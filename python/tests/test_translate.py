"""Tests for ``cds_harness.translate`` (Task 4 — autoformalization translator).

Covers:
* :class:`RecordedAdapter` lookup, missing-fixture, and schema-violation paths.
* :func:`translate_guideline` source-span validation (doc_id mismatch and
  out-of-bounds byte ranges).
* :func:`translate_path` and :func:`discover_translations` directory walk
  semantics (sorted iteration, sidecar skip, file vs directory handling).
* :func:`emit_smt` lowering: symbol-table extraction, OP_MAP coverage,
  IndicatorConstraint lowering, literal handling, error paths for
  unsupported nodes/ops.
* :func:`smt_sanity_check` returns ``"sat"`` for the consistent fixture and
  ``"unsat"`` for the contradictory fixture (the Phase 0 gate).
* CLI exit codes (``0`` happy, ``1`` translate error, ``2`` missing path).
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

from cds_harness.schema import (
    SCHEMA_VERSION,
    Atom,
    Constant,
    IndicatorConstraint,
    OnionLIRTree,
    Relation,
    Scope,
    SourceSpan,
    Variable,
)
from cds_harness.translate import (
    DEFAULT_LOGIC,
    OP_MAP,
    InvalidGuidelineError,
    LiveAdapter,
    MissingFixtureError,
    RecordedAdapter,
    TranslateError,
    UnsupportedNodeError,
    UnsupportedOpError,
    discover_translations,
    emit_smt,
    serialize,
    smt_sanity_check,
    translate_guideline,
    translate_path,
)
from cds_harness.translate.cli import build_parser, run

# ---------------------------------------------------------------------------
# Project anchors


def _project_root() -> Path:
    here = Path(__file__).resolve()
    for ancestor in (here, *here.parents):
        if (ancestor / "Cargo.toml").is_file():
            return ancestor
    raise RuntimeError("could not locate project root (no Cargo.toml ancestor)")


GUIDELINES_DIR = _project_root() / "data" / "guidelines"
HYPOXEMIA_TXT = GUIDELINES_DIR / "hypoxemia-trigger.txt"
CONTRADICTORY_TXT = GUIDELINES_DIR / "contradictory-bound.txt"


# ---------------------------------------------------------------------------
# Helpers


def _build_simple_tree(doc_id: str = "stub") -> OnionLIRTree:
    return OnionLIRTree(
        schema_version=SCHEMA_VERSION,
        root=Scope(
            id=doc_id,
            scope_kind="guideline",
            children=[
                Relation(
                    op="less_than",
                    args=[
                        Atom(
                            predicate="spo2",
                            terms=[],
                            source_span=SourceSpan(start=0, end=4, doc_id=doc_id),
                        ),
                        Atom(
                            predicate="literal",
                            terms=[Constant(value="100.0")],
                            source_span=SourceSpan(start=5, end=8, doc_id=doc_id),
                        ),
                    ],
                ),
            ],
        ),
    )


# ---------------------------------------------------------------------------
# RecordedAdapter


def test_recorded_adapter_loads_fixture() -> None:
    adapter = RecordedAdapter(GUIDELINES_DIR)
    text = HYPOXEMIA_TXT.read_text(encoding="utf-8")
    root = adapter.formalize(doc_id="hypoxemia-trigger", text=text)
    assert isinstance(root, Scope)
    assert root.id == "hypoxemia-trigger"
    assert len(root.children) == 2


def test_recorded_adapter_missing_fixture_raises(tmp_path: Path) -> None:
    adapter = RecordedAdapter(tmp_path)
    with pytest.raises(MissingFixtureError):
        adapter.formalize(doc_id="nope", text="anything")


def test_recorded_adapter_invalid_json_raises(tmp_path: Path) -> None:
    (tmp_path / "broken.recorded.json").write_text("{not json", encoding="utf-8")
    adapter = RecordedAdapter(tmp_path)
    with pytest.raises(TranslateError):
        adapter.formalize(doc_id="broken", text="")


def test_recorded_adapter_schema_mismatch_raises(tmp_path: Path) -> None:
    (tmp_path / "wrong.recorded.json").write_text(
        json.dumps({"schema_version": "0.1.0", "root": {"kind": "atom"}}),
        encoding="utf-8",
    )
    adapter = RecordedAdapter(tmp_path)
    with pytest.raises(TranslateError):
        adapter.formalize(doc_id="wrong", text="")


def test_live_adapter_is_a_phase0_stub() -> None:
    adapter = LiveAdapter()
    with pytest.raises(NotImplementedError):
        adapter.formalize(doc_id="x", text="y")


# ---------------------------------------------------------------------------
# translate_guideline / source-span validation


def test_translate_guideline_happy_path() -> None:
    adapter = RecordedAdapter(GUIDELINES_DIR)
    text = HYPOXEMIA_TXT.read_text(encoding="utf-8")
    tree = translate_guideline(doc_id="hypoxemia-trigger", text=text, adapter=adapter)
    assert tree.schema_version == SCHEMA_VERSION
    assert isinstance(tree.root, Scope)


def test_translate_guideline_rejects_doc_id_mismatch(tmp_path: Path) -> None:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "root": {
            "kind": "scope",
            "id": "doc",
            "scope_kind": "guideline",
            "children": [
                {
                    "kind": "atom",
                    "predicate": "spo2",
                    "terms": [],
                    "source_span": {"start": 0, "end": 1, "doc_id": "wrong-doc"},
                },
            ],
        },
    }
    (tmp_path / "doc.recorded.json").write_text(json.dumps(payload), encoding="utf-8")
    adapter = RecordedAdapter(tmp_path)
    with pytest.raises(InvalidGuidelineError, match="doc_id="):
        translate_guideline(doc_id="doc", text="x", adapter=adapter)


def test_translate_guideline_rejects_out_of_bounds_span(tmp_path: Path) -> None:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "root": {
            "kind": "scope",
            "id": "doc",
            "scope_kind": "guideline",
            "children": [
                {
                    "kind": "atom",
                    "predicate": "spo2",
                    "terms": [],
                    "source_span": {"start": 0, "end": 99, "doc_id": "doc"},
                },
            ],
        },
    }
    (tmp_path / "doc.recorded.json").write_text(json.dumps(payload), encoding="utf-8")
    adapter = RecordedAdapter(tmp_path)
    with pytest.raises(InvalidGuidelineError, match="outside source bounds"):
        translate_guideline(doc_id="doc", text="abc", adapter=adapter)


def test_translate_guideline_accepts_unicode_byte_offsets(tmp_path: Path) -> None:
    """Source spans are byte offsets, not character offsets — multi-byte UTF-8 must be honored."""
    text = "→<5\n"  # U+2192 is 3 bytes in UTF-8 → 6 bytes total
    assert len(text.encode("utf-8")) == 6
    payload = {
        "schema_version": SCHEMA_VERSION,
        "root": {
            "kind": "scope",
            "id": "uni",
            "scope_kind": "guideline",
            "children": [
                {
                    "kind": "atom",
                    "predicate": "arrow",
                    "terms": [],
                    "source_span": {"start": 0, "end": 3, "doc_id": "uni"},
                },
            ],
        },
    }
    (tmp_path / "uni.recorded.json").write_text(json.dumps(payload), encoding="utf-8")
    adapter = RecordedAdapter(tmp_path)
    tree = translate_guideline(doc_id="uni", text=text, adapter=adapter)
    assert isinstance(tree.root, Scope)


# ---------------------------------------------------------------------------
# translate_path / discover_translations


def test_translate_path_uses_sibling_recorded_fixture() -> None:
    tree = translate_path(HYPOXEMIA_TXT)
    assert tree.schema_version == SCHEMA_VERSION


def test_translate_path_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(InvalidGuidelineError, match="not found"):
        translate_path(tmp_path / "nope.txt")


def test_translate_path_rejects_wrong_extension(tmp_path: Path) -> None:
    p = tmp_path / "x.md"
    p.write_text("not a guideline", encoding="utf-8")
    with pytest.raises(InvalidGuidelineError, match="unsupported guideline extension"):
        translate_path(p)


def test_discover_translations_walks_directory_sorted() -> None:
    out = list(discover_translations(GUIDELINES_DIR))
    assert [p.name for p, _ in out] == sorted(p.name for p, _ in out)
    assert {p.name for p, _ in out} == {
        "hypoxemia-trigger.txt",
        "contradictory-bound.txt",
    }


def test_discover_translations_skips_non_guideline_extensions() -> None:
    # *.recorded.json sidecars and README.md must be skipped by the walker.
    out = list(discover_translations(GUIDELINES_DIR))
    suffixes = {p.suffix for p, _ in out}
    assert suffixes == {".txt"}


def test_discover_translations_single_file_passthrough() -> None:
    out = list(discover_translations(HYPOXEMIA_TXT))
    assert len(out) == 1
    assert out[0][0] == HYPOXEMIA_TXT


def test_discover_translations_rejects_bad_path(tmp_path: Path) -> None:
    nonexistent = tmp_path / "no-such-thing"
    with pytest.raises(InvalidGuidelineError, match="neither a file nor a directory"):
        list(discover_translations(nonexistent))


# ---------------------------------------------------------------------------
# emit_smt


def test_emit_smt_preamble_and_assumptions() -> None:
    tree = translate_path(HYPOXEMIA_TXT)
    matrix = emit_smt(tree)
    assert matrix.logic == DEFAULT_LOGIC
    assert matrix.theories == ["LRA"]
    assert matrix.preamble == "(set-logic QF_LRA)\n(declare-fun spo2 () Real)\n"
    assert len(matrix.assumptions) == 2
    labels = [a.label for a in matrix.assumptions]
    assert labels == ["clause_000", "clause_001"]
    assert matrix.assumptions[0].formula == "(< spo2 100.0)"
    assert matrix.assumptions[1].formula == "(> spo2 60.0)"


def test_emit_smt_provenance_threads_back_to_first_atom_span() -> None:
    tree = translate_path(HYPOXEMIA_TXT)
    matrix = emit_smt(tree)
    # Each clause's provenance must point at the FIRST atom encountered
    # in left-to-right walk so MUC reverse-mapping is mechanical.
    assert matrix.assumptions[0].provenance == "atom:hypoxemia-trigger:0-4"
    assert matrix.assumptions[1].provenance == "atom:hypoxemia-trigger:16-20"


def test_emit_smt_lowers_indicator_constraint() -> None:
    tree = OnionLIRTree(
        schema_version=SCHEMA_VERSION,
        root=Scope(
            id="ic",
            scope_kind="guideline",
            children=[
                IndicatorConstraint(
                    guard=Atom(
                        predicate="alarm",
                        terms=[],
                        source_span=SourceSpan(start=0, end=1, doc_id="ic"),
                    ),
                    body=Relation(
                        op="less_than",
                        args=[
                            Atom(
                                predicate="hr",
                                terms=[],
                                source_span=SourceSpan(start=0, end=1, doc_id="ic"),
                            ),
                            Atom(
                                predicate="literal",
                                terms=[Constant(value="180.0")],
                                source_span=SourceSpan(start=0, end=1, doc_id="ic"),
                            ),
                        ],
                    ),
                ),
            ],
        ),
    )
    matrix = emit_smt(tree)
    assert matrix.assumptions[0].formula == "(=> alarm (< hr 180.0))"


def test_emit_smt_elides_single_variable_term() -> None:
    """Patient-scoped Variable-only atoms lower to bare 0-ary symbols (golden parity)."""
    tree = OnionLIRTree(
        schema_version=SCHEMA_VERSION,
        root=Scope(
            id="ev",
            scope_kind="guideline",
            children=[
                Relation(
                    op="greater_than",
                    args=[
                        Atom(
                            predicate="hba1c",
                            terms=[Variable(name="P")],
                            source_span=SourceSpan(start=0, end=1, doc_id="ev"),
                        ),
                        Atom(
                            predicate="literal",
                            terms=[Constant(value="7.0")],
                            source_span=SourceSpan(start=0, end=1, doc_id="ev"),
                        ),
                    ],
                ),
            ],
        ),
    )
    matrix = emit_smt(tree)
    assert matrix.assumptions[0].formula == "(> hba1c 7.0)"
    assert "(declare-fun hba1c () Real)" in matrix.preamble


def test_emit_smt_rejects_unknown_op() -> None:
    tree = OnionLIRTree(
        schema_version=SCHEMA_VERSION,
        root=Scope(
            id="bad",
            scope_kind="guideline",
            children=[
                Relation(
                    op="modulo",
                    args=[
                        Atom(
                            predicate="x",
                            terms=[],
                            source_span=SourceSpan(start=0, end=1, doc_id="bad"),
                        ),
                    ],
                ),
            ],
        ),
    )
    with pytest.raises(UnsupportedOpError, match="modulo"):
        emit_smt(tree)


def test_emit_smt_rejects_richer_atoms() -> None:
    tree = OnionLIRTree(
        schema_version=SCHEMA_VERSION,
        root=Scope(
            id="rich",
            scope_kind="guideline",
            children=[
                Atom(
                    predicate="has_diagnosis",
                    terms=[Variable(name="P"), Constant(value="diabetes")],
                    source_span=SourceSpan(start=0, end=1, doc_id="rich"),
                ),
            ],
        ),
    )
    with pytest.raises(UnsupportedNodeError):
        emit_smt(tree)


def test_emit_smt_rejects_zero_arg_relation() -> None:
    tree = OnionLIRTree(
        schema_version=SCHEMA_VERSION,
        root=Scope(
            id="z",
            scope_kind="guideline",
            children=[Relation(op="and", args=[])],
        ),
    )
    with pytest.raises(UnsupportedNodeError):
        emit_smt(tree)


def test_op_map_covers_phase0_operators() -> None:
    # Tripwire: Phase 0 emitter contract pins these specific keys.
    expected = {
        "and",
        "or",
        "not",
        "implies",
        "equals",
        "less_than",
        "less_or_equal",
        "greater_than",
        "greater_or_equal",
        "plus",
        "minus",
        "times",
        "divide",
    }
    assert set(OP_MAP) == expected


# ---------------------------------------------------------------------------
# serialize / smt_sanity_check (the Task 4 gate)


def test_serialize_emits_check_sat_by_default() -> None:
    tree = translate_path(HYPOXEMIA_TXT)
    matrix = emit_smt(tree)
    script = serialize(matrix)
    assert script.endswith("(check-sat)\n")
    assert "(assert (< spo2 100.0))" in script
    assert "(assert (> spo2 60.0))" in script


def test_serialize_can_omit_check_sat() -> None:
    tree = translate_path(HYPOXEMIA_TXT)
    matrix = emit_smt(tree)
    script = serialize(matrix, include_check_sat=False)
    assert "(check-sat)" not in script


def test_smt_sanity_check_consistent_guideline_is_sat() -> None:
    tree = translate_path(HYPOXEMIA_TXT)
    matrix = emit_smt(tree)
    assert smt_sanity_check(matrix) == "sat"


def test_smt_sanity_check_contradictory_guideline_is_unsat() -> None:
    tree = translate_path(CONTRADICTORY_TXT)
    matrix = emit_smt(tree)
    assert smt_sanity_check(matrix) == "unsat"


def test_smt_sanity_check_disabled_assumption_is_dropped() -> None:
    tree = translate_path(CONTRADICTORY_TXT)
    matrix = emit_smt(tree)
    # Disable one of the conflicting bounds; the remaining clause is sat.
    relaxed = matrix.model_copy(
        update={
            "assumptions": [
                matrix.assumptions[0].model_copy(update={"enabled": False}),
                matrix.assumptions[1],
            ]
        }
    )
    assert smt_sanity_check(relaxed) == "sat"


# ---------------------------------------------------------------------------
# CLI


def test_cli_parser_defaults() -> None:
    parser = build_parser()
    args = parser.parse_args(["data/guidelines"])
    assert args.path == Path("data/guidelines")
    assert args.smt_check is False
    assert args.logic == DEFAULT_LOGIC


def test_cli_happy_path_writes_records(tmp_path: Path) -> None:
    out = tmp_path / "out.json"
    code = run(
        [
            str(GUIDELINES_DIR),
            "--output",
            str(out),
            "--smt-check",
        ]
    )
    assert code == 0
    records = json.loads(out.read_text(encoding="utf-8"))
    assert {r["doc_id"] for r in records} == {
        "hypoxemia-trigger",
        "contradictory-bound",
    }
    by_doc = {r["doc_id"]: r for r in records}
    assert by_doc["hypoxemia-trigger"]["smt_check"] == "sat"
    assert by_doc["contradictory-bound"]["smt_check"] == "unsat"
    # Tree + matrix round-trip through their schemas.
    OnionLIRTree.model_validate(by_doc["hypoxemia-trigger"]["tree"])


def test_cli_missing_path_exits_2(tmp_path: Path) -> None:
    err = io.StringIO()
    with redirect_stderr(err):
        code = run([str(tmp_path / "nope")])
    assert code == 2
    assert "path not found" in err.getvalue()


def test_cli_translate_error_exits_1(tmp_path: Path) -> None:
    # A *.txt file with no sidecar triggers MissingFixtureError → exit 1.
    p = tmp_path / "loose.txt"
    p.write_text("nothing\n", encoding="utf-8")
    err = io.StringIO()
    with redirect_stderr(err), redirect_stdout(io.StringIO()):
        code = run([str(p)])
    assert code == 1
    assert "translation failed" in err.getvalue()


def test_emit_smt_ignores_simple_tree_helper() -> None:
    # Sanity that the in-test helper produces a valid emitter input.
    tree = _build_simple_tree()
    matrix = emit_smt(tree)
    assert matrix.assumptions[0].formula == "(< spo2 100.0)"
