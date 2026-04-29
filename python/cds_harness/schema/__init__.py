"""Phase 0 conceptual schemas (Task 2).

Pydantic v2 mirrors of the four canonical wire-format types defined by the
Rust kernel in ``crates/kernel/src/schema/``. Every model is frozen and
validates on construction; the on-the-wire JSON shape is byte-for-byte
identical to the Rust serde output (verified by the Rust+Python golden
fixture tests under ``tests/golden/``).

When a wire-format-breaking change lands, bump ``SCHEMA_VERSION`` in BOTH
this module and ``crates/kernel/src/schema/mod.rs``. The two values must
match.
"""

from __future__ import annotations

from cds_harness.schema.onionl import (
    Atom,
    Constant,
    IndicatorConstraint,
    OnionLIRTree,
    OnionLNode,
    Relation,
    Scope,
    SourceSpan,
    Term,
    Variable,
)
from cds_harness.schema.smt import LabelledAssertion, SmtConstraintMatrix
from cds_harness.schema.telemetry import (
    ClinicalTelemetryPayload,
    DiscreteEvent,
    TelemetrySample,
    TelemetrySource,
)
from cds_harness.schema.verification import FormalVerificationTrace

SCHEMA_VERSION: str = "0.1.0"

__all__ = [
    "SCHEMA_VERSION",
    "Atom",
    "ClinicalTelemetryPayload",
    "Constant",
    "DiscreteEvent",
    "FormalVerificationTrace",
    "IndicatorConstraint",
    "LabelledAssertion",
    "OnionLIRTree",
    "OnionLNode",
    "Relation",
    "Scope",
    "SmtConstraintMatrix",
    "SourceSpan",
    "TelemetrySample",
    "TelemetrySource",
    "Term",
    "Variable",
]
