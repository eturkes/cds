"""Ingestion (Task 3) — sample dataset round-trip + boundary-policy errors.

Asserts:

1. The shipped CSV (+ sidecar) and JSON-envelope samples ingest cleanly
   into ``ClinicalTelemetryPayload`` instances, with values bit-stable
   under a re-serialization round-trip.
2. The directory dispatcher discovers both forms and skips sidecar
   metadata files.
3. Every documented boundary-policy violation raises the right
   ``IngestError`` subclass: duplicate ``monotonic_ns``, unknown vital
   column, missing required column, missing sidecar, malformed CSV cell,
   and non-UTC / naive timestamps.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from cds_harness.ingest.canonical import CANONICAL_VITALS
from cds_harness.ingest.cli import run as cli_run
from cds_harness.ingest.csv_loader import load_csv
from cds_harness.ingest.errors import (
    DuplicateMonotonicError,
    IngestError,
    InvalidTimestampError,
    MalformedCsvError,
    MissingMetadataError,
    UnknownVitalError,
)
from cds_harness.ingest.json_loader import load_json
from cds_harness.ingest.loader import discover_payloads
from cds_harness.ingest.timestamps import canonicalize_utc, parse_utc_timestamp
from cds_harness.schema import (
    SCHEMA_VERSION,
    ClinicalTelemetryPayload,
)


def _project_root() -> Path:
    here = Path(__file__).resolve()
    for ancestor in (here, *here.parents):
        if (ancestor / "Cargo.toml").is_file():
            return ancestor
    raise RuntimeError("project root not found (no Cargo.toml ancestor)")


SAMPLE_DIR = _project_root() / "data" / "sample"


# ----- canonical namespace --------------------------------------------------


def test_canonical_vitals_namespace_is_lower_snake() -> None:
    assert "heart_rate_bpm" in CANONICAL_VITALS
    assert "spo2_percent" in CANONICAL_VITALS
    for key in CANONICAL_VITALS:
        assert key.islower(), f"non-lowercase canonical vital: {key!r}"
        assert " " not in key
        assert "-" not in key


# ----- timestamp validators -------------------------------------------------


def test_canonicalize_utc_pads_microseconds_when_absent() -> None:
    assert canonicalize_utc("2026-04-29T12:55:00Z") == "2026-04-29T12:55:00.000000Z"


def test_canonicalize_utc_preserves_microseconds_when_present() -> None:
    assert canonicalize_utc("2026-04-29T12:55:00.123456Z") == "2026-04-29T12:55:00.123456Z"


def test_canonicalize_utc_rejects_offset_form() -> None:
    with pytest.raises(InvalidTimestampError):
        canonicalize_utc("2026-04-29T12:55:00+02:00")


def test_canonicalize_utc_rejects_naive() -> None:
    with pytest.raises(InvalidTimestampError):
        canonicalize_utc("2026-04-29T12:55:00")


def test_parse_utc_rejects_non_string_input() -> None:
    with pytest.raises(InvalidTimestampError):
        parse_utc_timestamp(12345)  # type: ignore[arg-type]


# ----- CSV loader -----------------------------------------------------------


def test_csv_sample_ingests_into_payload() -> None:
    payload = load_csv(SAMPLE_DIR / "icu-monitor-01.csv")
    assert isinstance(payload, ClinicalTelemetryPayload)
    assert payload.schema_version == SCHEMA_VERSION
    assert payload.source.device_id == "icu-monitor-01"
    assert payload.source.patient_pseudo_id == "pseudo-abc123"
    assert len(payload.samples) == 10
    first = payload.samples[0]
    assert first.monotonic_ns == 1_000_000_000_000
    assert first.wall_clock_utc == "2026-04-29T12:55:00.000000Z"
    # Vitals dict must serialize in lexicographic order to match Rust BTreeMap.
    assert list(first.vitals.keys()) == sorted(first.vitals.keys())
    # The single sidecar event lands in exactly one bucket.
    bucketed_events = sum(len(s.events) for s in payload.samples)
    assert bucketed_events == 1


def test_csv_sample_round_trips_through_json() -> None:
    payload = load_csv(SAMPLE_DIR / "icu-monitor-01.csv")
    rehydrated = ClinicalTelemetryPayload.model_validate_json(payload.model_dump_json())
    assert rehydrated == payload


def test_csv_rejects_duplicate_monotonic_ns(tmp_path: Path) -> None:
    csv_file = tmp_path / "dup.csv"
    csv_file.write_text(
        "wall_clock_utc,monotonic_ns,heart_rate_bpm\n"
        "2026-04-29T12:55:00Z,1000,70.0\n"
        "2026-04-29T12:55:01Z,1000,71.0\n",
        encoding="utf-8",
    )
    (tmp_path / "dup.meta.json").write_text(
        json.dumps({"source": {"device_id": "d", "patient_pseudo_id": "p"}}),
        encoding="utf-8",
    )
    with pytest.raises(DuplicateMonotonicError):
        load_csv(csv_file)


def test_csv_rejects_unknown_vital_column(tmp_path: Path) -> None:
    csv_file = tmp_path / "u.csv"
    csv_file.write_text(
        "wall_clock_utc,monotonic_ns,unknown_metric\n"
        "2026-04-29T12:55:00Z,1000,42.0\n",
        encoding="utf-8",
    )
    (tmp_path / "u.meta.json").write_text(
        json.dumps({"source": {"device_id": "d", "patient_pseudo_id": "p"}}),
        encoding="utf-8",
    )
    with pytest.raises(UnknownVitalError):
        load_csv(csv_file)


def test_csv_rejects_missing_sidecar(tmp_path: Path) -> None:
    csv_file = tmp_path / "lonely.csv"
    csv_file.write_text(
        "wall_clock_utc,monotonic_ns\n2026-04-29T12:55:00Z,1000\n",
        encoding="utf-8",
    )
    with pytest.raises(MissingMetadataError):
        load_csv(csv_file)


def test_csv_rejects_missing_required_column(tmp_path: Path) -> None:
    csv_file = tmp_path / "m.csv"
    csv_file.write_text("wall_clock_utc\n2026-04-29T12:55:00Z\n", encoding="utf-8")
    (tmp_path / "m.meta.json").write_text(
        json.dumps({"source": {"device_id": "d", "patient_pseudo_id": "p"}}),
        encoding="utf-8",
    )
    with pytest.raises(MalformedCsvError):
        load_csv(csv_file)


def test_csv_rejects_negative_monotonic_ns(tmp_path: Path) -> None:
    csv_file = tmp_path / "neg.csv"
    csv_file.write_text(
        "wall_clock_utc,monotonic_ns\n2026-04-29T12:55:00Z,-1\n",
        encoding="utf-8",
    )
    (tmp_path / "neg.meta.json").write_text(
        json.dumps({"source": {"device_id": "d", "patient_pseudo_id": "p"}}),
        encoding="utf-8",
    )
    with pytest.raises(MalformedCsvError):
        load_csv(csv_file)


def test_csv_rejects_non_numeric_vital(tmp_path: Path) -> None:
    csv_file = tmp_path / "bad.csv"
    csv_file.write_text(
        "wall_clock_utc,monotonic_ns,heart_rate_bpm\n2026-04-29T12:55:00Z,1000,oops\n",
        encoding="utf-8",
    )
    (tmp_path / "bad.meta.json").write_text(
        json.dumps({"source": {"device_id": "d", "patient_pseudo_id": "p"}}),
        encoding="utf-8",
    )
    with pytest.raises(MalformedCsvError):
        load_csv(csv_file)


def test_csv_rejects_naive_timestamp(tmp_path: Path) -> None:
    csv_file = tmp_path / "nz.csv"
    csv_file.write_text(
        "wall_clock_utc,monotonic_ns,heart_rate_bpm\n2026-04-29T12:55:00,1000,70.0\n",
        encoding="utf-8",
    )
    (tmp_path / "nz.meta.json").write_text(
        json.dumps({"source": {"device_id": "d", "patient_pseudo_id": "p"}}),
        encoding="utf-8",
    )
    with pytest.raises(InvalidTimestampError):
        load_csv(csv_file)


def test_csv_sidecar_must_have_source(tmp_path: Path) -> None:
    csv_file = tmp_path / "s.csv"
    csv_file.write_text(
        "wall_clock_utc,monotonic_ns\n2026-04-29T12:55:00Z,1000\n",
        encoding="utf-8",
    )
    (tmp_path / "s.meta.json").write_text(json.dumps({"events": []}), encoding="utf-8")
    with pytest.raises(MissingMetadataError):
        load_csv(csv_file)


def test_csv_sparse_vitals_are_skipped_not_zeroed(tmp_path: Path) -> None:
    csv_file = tmp_path / "sparse.csv"
    csv_file.write_text(
        "wall_clock_utc,monotonic_ns,heart_rate_bpm,spo2_percent\n"
        "2026-04-29T12:55:00Z,1000,70.0,\n",
        encoding="utf-8",
    )
    (tmp_path / "sparse.meta.json").write_text(
        json.dumps({"source": {"device_id": "d", "patient_pseudo_id": "p"}}),
        encoding="utf-8",
    )
    payload = load_csv(csv_file)
    sample = payload.samples[0]
    assert "heart_rate_bpm" in sample.vitals
    assert "spo2_percent" not in sample.vitals


# ----- JSON loader ----------------------------------------------------------


def test_json_envelope_ingests_cleanly() -> None:
    payload = load_json(SAMPLE_DIR / "icu-monitor-02.json")
    assert payload.source.device_id == "icu-monitor-02"
    assert len(payload.samples) == 2
    assert payload.samples[0].vitals["heart_rate_bpm"] == 88.0
    assert payload.samples[1].events[0].name == "low_spo2_alarm"


def test_json_loader_rejects_unknown_vital(tmp_path: Path) -> None:
    bad = {
        "schema_version": SCHEMA_VERSION,
        "source": {"device_id": "d", "patient_pseudo_id": "p"},
        "samples": [
            {
                "wall_clock_utc": "2026-04-29T12:55:00Z",
                "monotonic_ns": 1000,
                "vitals": {"weird_metric": 1.0},
                "events": [],
            }
        ],
    }
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(UnknownVitalError):
        load_json(path)


def test_json_loader_rejects_duplicate_monotonic(tmp_path: Path) -> None:
    bad = {
        "schema_version": SCHEMA_VERSION,
        "source": {"device_id": "d", "patient_pseudo_id": "p"},
        "samples": [
            {
                "wall_clock_utc": "2026-04-29T12:55:00Z",
                "monotonic_ns": 1000,
                "vitals": {},
                "events": [],
            },
            {
                "wall_clock_utc": "2026-04-29T12:55:01Z",
                "monotonic_ns": 1000,
                "vitals": {},
                "events": [],
            },
        ],
    }
    path = tmp_path / "dup.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(DuplicateMonotonicError):
        load_json(path)


def test_json_loader_rejects_extra_top_level_field(tmp_path: Path) -> None:
    bad = {
        "schema_version": SCHEMA_VERSION,
        "source": {"device_id": "d", "patient_pseudo_id": "p"},
        "samples": [],
        "rogue_field": "boom",
    }
    path = tmp_path / "x.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ValidationError):  # surfaced from frozen extra="forbid"
        load_json(path)


# ----- directory dispatcher -------------------------------------------------


def test_discover_walks_sample_directory() -> None:
    found = list(discover_payloads(SAMPLE_DIR))
    devices = {payload.source.device_id for _, payload in found}
    assert {"icu-monitor-01", "icu-monitor-02"}.issubset(devices)
    # Sidecar must NOT be returned as a payload.
    paths = {path.name for path, _ in found}
    assert "icu-monitor-01.meta.json" not in paths


def test_discover_rejects_missing_path(tmp_path: Path) -> None:
    with pytest.raises(IngestError):
        list(discover_payloads(tmp_path / "does-not-exist"))


# ----- CLI ------------------------------------------------------------------


def test_cli_writes_payload_array(tmp_path: Path) -> None:
    out = tmp_path / "out.json"
    rc = cli_run([str(SAMPLE_DIR), "--output", str(out), "--pretty"])
    assert rc == 0
    body = json.loads(out.read_text(encoding="utf-8"))
    assert isinstance(body, list)
    assert len(body) == 2
    for record in body:
        assert "source_path" in record
        assert "payload" in record
        ClinicalTelemetryPayload.model_validate(record["payload"])


def test_cli_returns_two_for_missing_path(tmp_path: Path) -> None:
    rc = cli_run([str(tmp_path / "nope")])
    assert rc == 2
