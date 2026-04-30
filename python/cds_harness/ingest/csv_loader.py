"""CSV (+ sidecar JSON) → :class:`ClinicalTelemetryPayload`.

A CSV row stream encodes one :class:`TelemetrySample` per line. The
required reserved columns are ``wall_clock_utc`` and ``monotonic_ns``;
every remaining column must be a member of
:data:`cds_harness.ingest.canonical.CANONICAL_VITALS`. A sidecar
``<stem>.meta.json`` supplies the :class:`TelemetrySource` (mandatory)
and any :class:`DiscreteEvent` annotations (optional). Events are
bucketed into the latest sample whose ``monotonic_ns`` is ≤
``event.at_monotonic_ns``; events that predate the first sample attach
to the first sample.
"""

from __future__ import annotations

import bisect
import csv
import io
import json
from pathlib import Path

from cds_harness.ingest.canonical import CANONICAL_VITALS
from cds_harness.ingest.errors import (
    DuplicateMonotonicError,
    MalformedCsvError,
    MissingMetadataError,
    UnknownVitalError,
)
from cds_harness.ingest.timestamps import canonicalize_utc
from cds_harness.schema import (
    SCHEMA_VERSION,
    ClinicalTelemetryPayload,
    DiscreteEvent,
    TelemetrySample,
    TelemetrySource,
)

_RESERVED_COLUMNS: frozenset[str] = frozenset({"wall_clock_utc", "monotonic_ns"})


def load_csv(csv_path: Path) -> ClinicalTelemetryPayload:
    """Load a single CSV (+ sidecar) into a :class:`ClinicalTelemetryPayload`.

    Raises:
        MissingMetadataError: when ``<stem>.meta.json`` is absent.
        MalformedCsvError: on missing reserved columns or non-numeric cells.
        UnknownVitalError: on any vital column outside the canonical namespace.
        DuplicateMonotonicError: on repeated ``monotonic_ns`` across rows.
    """
    csv_path = Path(csv_path).resolve()
    meta_path = csv_path.with_suffix(".meta.json")
    if not meta_path.is_file():
        raise MissingMetadataError(
            f"CSV {csv_path.name!r} requires sidecar metadata at {meta_path.name!r}"
        )

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    csv_text = csv_path.read_text(encoding="utf-8")
    return load_csv_text(csv_text, meta, file_label=csv_path.name)


def load_csv_text(
    csv_text: str,
    meta: object,
    *,
    file_label: str = "<inline>",
) -> ClinicalTelemetryPayload:
    """In-memory variant of :func:`load_csv`.

    The CSV body and the sidecar-metadata dict are passed directly so the
    JSON-over-TCP boundary (constraint C6) can ingest payloads without a
    filesystem detour. ``file_label`` is the diagnostic name surfaced in
    error messages.
    """
    if not isinstance(meta, dict) or "source" not in meta:
        raise MissingMetadataError(
            f"sidecar metadata for {file_label!r} missing required 'source' object"
        )
    source = TelemetrySource.model_validate(meta["source"])
    raw_events = meta.get("events", [])
    events = [DiscreteEvent.model_validate(e) for e in raw_events]

    samples = _parse_csv_samples_from_text(csv_text, file_label)
    bucketed = _bucket_events_into_samples(samples, events, file_label=file_label)
    return ClinicalTelemetryPayload(
        schema_version=SCHEMA_VERSION,
        source=source,
        samples=bucketed,
    )


def _parse_csv_samples(csv_path: Path) -> list[TelemetrySample]:
    return _parse_csv_samples_from_text(
        csv_path.read_text(encoding="utf-8"),
        csv_path.name,
    )


def _parse_csv_samples_from_text(csv_text: str, file_label: str) -> list[TelemetrySample]:
    seen_monotonic: set[int] = set()
    samples: list[TelemetrySample] = []
    handle = io.StringIO(csv_text)
    reader = csv.DictReader(handle)
    if reader.fieldnames is None:
        raise MalformedCsvError(f"empty CSV {file_label!r}")
    header = list(reader.fieldnames)
    missing = _RESERVED_COLUMNS - set(header)
    if missing:
        raise MalformedCsvError(
            f"CSV {file_label!r} missing required columns: {sorted(missing)}"
        )
    vital_columns = [c for c in header if c not in _RESERVED_COLUMNS]
    for col in vital_columns:
        if col not in CANONICAL_VITALS:
            raise UnknownVitalError(
                f"CSV column {col!r} is not a canonical vital; "
                f"set={sorted(CANONICAL_VITALS)}"
            )
    for row_idx, row in enumerate(reader, start=2):  # row 1 is the header
        sample = _row_to_sample(row, vital_columns, file_label, row_idx)
        if sample.monotonic_ns in seen_monotonic:
            raise DuplicateMonotonicError(
                f"{file_label}: duplicate monotonic_ns={sample.monotonic_ns} "
                f"at row {row_idx}"
            )
        seen_monotonic.add(sample.monotonic_ns)
        samples.append(sample)
    return samples


def _row_to_sample(
    row: dict[str, str],
    vital_columns: list[str],
    file_label: str,
    row_idx: int,
) -> TelemetrySample:
    raw_ns = row.get("monotonic_ns", "").strip()
    try:
        monotonic = int(raw_ns)
    except ValueError as exc:
        raise MalformedCsvError(
            f"{file_label} row {row_idx}: monotonic_ns not integer: {raw_ns!r}"
        ) from exc
    if monotonic < 0:
        raise MalformedCsvError(
            f"{file_label} row {row_idx}: monotonic_ns must be ≥ 0 (got {monotonic})"
        )
    raw_clock = row.get("wall_clock_utc", "").strip()
    if not raw_clock:
        raise MalformedCsvError(f"{file_label} row {row_idx}: wall_clock_utc is empty")
    wall_clock = canonicalize_utc(raw_clock)

    vitals: dict[str, float] = {}
    for col in sorted(vital_columns):  # lexicographic — wire stability w/ Rust BTreeMap
        cell = (row.get(col) or "").strip()
        if not cell:
            continue
        try:
            vitals[col] = float(cell)
        except ValueError as exc:
            raise MalformedCsvError(
                f"{file_label} row {row_idx}: vital {col!r} not numeric: {cell!r}"
            ) from exc

    return TelemetrySample(
        wall_clock_utc=wall_clock,
        monotonic_ns=monotonic,
        vitals=vitals,
        events=[],
    )


def _bucket_events_into_samples(
    samples: list[TelemetrySample],
    events: list[DiscreteEvent],
    *,
    file_label: str = "<inline>",
) -> list[TelemetrySample]:
    if not samples:
        if events:
            raise MalformedCsvError(
                f"cannot attach sidecar events to an empty sample stream ({file_label})"
            )
        return samples
    ordered = sorted(samples, key=lambda s: s.monotonic_ns)
    boundaries = [s.monotonic_ns for s in ordered]
    buckets: list[list[DiscreteEvent]] = [[] for _ in ordered]
    for event in events:
        idx = bisect.bisect_right(boundaries, event.at_monotonic_ns) - 1
        if idx < 0:
            idx = 0
        buckets[idx].append(event)
    return [
        sample.model_copy(update={"events": list(bucket)})
        for sample, bucket in zip(ordered, buckets, strict=True)
    ]


__all__ = ["load_csv", "load_csv_text"]
