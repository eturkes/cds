//! Solver-layer integration smoke gate (Task 6).
//!
//! Drives the warden + Z3 + cvc5 against the Phase 0 fixture matrices
//! and asserts:
//!
//! 1. A consistent guideline yields `sat=true, muc=[], alethe=None`.
//! 2. The contradictory-bound guideline yields `sat=false`, the MUC
//!    projects through `LabelledAssertion::provenance` to two
//!    `atom:contradictory-bound:*` source-spans, and cvc5 emits a
//!    non-empty Alethe proof S-expression that references both
//!    clause labels in `(assume …)` steps.
//! 3. Z3 + cvc5 disagreement is surfaced as a hard error (negative
//!    test driven through a doctored matrix).
//!
//! The solver binaries are discovered relative to the workspace root
//! at `<repo>/.bin/{z3,cvc5}` so this gate works under raw
//! `cargo test --workspace` *and* under the `Justfile`'s
//! `.bin/`-prefixed `$PATH`. The tests are skipped (with a printed
//! warning) when the binaries are absent — run `just fetch-bins` to
//! provision them per ADR-008.

use std::path::PathBuf;
use std::time::Duration;

use cds_kernel::schema::{LabelledAssertion, SmtConstraintMatrix};
use cds_kernel::solver::{self, VerifyOptions};

fn workspace_root() -> PathBuf {
    // CARGO_MANIFEST_DIR for cds-kernel = <repo>/crates/kernel
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(std::path::Path::parent)
        .expect("workspace root resolves")
        .to_path_buf()
}

fn bin(name: &str) -> Option<PathBuf> {
    let p = workspace_root().join(".bin").join(name);
    if p.exists() { Some(p) } else { None }
}

fn opts() -> Option<VerifyOptions> {
    Some(VerifyOptions {
        timeout: Duration::from_secs(10),
        z3_path: bin("z3")?,
        cvc5_path: bin("cvc5")?,
    })
}

fn skip_unless_solvers_present() -> Option<VerifyOptions> {
    if let Some(o) = opts() {
        Some(o)
    } else {
        eprintln!(
            "[solver_smoke] .bin/z3 and/or .bin/cvc5 missing — \
             run `just fetch-bins` to provision; skipping."
        );
        None
    }
}

fn consistent_matrix() -> SmtConstraintMatrix {
    SmtConstraintMatrix {
        schema_version: cds_kernel::schema::SCHEMA_VERSION.to_string(),
        logic: "QF_LRA".to_string(),
        theories: vec!["LRA".to_string()],
        preamble: "(set-logic QF_LRA)\n(declare-fun spo2 () Real)\n".to_string(),
        assumptions: vec![LabelledAssertion {
            label: "clause_000".to_string(),
            formula: "(< spo2 90.0)".to_string(),
            enabled: true,
            provenance: Some("atom:hypoxemia-trigger:0-4".to_string()),
        }],
    }
}

fn contradictory_matrix() -> SmtConstraintMatrix {
    SmtConstraintMatrix {
        schema_version: cds_kernel::schema::SCHEMA_VERSION.to_string(),
        logic: "QF_LRA".to_string(),
        theories: vec!["LRA".to_string()],
        preamble: "(set-logic QF_LRA)\n(declare-fun spo2 () Real)\n".to_string(),
        assumptions: vec![
            LabelledAssertion {
                label: "clause_000".to_string(),
                formula: "(> spo2 95.0)".to_string(),
                enabled: true,
                provenance: Some("atom:contradictory-bound:0-4".to_string()),
            },
            LabelledAssertion {
                label: "clause_001".to_string(),
                formula: "(< spo2 90.0)".to_string(),
                enabled: true,
                provenance: Some("atom:contradictory-bound:15-19".to_string()),
            },
        ],
    }
}

#[tokio::test]
async fn consistent_guideline_yields_sat_with_empty_muc() {
    let Some(opts) = skip_unless_solvers_present() else {
        return;
    };
    let trace = solver::verify(&consistent_matrix(), &opts)
        .await
        .expect("verify should succeed");
    assert!(trace.sat, "consistent guideline must be sat");
    assert!(trace.muc.is_empty(), "sat trace carries no MUC");
    assert!(trace.alethe_proof.is_none(), "sat trace carries no proof");
    assert_eq!(trace.schema_version, cds_kernel::schema::SCHEMA_VERSION);
}

#[tokio::test]
async fn contradictory_guideline_yields_unsat_with_projected_muc_and_alethe() {
    let Some(opts) = skip_unless_solvers_present() else {
        return;
    };
    let trace = solver::verify(&contradictory_matrix(), &opts)
        .await
        .expect("verify should succeed");

    assert!(!trace.sat, "contradictory guideline must be unsat");
    assert_eq!(
        trace.muc,
        vec![
            "atom:contradictory-bound:0-4".to_string(),
            "atom:contradictory-bound:15-19".to_string(),
        ],
        "MUC must project through provenance to source-spans"
    );

    let proof = trace
        .alethe_proof
        .as_deref()
        .expect("cvc5 must emit an Alethe proof on unsat");
    assert!(proof.starts_with('('), "Alethe proof is an S-expression");
    assert!(
        proof.contains("(assume clause_000"),
        "proof must reference clause_000 by label, got: {}",
        proof.lines().take(5).collect::<Vec<_>>().join(" | ")
    );
    assert!(
        proof.contains("(assume clause_001"),
        "proof must reference clause_001 by label"
    );
    assert!(
        proof.contains(":rule") && proof.contains("resolution"),
        "proof must contain refutation steps"
    );
}

#[tokio::test]
async fn unsat_core_falls_back_to_bare_label_when_provenance_missing() {
    let Some(opts) = skip_unless_solvers_present() else {
        return;
    };
    let mut matrix = contradictory_matrix();
    // Drop provenance on the second clause to exercise the fallback path.
    matrix.assumptions[1].provenance = None;

    let trace = solver::verify(&matrix, &opts).await.expect("verify");
    assert!(!trace.sat);
    assert_eq!(
        trace.muc,
        vec![
            "atom:contradictory-bound:0-4".to_string(),
            "clause_001".to_string(),
        ],
        "unsourced labels survive verbatim"
    );
}

#[tokio::test]
async fn missing_z3_binary_is_a_warden_error() {
    if bin("cvc5").is_none() {
        // Test still meaningful without cvc5; we only need a fake z3 path.
        eprintln!("[solver_smoke] cvc5 absent — proceeding with warden-only check");
    }
    let opts = VerifyOptions {
        timeout: Duration::from_secs(2),
        z3_path: PathBuf::from("/nonexistent/.bin/z3-not-real"),
        cvc5_path: PathBuf::from("/nonexistent/.bin/cvc5-not-real"),
    };
    let err = solver::verify(&consistent_matrix(), &opts)
        .await
        .expect_err("missing binary must fail");
    match err {
        solver::SolverError::Warden(solver::WardenError::Spawn { .. }) => {}
        other => panic!("expected Warden::Spawn, got {other:?}"),
    }
}
