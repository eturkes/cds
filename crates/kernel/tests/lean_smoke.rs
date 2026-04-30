//! Lean / Kimina re-check integration smoke (Task 7).
//!
//! Drives the full Phase 0 pipeline through the Lean 4 boundary:
//!
//! 1. The Phase-0 contradictory matrix is verified by Z3 + cvc5
//!    (Task 6) to produce a `FormalVerificationTrace` carrying the
//!    Alethe proof S-expression.
//! 2. That trace is re-checked through Kimina via [`cds_kernel::lean::recheck`].
//!    The Phase 0 re-check is structural (snippet + four `PROBE`
//!    `#eval` lines) — see `crates/kernel/src/lean/mod.rs` for the
//!    Phase 0 vs. Phase 1 (foundational) scope split.
//!
//! The test is **opt-in**: it runs only when `CDS_KIMINA_URL` is set
//! and the host is reachable on TCP. With no Kimina daemon available,
//! the test prints a skip notice and returns `Ok(())`.
//!
//! To run end-to-end on a dev box:
//!
//! ```text
//! # In one shell — start Kimina (clone https://github.com/project-numina/kimina-lean-server):
//! python -m server   # binds 0.0.0.0:8000 by default.
//!
//! # In another:
//! CDS_KIMINA_URL=http://127.0.0.1:8000 just rs-lean
//! ```

use std::path::PathBuf;
use std::time::Duration;

use cds_kernel::lean::{self, LeanOptions};
use cds_kernel::schema::{LabelledAssertion, SCHEMA_VERSION, SmtConstraintMatrix};
use cds_kernel::solver::{self, VerifyOptions};

fn workspace_root() -> PathBuf {
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

fn solver_opts() -> Option<VerifyOptions> {
    Some(VerifyOptions {
        timeout: Duration::from_secs(10),
        z3_path: bin("z3")?,
        cvc5_path: bin("cvc5")?,
    })
}

fn kimina_url() -> Option<String> {
    let url = std::env::var("CDS_KIMINA_URL").ok()?;
    let trimmed = url.trim();
    if trimmed.is_empty() {
        None
    } else {
        Some(trimmed.to_string())
    }
}

fn contradictory_matrix() -> SmtConstraintMatrix {
    SmtConstraintMatrix {
        schema_version: SCHEMA_VERSION.to_string(),
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
async fn alethe_proof_round_trips_through_kimina() {
    let Some(url) = kimina_url() else {
        eprintln!(
            "[lean_smoke] CDS_KIMINA_URL unset — skipping (start Kimina and set the env var \
             to exercise this gate)."
        );
        return;
    };
    let Some(opts) = solver_opts() else {
        eprintln!("[lean_smoke] .bin/z3 / .bin/cvc5 missing — run `just fetch-bins`; skipping.");
        return;
    };

    let trace = solver::verify(&contradictory_matrix(), &opts)
        .await
        .expect("solver::verify must succeed against the canonical contradiction");
    assert!(!trace.sat, "fixture must be unsat");
    let proof_len = trace
        .alethe_proof
        .as_deref()
        .map(str::len)
        .expect("cvc5 must emit a non-empty proof");
    assert!(proof_len > 0);

    let recheck = lean::recheck(
        &trace,
        &LeanOptions {
            kimina_url: url,
            timeout: Duration::from_secs(120),
            custom_id: "cds-lean-smoke".to_string(),
            ..LeanOptions::default()
        },
    )
    .await
    .expect("kimina recheck must succeed");

    assert!(
        recheck.ok,
        "lean recheck must pass; messages={:?}, probes={:?}",
        recheck.messages, recheck.probes
    );
    assert_eq!(recheck.custom_id, "cds-lean-smoke");
    assert_eq!(
        recheck.probes.get("starts_paren").map(String::as_str),
        Some("true")
    );
    assert_eq!(
        recheck.probes.get("has_assume").map(String::as_str),
        Some("true")
    );
    assert_eq!(
        recheck.probes.get("has_rule").map(String::as_str),
        Some("true")
    );
    let byte_len: u64 = recheck
        .probes
        .get("byte_len")
        .expect("byte_len probe present")
        .parse()
        .expect("byte_len probe is numeric");
    assert!(byte_len > 0, "lean saw a non-empty proof string");
}
