"""Pydantic v2 mirror of ``cds_kernel::schema::smt``.

See ``crates/kernel/src/schema/smt.rs`` for the canonical Rust definition.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class LabelledAssertion(BaseModel):
    """A retractable, named SMT-LIBv2 assertion (subject to ``check-sat-assuming``)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    label: str
    formula: str
    enabled: bool
    provenance: str | None = None


class SmtConstraintMatrix(BaseModel):
    """The SMT-LIBv2 program presented to Z3 / cvc5."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str
    logic: str
    theories: list[str]
    preamble: str
    assumptions: list[LabelledAssertion]
