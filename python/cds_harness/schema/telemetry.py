"""Pydantic v2 mirror of ``cds_kernel::schema::telemetry``.

See ``crates/kernel/src/schema/telemetry.rs`` for the canonical Rust
definition. All field names, types, and JSON serialization must match
exactly — round-trip enforced by ``tests/golden/clinical_telemetry_payload.json``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TelemetrySource(BaseModel):
    """Provenance for a telemetry stream."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    device_id: str
    patient_pseudo_id: str


class DiscreteEvent(BaseModel):
    """A non-continuous clinical event (alarm, intervention, annotation)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    at_monotonic_ns: int = Field(ge=0)
    data: Any


class TelemetrySample(BaseModel):
    """A single instant of physiological observation.

    ``vitals`` keys serialize in insertion order on the Python side; the
    Rust side uses ``BTreeMap`` (lexicographic). Ingestion stages should
    insert keys in sorted order to keep payload byte-stable across both.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    wall_clock_utc: str
    monotonic_ns: int = Field(ge=0)
    vitals: dict[str, float]
    events: list[DiscreteEvent]


class ClinicalTelemetryPayload(BaseModel):
    """Top-level telemetry envelope."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str
    source: TelemetrySource
    samples: list[TelemetrySample]
