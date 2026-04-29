"""Autoformalization translator: clinical guideline NL → OnionL IR → SMT-LIBv2.

Phase 0 wiring (Task 4) for the CLOVER + NL2LOGIC pipeline (ADR-005). The
LLM-touched stage is hidden behind
:class:`~cds_harness.translate.adapter.AutoformalAdapter` so deterministic
test fixtures (:class:`~cds_harness.translate.adapter.RecordedAdapter`)
can swap the network call out for a recorded transcript. The SMT lowering
(:func:`~cds_harness.translate.smt_emitter.emit_smt`) emits an
:class:`~cds_harness.schema.SmtConstraintMatrix` whose ``LabelledAssertion``
labels and ``provenance`` strings preserve the link from each top-level
clause back to its originating :class:`~cds_harness.schema.SourceSpan`,
priming the MUC reverse-projection wiring for Task 6.
"""

from __future__ import annotations

from cds_harness.translate.adapter import (
    AutoformalAdapter,
    LiveAdapter,
    RecordedAdapter,
)
from cds_harness.translate.clover import (
    GUIDELINE_SUFFIX,
    SIDECAR_SUFFIX,
    discover_translations,
    translate_guideline,
    translate_path,
)
from cds_harness.translate.errors import (
    InvalidGuidelineError,
    MissingFixtureError,
    TranslateError,
    UnsupportedNodeError,
    UnsupportedOpError,
)
from cds_harness.translate.smt_emitter import (
    DEFAULT_LOGIC,
    LITERAL_PREDICATE,
    OP_MAP,
    THEORIES_BY_LOGIC,
    emit_smt,
    serialize,
    smt_sanity_check,
)

__all__ = [
    "DEFAULT_LOGIC",
    "GUIDELINE_SUFFIX",
    "LITERAL_PREDICATE",
    "OP_MAP",
    "SIDECAR_SUFFIX",
    "THEORIES_BY_LOGIC",
    "AutoformalAdapter",
    "InvalidGuidelineError",
    "LiveAdapter",
    "MissingFixtureError",
    "RecordedAdapter",
    "TranslateError",
    "UnsupportedNodeError",
    "UnsupportedOpError",
    "discover_translations",
    "emit_smt",
    "serialize",
    "smt_sanity_check",
    "translate_guideline",
    "translate_path",
]
