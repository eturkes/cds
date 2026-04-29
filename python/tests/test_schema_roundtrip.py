"""Cross-language wire-format integration tests (Task 2).

Loads the golden JSON fixtures shared with the Rust kernel
(``tests/golden/*.json``), parses them with the Pydantic v2 models, and
confirms a re-serialization round-trips back to a value-equal model. The
Rust integration test ``crates/kernel/tests/golden_roundtrip.rs`` parses
the same files via serde — if both pass, the wire format is bit-stable
across Rust ↔ Python.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from cds_harness.schema import (
    SCHEMA_VERSION,
    Atom,
    ClinicalTelemetryPayload,
    FormalVerificationTrace,
    OnionLIRTree,
    Scope,
    SmtConstraintMatrix,
)


def _project_root() -> Path:
    """Return the repository root by walking up from this test file."""
    here = Path(__file__).resolve()
    for ancestor in (here, *here.parents):
        if (ancestor / "Cargo.toml").is_file():
            return ancestor
    raise RuntimeError("could not locate project root (no Cargo.toml ancestor)")


GOLDEN_DIR = _project_root() / "tests" / "golden"


def _load_golden(name: str) -> dict:
    path = GOLDEN_DIR / name
    return json.loads(path.read_text(encoding="utf-8"))


def test_schema_version_matches_rust() -> None:
    # The Rust kernel must publish the same constant.
    assert SCHEMA_VERSION == "0.1.0"


def test_clinical_telemetry_payload_roundtrips() -> None:
    raw = _load_golden("clinical_telemetry_payload.json")
    parsed = ClinicalTelemetryPayload.model_validate(raw)

    reserialized = json.loads(parsed.model_dump_json())
    reparsed = ClinicalTelemetryPayload.model_validate(reserialized)
    assert parsed == reparsed

    assert parsed.schema_version == "0.1.0"
    assert parsed.source.device_id == "icu-monitor-01"
    assert parsed.source.patient_pseudo_id == "pseudo-abc123"
    assert len(parsed.samples) == 1
    sample = parsed.samples[0]
    assert sample.monotonic_ns == 1_234_567_890_123
    assert sample.vitals["heart_rate_bpm"] == pytest.approx(72.5)
    assert len(sample.events) == 1
    assert sample.events[0].name == "manual_bp_cuff_inflate"


def test_clinical_telemetry_rejects_negative_monotonic_ns() -> None:
    bad = _load_golden("clinical_telemetry_payload.json")
    bad["samples"][0]["monotonic_ns"] = -1
    with pytest.raises(ValidationError):
        ClinicalTelemetryPayload.model_validate(bad)


def test_onionl_ir_tree_roundtrips() -> None:
    raw = _load_golden("onionl_ir_tree.json")
    parsed = OnionLIRTree.model_validate(raw)

    reserialized = json.loads(parsed.model_dump_json())
    reparsed = OnionLIRTree.model_validate(reserialized)
    assert parsed == reparsed

    assert parsed.schema_version == "0.1.0"
    assert isinstance(parsed.root, Scope)
    assert parsed.root.scope_kind == "guideline"
    assert len(parsed.root.children) == 1


def test_onionl_atom_requires_source_span() -> None:
    """Constraint C4: every Atom MUST carry a SourceSpan."""
    with pytest.raises(ValidationError):
        Atom.model_validate({"kind": "atom", "predicate": "p", "terms": []})


def test_onionl_discriminator_is_kind() -> None:
    raw = _load_golden("onionl_ir_tree.json")
    parsed = OnionLIRTree.model_validate(raw)
    serialized = parsed.model_dump_json()
    for tag in ("scope", "indicator_constraint", "atom", "relation"):
        assert f'"kind":"{tag}"' in serialized, f"discriminator kind={tag} missing"


def test_smt_constraint_matrix_roundtrips() -> None:
    raw = _load_golden("smt_constraint_matrix.json")
    parsed = SmtConstraintMatrix.model_validate(raw)

    reserialized = json.loads(parsed.model_dump_json())
    reparsed = SmtConstraintMatrix.model_validate(reserialized)
    assert parsed == reparsed

    assert parsed.logic == "QF_LRA"
    assert parsed.theories == ["LRA"]
    assert len(parsed.assumptions) == 2
    assert parsed.assumptions[0].provenance == "atom:guideline-001:31-60"
    assert parsed.assumptions[1].provenance is None


def test_formal_verification_trace_roundtrips() -> None:
    raw = _load_golden("formal_verification_trace.json")
    parsed = FormalVerificationTrace.model_validate(raw)

    reserialized = json.loads(parsed.model_dump_json())
    reparsed = FormalVerificationTrace.model_validate(reserialized)
    assert parsed == reparsed

    assert parsed.sat is False
    assert len(parsed.muc) == 2
    assert parsed.alethe_proof is not None


def test_formal_verification_sat_carries_no_proof() -> None:
    sat_trace = FormalVerificationTrace(schema_version="0.1.0", sat=True, muc=[], alethe_proof=None)
    assert sat_trace.alethe_proof is None
    assert sat_trace.muc == []
    # Round-trips even with the optional field absent.
    rehydrated = FormalVerificationTrace.model_validate_json(sat_trace.model_dump_json())
    assert rehydrated == sat_trace
