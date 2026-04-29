"""Pydantic v2 mirror of ``cds_kernel::schema::onionl``.

See ``crates/kernel/src/schema/onionl.rs`` for the canonical Rust
definition. Discriminated unions use ``kind`` as the discriminator field
(matches Serde ``tag = "kind"``).
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class SourceSpan(BaseModel):
    """Byte-offset projection back to the originating NL document.

    Constraint C4: every ``Atom`` MUST carry a ``SourceSpan`` so that an
    SMT-derived MUC can be projected back onto the offending textual fragment.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    start: int = Field(ge=0)
    end: int = Field(ge=0)
    doc_id: str


class Variable(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["variable"] = "variable"
    name: str


class Constant(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["constant"] = "constant"
    value: str


Term = Annotated[Variable | Constant, Field(discriminator="kind")]


class Scope(BaseModel):
    """A textual region: document / section / guideline / sub-clause."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["scope"] = "scope"
    id: str
    scope_kind: str
    children: list[OnionLNode]


class Relation(BaseModel):
    """An n-ary logical relation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["relation"] = "relation"
    op: str
    args: list[OnionLNode]


class IndicatorConstraint(BaseModel):
    """A guarded indicator: ``guard ⇒ body``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["indicator_constraint"] = "indicator_constraint"
    guard: OnionLNode
    body: OnionLNode


class Atom(BaseModel):
    """A first-order atom — only variant that participates in MUC → text projection."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["atom"] = "atom"
    predicate: str
    terms: list[Term]
    source_span: SourceSpan


OnionLNode = Annotated[
    Scope | Relation | IndicatorConstraint | Atom,
    Field(discriminator="kind"),
]


class OnionLIRTree(BaseModel):
    """Top-level IR envelope — schema version + a single root node."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str
    root: OnionLNode


# Resolve forward refs for the recursive variants.
Scope.model_rebuild()
Relation.model_rebuild()
IndicatorConstraint.model_rebuild()
Atom.model_rebuild()
OnionLIRTree.model_rebuild()
