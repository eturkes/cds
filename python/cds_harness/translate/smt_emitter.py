"""Lower an :class:`OnionLIRTree` to an :class:`SmtConstraintMatrix`.

Phase 0 lowering rules (see ADR-012):

* The root :class:`Scope`'s direct children form the *clause set*. Each
  clause becomes a single :class:`LabelledAssertion` with a stable label
  (``clause_NNN``) and a ``provenance`` string of the form
  ``atom:<doc_id>:<start>-<end>`` taken from the first :class:`Atom`
  reached by a left-to-right walk. This pattern is verbatim from the
  Task 2 golden fixture so MUC reverse-mapping (Task 6) is mechanical.
* :class:`Relation` ops are translated through :data:`OP_MAP`; unknown
  ops raise :class:`UnsupportedOpError`.
* :class:`IndicatorConstraint` lowers to ``(=> guard body)``.
* :class:`Atom` lowering:

  - ``predicate == "literal"`` with one :class:`Constant` term emits the
    constant value verbatim (numeric literal).
  - Otherwise the atom is treated as a 0-ary scalar symbol with SMT sort
    ``Real`` — the predicate name is its own SMT identifier. Any single
    :class:`Variable` term is descriptive and elided (matches the
    Task 2 golden's ``has_diagnosis P diabetes`` ⇒ ``hba1c`` pattern).
    Anything richer raises :class:`UnsupportedNodeError` until the
    deductive engine (Task 5) and SMT integration (Task 6) widen the
    contract.

The emitter also exposes :func:`serialize` (full SMT-LIBv2 script as a
string) and :func:`smt_sanity_check` (run the script through the
``z3-solver`` Python binding and return ``"sat"`` / ``"unsat"`` /
``"unknown"`` — the Task 4 gate).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Final

from cds_harness.schema import (
    SCHEMA_VERSION,
    Atom,
    Constant,
    IndicatorConstraint,
    LabelledAssertion,
    OnionLIRTree,
    OnionLNode,
    Relation,
    Scope,
    SmtConstraintMatrix,
    Term,
    Variable,
)
from cds_harness.translate.errors import UnsupportedNodeError, UnsupportedOpError

OP_MAP: Final[dict[str, str]] = {
    "and": "and",
    "or": "or",
    "not": "not",
    "implies": "=>",
    "equals": "=",
    "less_than": "<",
    "less_or_equal": "<=",
    "greater_than": ">",
    "greater_or_equal": ">=",
    "plus": "+",
    "minus": "-",
    "times": "*",
    "divide": "/",
}
"""Recognised :class:`Relation` ops → SMT-LIBv2 operator tokens."""

LITERAL_PREDICATE: Final[str] = "literal"
DEFAULT_LOGIC: Final[str] = "QF_LRA"
THEORIES_BY_LOGIC: Final[dict[str, list[str]]] = {
    "QF_LRA": ["LRA"],
    "QF_LIA": ["LIA"],
    "QF_LIRA": ["LIA", "LRA"],
}


def emit_smt(
    tree: OnionLIRTree,
    *,
    logic: str = DEFAULT_LOGIC,
) -> SmtConstraintMatrix:
    """Lower a validated :class:`OnionLIRTree` into an :class:`SmtConstraintMatrix`.

    Parameters
    ----------
    tree:
        The IR tree produced by
        :func:`cds_harness.translate.clover.translate_guideline`.
    logic:
        The SMT-LIBv2 logic to set in the preamble. Defaults to
        ``QF_LRA`` (quantifier-free linear real arithmetic) — the
        Phase 0 home logic.
    """
    symbols = _collect_symbols(tree.root)
    preamble_lines = [f"(set-logic {logic})"]
    preamble_lines.extend(
        f"(declare-fun {name} () {sort})" for name, sort in sorted(symbols.items())
    )
    preamble = "\n".join(preamble_lines) + "\n"

    assumptions = list(_collect_assumptions(tree.root))
    theories = THEORIES_BY_LOGIC.get(logic, [logic])
    return SmtConstraintMatrix(
        schema_version=SCHEMA_VERSION,
        logic=logic,
        theories=theories,
        preamble=preamble,
        assumptions=assumptions,
    )


def serialize(matrix: SmtConstraintMatrix, *, include_check_sat: bool = True) -> str:
    """Render the full SMT-LIBv2 script (preamble + (assert …) + (check-sat))."""
    lines = [matrix.preamble.rstrip("\n")]
    for assumption in matrix.assumptions:
        if assumption.enabled:
            lines.append(f"(assert {assumption.formula})")
    if include_check_sat:
        lines.append("(check-sat)")
    return "\n".join(lines) + "\n"


def smt_sanity_check(matrix: SmtConstraintMatrix) -> str:
    """Run the script through Z3 and return ``"sat"`` / ``"unsat"`` / ``"unknown"``.

    Uses the ``z3-solver`` Python binding (ADR-001). The full
    binary-warden subprocess wiring (ADR-004) lands in Task 6 alongside
    MUC extraction; for the Task 4 gate the in-process binding is
    sufficient.
    """
    import z3

    script = serialize(matrix, include_check_sat=False)
    asts = z3.parse_smt2_string(script)
    solver = z3.Solver()
    solver.add(asts)
    return str(solver.check())


def _collect_symbols(root: OnionLNode) -> dict[str, str]:
    symbols: dict[str, str] = {}
    for atom in _walk_atoms(root):
        if atom.predicate == LITERAL_PREDICATE:
            continue
        # Phase 0: every non-literal atom lowers to a 0-ary Real symbol.
        symbols[atom.predicate] = "Real"
    return symbols


def _collect_assumptions(root: OnionLNode) -> Iterator[LabelledAssertion]:
    if isinstance(root, Scope):
        for ord_, child in enumerate(root.children):
            yield _build_assertion(child, ord_=ord_)
        return
    yield _build_assertion(root, ord_=0)


def _build_assertion(node: OnionLNode, *, ord_: int) -> LabelledAssertion:
    formula = _emit_node(node)
    label = f"clause_{ord_:03d}"
    provenance = _atom_provenance(node)
    return LabelledAssertion(
        label=label,
        formula=formula,
        enabled=True,
        provenance=provenance,
    )


def _atom_provenance(node: OnionLNode) -> str | None:
    for atom in _walk_atoms(node):
        return f"atom:{atom.source_span.doc_id}:{atom.source_span.start}-{atom.source_span.end}"
    return None


def _emit_node(node: OnionLNode) -> str:
    if isinstance(node, Atom):
        return _emit_atom(node)
    if isinstance(node, Relation):
        try:
            op_token = OP_MAP[node.op]
        except KeyError as exc:
            raise UnsupportedOpError(
                f"relation op {node.op!r} is outside the Phase 0 OP map"
            ) from exc
        if not node.args:
            raise UnsupportedNodeError(f"relation op={node.op!r} requires at least one argument")
        rendered = " ".join(_emit_node(arg) for arg in node.args)
        return f"({op_token} {rendered})"
    if isinstance(node, IndicatorConstraint):
        return f"(=> {_emit_node(node.guard)} {_emit_node(node.body)})"
    if isinstance(node, Scope):
        raise UnsupportedNodeError(
            "nested Scope nodes are not yet supported by the Phase 0 emitter"
        )
    raise UnsupportedNodeError(f"unrecognised OnionL node: {type(node).__name__}")


def _emit_atom(atom: Atom) -> str:
    if atom.predicate == LITERAL_PREDICATE:
        if len(atom.terms) != 1 or not isinstance(atom.terms[0], Constant):
            raise UnsupportedNodeError(
                "atom with predicate='literal' must carry exactly one Constant term"
            )
        return atom.terms[0].value
    if not atom.terms:
        return atom.predicate
    if len(atom.terms) == 1 and isinstance(atom.terms[0], Variable):
        # Patient-scoped descriptive variable — elide for Phase 0.
        return atom.predicate
    raise UnsupportedNodeError(
        f"atom predicate={atom.predicate!r} with terms={_describe_terms(atom.terms)} "
        "is not supported by the Phase 0 emitter"
    )


def _describe_terms(terms: list[Term]) -> str:
    parts: list[str] = []
    for term in terms:
        if isinstance(term, Variable):
            parts.append(f"Variable({term.name!r})")
        else:
            parts.append(f"Constant({term.value!r})")
    return "[" + ", ".join(parts) + "]"


def _walk_atoms(node: OnionLNode) -> Iterator[Atom]:
    if isinstance(node, Atom):
        yield node
    elif isinstance(node, Scope):
        for child in node.children:
            yield from _walk_atoms(child)
    elif isinstance(node, Relation):
        for arg in node.args:
            yield from _walk_atoms(arg)
    elif isinstance(node, IndicatorConstraint):
        yield from _walk_atoms(node.guard)
        yield from _walk_atoms(node.body)


__all__ = [
    "DEFAULT_LOGIC",
    "LITERAL_PREDICATE",
    "OP_MAP",
    "THEORIES_BY_LOGIC",
    "emit_smt",
    "serialize",
    "smt_sanity_check",
]
