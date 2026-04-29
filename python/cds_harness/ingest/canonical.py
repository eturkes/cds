"""Canonical vital-key namespace for Phase 0 telemetry ingestion.

The namespace is intentionally small and lower-snake-case so that the wire
format is byte-stable across the Rust ↔ Python boundary (ADR-010) and the
deductive engine (Task 5) can address scalars by predictable name.

Adding a new canonical vital is a coordinated edit: bump
:data:`cds_harness.schema.SCHEMA_VERSION`, mirror the addition in any
downstream rule files (Tasks 4-6), and ship a fresh golden fixture.
"""

from __future__ import annotations

CANONICAL_VITALS: frozenset[str] = frozenset(
    {
        "heart_rate_bpm",
        "spo2_percent",
        "systolic_mmhg",
        "diastolic_mmhg",
        "temp_celsius",
        "respiratory_rate_bpm",
    }
)

__all__ = ["CANONICAL_VITALS"]
