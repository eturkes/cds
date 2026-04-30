"""Whole-envelope JSON → :class:`ClinicalTelemetryPayload`.

The input file's top-level shape mirrors the schema exactly. The loader
runs structural validation through Pydantic, then re-canonicalizes every
wall-clock timestamp and applies the boundary policies (canonical vital
namespace, unique ``monotonic_ns``).
"""

from __future__ import annotations

import json
from pathlib import Path

from cds_harness.ingest.timestamps import canonicalize_utc
from cds_harness.ingest.validation import (
    assert_canonical_vitals,
    assert_unique_monotonic,
)
from cds_harness.schema import ClinicalTelemetryPayload


def load_json_envelope(raw: object) -> ClinicalTelemetryPayload:
    """Validate + canonicalize a parsed JSON envelope (dict-like).

    Mirrors :func:`load_json` but operates on an in-memory object. Useful
    on the JSON-over-TCP boundary where the wire delivers the envelope
    directly (constraint C6) without a filesystem detour.
    """
    payload = ClinicalTelemetryPayload.model_validate(raw)
    canonical_samples = [
        sample.model_copy(
            update={"wall_clock_utc": canonicalize_utc(sample.wall_clock_utc)}
        )
        for sample in payload.samples
    ]
    assert_unique_monotonic(canonical_samples)
    assert_canonical_vitals(canonical_samples)
    return payload.model_copy(update={"samples": canonical_samples})


def load_json(json_path: Path) -> ClinicalTelemetryPayload:
    """Load a fully-formed payload JSON envelope."""
    raw = json.loads(Path(json_path).read_text(encoding="utf-8"))
    return load_json_envelope(raw)


__all__ = ["load_json", "load_json_envelope"]
