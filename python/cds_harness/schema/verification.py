"""Pydantic v2 mirror of ``cds_kernel::schema::verification``.

See ``crates/kernel/src/schema/verification.rs`` for the canonical Rust
definition.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class FormalVerificationTrace(BaseModel):
    """Outcome of one SMT + ITP verification cycle.

    On ``sat = False``, ``muc`` enumerates the assertion labels (matching
    ``LabelledAssertion.label`` and projecting back to ``Atom.source_span``)
    that participate in a Minimal Unsatisfiable Core. ``alethe_proof``
    carries the cvc5-emitted certificate for Lean 4 re-checking (Task 7).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str
    sat: bool
    muc: list[str]
    alethe_proof: str | None = None
