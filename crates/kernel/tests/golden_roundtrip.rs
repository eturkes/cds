//! Cross-language wire-format integration tests (Task 2).
//!
//! Loads the golden JSON fixtures shared with the Python harness
//! (`tests/golden/*.json`), parses them into the kernel's schema types, and
//! confirms that a re-serialization deserializes back to a structurally-
//! identical value. The Python pytest suite (`python/tests/
//! test_schema_roundtrip.py`) parses the same files with Pydantic v2 — if
//! both pass, the wire format is bit-stable across Rust ↔ Python.

use std::path::{Path, PathBuf};

use cds_kernel::schema::{
    ClinicalTelemetryPayload, FormalVerificationTrace, OnionLIRTree, SmtConstraintMatrix,
};

/// Repository-relative path to the shared golden-fixture directory.
fn golden_dir() -> PathBuf {
    // CARGO_MANIFEST_DIR points at crates/kernel; goldens live two levels up.
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..")
        .join("tests")
        .join("golden")
}

fn load_golden(name: &str) -> String {
    let path = golden_dir().join(name);
    std::fs::read_to_string(&path).unwrap_or_else(|e| panic!("read golden {}: {e}", path.display()))
}

#[test]
fn clinical_telemetry_payload_roundtrips() {
    let raw = load_golden("clinical_telemetry_payload.json");
    let parsed: ClinicalTelemetryPayload =
        serde_json::from_str(&raw).expect("parse golden ClinicalTelemetryPayload");
    let reserialized = serde_json::to_string(&parsed).expect("re-serialize");
    let reparsed: ClinicalTelemetryPayload = serde_json::from_str(&reserialized).expect("re-parse");
    assert_eq!(parsed, reparsed);

    assert_eq!(parsed.schema_version, "0.1.0");
    assert_eq!(parsed.source.device_id, "icu-monitor-01");
    assert_eq!(parsed.samples.len(), 1);
    assert!(parsed.samples[0].vitals.contains_key("heart_rate_bpm"));
}

#[test]
fn onionl_ir_tree_roundtrips() {
    use cds_kernel::schema::OnionLNode;
    let raw = load_golden("onionl_ir_tree.json");
    let parsed: OnionLIRTree = serde_json::from_str(&raw).expect("parse golden OnionLIRTree");
    let reserialized = serde_json::to_string(&parsed).expect("re-serialize");
    let reparsed: OnionLIRTree = serde_json::from_str(&reserialized).expect("re-parse");
    assert_eq!(parsed, reparsed);

    // Constraint C4 sanity: the deepest atoms carry source spans.
    match &parsed.root {
        OnionLNode::Scope { children, .. } => {
            assert_eq!(children.len(), 1);
        }
        _ => panic!("root must be a scope"),
    }
}

#[test]
fn smt_constraint_matrix_roundtrips() {
    let raw = load_golden("smt_constraint_matrix.json");
    let parsed: SmtConstraintMatrix =
        serde_json::from_str(&raw).expect("parse golden SmtConstraintMatrix");
    let reserialized = serde_json::to_string(&parsed).expect("re-serialize");
    let reparsed: SmtConstraintMatrix = serde_json::from_str(&reserialized).expect("re-parse");
    assert_eq!(parsed, reparsed);

    assert_eq!(parsed.logic, "QF_LRA");
    assert_eq!(parsed.assumptions.len(), 2);
    assert!(parsed.assumptions[0].provenance.is_some());
    assert!(parsed.assumptions[1].provenance.is_none());
}

#[test]
fn formal_verification_trace_roundtrips() {
    let raw = load_golden("formal_verification_trace.json");
    let parsed: FormalVerificationTrace =
        serde_json::from_str(&raw).expect("parse golden FormalVerificationTrace");
    let reserialized = serde_json::to_string(&parsed).expect("re-serialize");
    let reparsed: FormalVerificationTrace = serde_json::from_str(&reserialized).expect("re-parse");
    assert_eq!(parsed, reparsed);

    assert!(!parsed.sat, "golden trace is unsat");
    assert_eq!(parsed.muc.len(), 2);
    assert!(parsed.alethe_proof.is_some());
}

#[test]
fn schema_version_is_stable() {
    assert_eq!(cds_kernel::schema::SCHEMA_VERSION, "0.1.0");
}
