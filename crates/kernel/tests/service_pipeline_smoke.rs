//! Phase 0 kernel-service pipeline daprd smokes (Task 8.3b2b).
//!
//! Two cargo integration tests, each driving `cds-kernel-service` behind
//! a `dapr run -- <bin>` sidecar. Lifted into a separate file from
//! `tests/service_smoke.rs` per ADR-020 §3 (the foundation `/healthz` +
//! deduce smokes shipped in 8.3a / 8.3b2a stay co-located in
//! `service_smoke.rs`; this file owns the dependency-gated close-out).
//!
//! ## Suites
//!
//! 1. **`/v1/solve` smoke** — gated on `.bin/z3` + `.bin/cvc5`. POSTs the
//!    canonical contradictory matrix (the same shape used by
//!    `tests/solver_smoke.rs`; the `atom:contradictory-bound:*`
//!    provenance spans project through the `OnionL` fixture
//!    `data/guidelines/contradictory-bound.recorded.json` per ADR-020 §3
//!    bullet 1). Asserts `trace.sat == false`, `trace.muc` pulls both
//!    source-spans, and the Alethe proof references both clause labels
//!    in `(assume …)` steps.
//! 2. **`/v1/recheck` smoke** — gated on `.bin/z3` + `.bin/cvc5` AND
//!    `CDS_KIMINA_URL`. Chains the trace forward: first POSTs `/v1/solve`
//!    against the same sidecar to obtain the contradictory trace, then
//!    POSTs `/v1/recheck` with that trace plus the operator-supplied
//!    Kimina URL. Asserts `recheck.ok == true` plus the four Phase 0
//!    probes (`starts_paren`, `has_assume`, `has_rule`, `byte_len > 0`)
//!    — same probe set as `tests/lean_smoke.rs`.
//!
//! Per ADR-020 §3 bullet 3, both smokes set per-request `options.z3_path`
//! / `options.cvc5_path` to the absolute `.bin/z3` / `.bin/cvc5` paths so
//! daprd's `$PATH` does not leak into the gate; this also serves as
//! on-the-wire validation of 8.3b2a's per-request override semantics
//! (ADR-020 §5). Tests run with `--test-threads=1` (Justfile recipe
//! `rs-service-pipeline-smoke`); the helper module `tests/common.rs`
//! (lifted in 8.3b2a) supplies the dapr-bring-up, readiness-probe, and
//! SIGTERM-then-kill teardown shared with `tests/service_smoke.rs`.

mod common;

use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

use cds_kernel::schema::{
    FormalVerificationTrace, LabelledAssertion, SCHEMA_VERSION, SmtConstraintMatrix,
};
use cds_kernel::service::{
    HEALTHZ_PATH,
    handlers::{RECHECK_PATH, SOLVE_PATH},
};
use serde_json::Value;

use crate::common::{
    DaprPorts, build_dapr_command, dapr_paths, repo_root, sigterm_then_kill, wait_until_ready,
};

/// `<repo>/.bin/<name>` if it exists, else `None`. Mirrors
/// `tests/solver_smoke.rs::bin` and `tests/lean_smoke.rs::bin` shape;
/// resolves through `tests/common::repo_root` so the two files stay in
/// step.
fn bin(name: &str) -> Option<PathBuf> {
    let p = repo_root().join(".bin").join(name);
    if p.exists() { Some(p) } else { None }
}

/// `CDS_KIMINA_URL`, with empty / whitespace-only values treated as
/// unset. Mirrors `tests/lean_smoke.rs::kimina_url`.
fn kimina_url() -> Option<String> {
    let raw = std::env::var("CDS_KIMINA_URL").ok()?;
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        None
    } else {
        Some(trimmed.to_string())
    }
}

/// Canonical contradictory matrix — `spo2 > 95.0 ∧ spo2 < 90.0`. The
/// labels mirror `tests/solver_smoke.rs::contradictory_matrix` and
/// `tests/lean_smoke.rs::contradictory_matrix`; the `atom:contradictory-
/// bound:*` provenance spans project through the `OnionL` fixture at
/// `data/guidelines/contradictory-bound.recorded.json`.
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

/// Decode the solve response and assert the verdict shape this gate pins:
/// `sat = false`, MUC projects through provenance to both
/// `atom:contradictory-bound:*` spans, and the Alethe proof references
/// both clause labels in `(assume …)` steps. Returns the decoded trace
/// so the recheck smoke can chain it forward.
fn assert_expected_solve_trace(body_bytes: &[u8]) -> Result<FormalVerificationTrace, String> {
    let trace: FormalVerificationTrace = serde_json::from_slice(body_bytes).map_err(|e| {
        format!(
            "decode FormalVerificationTrace: {e}; body={}",
            String::from_utf8_lossy(body_bytes)
        )
    })?;
    if trace.sat {
        return Err(format!(
            "contradictory matrix must be unsat; got trace={trace:?}"
        ));
    }
    let expected_muc = vec![
        "atom:contradictory-bound:0-4".to_string(),
        "atom:contradictory-bound:15-19".to_string(),
    ];
    if trace.muc != expected_muc {
        return Err(format!(
            "muc mismatch: got {:?} (expected {expected_muc:?})",
            trace.muc
        ));
    }
    let proof = trace
        .alethe_proof
        .as_deref()
        .ok_or_else(|| "alethe_proof missing on unsat trace".to_string())?;
    if !proof.starts_with('(') {
        return Err("Alethe proof must be an S-expression".to_string());
    }
    if !(proof.contains("(assume clause_000") && proof.contains("(assume clause_001")) {
        return Err(format!(
            "proof must reference both clause labels via (assume …); head={}",
            proof.lines().take(5).collect::<Vec<_>>().join(" | ")
        ));
    }
    Ok(trace)
}

/// Decode the recheck response (wire shape:
/// [`cds_kernel::service::handlers::LeanRecheckWire`]) and pin the four
/// Phase 0 probes plus `ok` + custom-id round-trip.
fn assert_expected_recheck_outcome(body_bytes: &[u8], custom_id: &str) -> Result<(), String> {
    let recheck: Value = serde_json::from_slice(body_bytes).map_err(|e| {
        format!(
            "decode LeanRecheckWire: {e}; body={}",
            String::from_utf8_lossy(body_bytes)
        )
    })?;
    if recheck["ok"] != Value::Bool(true) {
        return Err(format!("recheck.ok != true; body={recheck}"));
    }
    if recheck["custom_id"] != Value::String(custom_id.to_string()) {
        return Err(format!(
            "custom_id round-trip failed: got {} (expected {custom_id:?})",
            recheck["custom_id"]
        ));
    }
    let probes = &recheck["probes"];
    for (name, want) in [
        ("starts_paren", "true"),
        ("has_assume", "true"),
        ("has_rule", "true"),
    ] {
        if probes[name] != Value::String(want.to_string()) {
            return Err(format!(
                "phase 0 probe `{name}` mismatch: got {} (expected {want:?}); probes={probes}",
                probes[name]
            ));
        }
    }
    let byte_len_raw = probes["byte_len"]
        .as_str()
        .ok_or_else(|| format!("byte_len probe missing or non-string: probes={probes}"))?;
    let byte_len: u64 = byte_len_raw
        .parse()
        .map_err(|e| format!("byte_len probe `{byte_len_raw}` not numeric: {e}"))?;
    if byte_len == 0 {
        return Err(format!("byte_len probe was zero: probes={probes}"));
    }
    Ok(())
}

/// Drive both Dapr readiness gates against `ports` until `deadline` —
/// `/healthz` on the app port (200), then `/v1.0/healthz/outbound` on
/// the sidecar HTTP port (200 / 204). Mirrors the readiness shape used
/// by every kernel-side daprd smoke.
async fn await_dapr_ready(
    client: &reqwest::Client,
    ports: &DaprPorts,
    deadline: Instant,
) -> Result<(), String> {
    wait_until_ready(
        client,
        &format!("http://127.0.0.1:{}{HEALTHZ_PATH}", ports.app),
        &[200],
        deadline,
    )
    .await
    .map_err(|e| format!("app readiness: {e}"))?;
    wait_until_ready(
        client,
        &format!("http://127.0.0.1:{}/v1.0/healthz/outbound", ports.http),
        &[200, 204],
        deadline,
    )
    .await
    .map_err(|e| format!("sidecar readiness: {e}"))?;
    Ok(())
}

/// POST the contradictory matrix through the sidecar's `/v1/solve`
/// invocation route, decode the response, and pin the unsat verdict.
/// Returns the decoded trace so the recheck smoke can chain it forward.
async fn invoke_solve_smoke(
    client: &reqwest::Client,
    ports: &DaprPorts,
    smoke_app_id: &str,
    z3: &Path,
    cvc5: &Path,
) -> Result<FormalVerificationTrace, String> {
    let invoke_url = format!(
        "http://127.0.0.1:{}/v1.0/invoke/{smoke_app_id}/method{SOLVE_PATH}",
        ports.http
    );
    let body = serde_json::json!({
        "matrix": contradictory_matrix(),
        "options": {
            "timeout_ms": 10_000u64,
            "z3_path": z3.to_str().expect(".bin/z3 path is valid UTF-8"),
            "cvc5_path": cvc5.to_str().expect(".bin/cvc5 path is valid UTF-8"),
        },
    });
    let resp = client
        .post(&invoke_url)
        .json(&body)
        .send()
        .await
        .map_err(|e| format!("solve invoke: {e}"))?;
    let status = resp.status();
    let bytes = resp.bytes().await.map_err(|e| format!("solve read: {e}"))?;
    if status != reqwest::StatusCode::OK {
        return Err(format!(
            "solve status: {status}; body={}",
            String::from_utf8_lossy(&bytes)
        ));
    }
    assert_expected_solve_trace(&bytes)
}

/// POST the prior-stage trace through the sidecar's `/v1/recheck`
/// invocation route and assert the outcome matches the Phase 0 contract.
async fn invoke_recheck_smoke(
    client: &reqwest::Client,
    ports: &DaprPorts,
    smoke_app_id: &str,
    trace: &FormalVerificationTrace,
    kimina_url: &str,
    custom_id: &str,
) -> Result<(), String> {
    let invoke_url = format!(
        "http://127.0.0.1:{}/v1.0/invoke/{smoke_app_id}/method{RECHECK_PATH}",
        ports.http
    );
    let body = serde_json::json!({
        "trace": trace,
        "options": {
            "kimina_url": kimina_url,
            "timeout_ms": 120_000u64,
            "custom_id": custom_id,
        },
    });
    let resp = client
        .post(&invoke_url)
        .json(&body)
        .send()
        .await
        .map_err(|e| format!("recheck invoke: {e}"))?;
    let status = resp.status();
    let bytes = resp
        .bytes()
        .await
        .map_err(|e| format!("recheck read: {e}"))?;
    if status != reqwest::StatusCode::OK {
        return Err(format!(
            "recheck status: {status}; body={}",
            String::from_utf8_lossy(&bytes)
        ));
    }
    assert_expected_recheck_outcome(&bytes, custom_id)
}

#[tokio::test]
async fn dapr_sidecar_drives_solve_through_service_invocation() {
    let service_bin = env!("CARGO_BIN_EXE_cds-kernel-service");

    let (cli, daprd, install, resources, config) = dapr_paths();
    if !cli.is_file() || !daprd.is_file() {
        eprintln!(
            "==> SKIP: dapr CLI / slim runtime not staged (run `just fetch-dapr`); skipping kernel sidecar solve smoke"
        );
        return;
    }
    if !resources.is_dir() || !config.is_file() {
        eprintln!(
            "==> SKIP: dapr/components or dapr/config.yaml missing; skipping kernel sidecar solve smoke"
        );
        return;
    }
    let (Some(z3), Some(cvc5)) = (bin("z3"), bin("cvc5")) else {
        eprintln!(
            "==> SKIP: .bin/z3 and/or .bin/cvc5 missing — run `just fetch-bins` to provision; skipping kernel sidecar solve smoke"
        );
        return;
    };

    let ports = DaprPorts::allocate();
    let smoke_app_id = "cds-kernel-solve-smoke";

    let mut cmd = build_dapr_command(
        &cli,
        smoke_app_id,
        &ports,
        &install,
        &resources,
        &config,
        service_bin,
    );
    let mut child = cmd
        .spawn()
        .expect("dapr run --app-id cds-kernel-solve-smoke");

    // Solver wall-clock is 10 s; allow a generous HTTP budget so the
    // gate does not flake on a cold child spawn.
    let result = async {
        let client = reqwest::Client::builder()
            .timeout(Duration::from_secs(30))
            .build()
            .expect("reqwest client");
        let deadline = Instant::now() + Duration::from_secs(25);
        await_dapr_ready(&client, &ports, deadline).await?;
        invoke_solve_smoke(&client, &ports, smoke_app_id, &z3, &cvc5).await?;
        Ok::<(), String>(())
    }
    .await;

    sigterm_then_kill(&mut child, Duration::from_secs(5)).await;

    if let Err(err) = result {
        panic!("kernel sidecar solve smoke failed: {err}");
    }
}

#[tokio::test]
async fn dapr_sidecar_drives_recheck_through_service_invocation() {
    let service_bin = env!("CARGO_BIN_EXE_cds-kernel-service");

    let (cli, daprd, install, resources, config) = dapr_paths();
    if !cli.is_file() || !daprd.is_file() {
        eprintln!(
            "==> SKIP: dapr CLI / slim runtime not staged (run `just fetch-dapr`); skipping kernel sidecar recheck smoke"
        );
        return;
    }
    if !resources.is_dir() || !config.is_file() {
        eprintln!(
            "==> SKIP: dapr/components or dapr/config.yaml missing; skipping kernel sidecar recheck smoke"
        );
        return;
    }
    let (Some(z3), Some(cvc5)) = (bin("z3"), bin("cvc5")) else {
        eprintln!(
            "==> SKIP: .bin/z3 and/or .bin/cvc5 missing — run `just fetch-bins` to provision; skipping kernel sidecar recheck smoke"
        );
        return;
    };
    let Some(url) = kimina_url() else {
        eprintln!(
            "==> SKIP: CDS_KIMINA_URL unset — start Kimina (`python -m server` from the project-numina/kimina-lean-server checkout) and re-run with that URL exported; skipping kernel sidecar recheck smoke"
        );
        return;
    };

    let ports = DaprPorts::allocate();
    let smoke_app_id = "cds-kernel-recheck-smoke";
    let custom_id = "cds-recheck-smoke";

    let mut cmd = build_dapr_command(
        &cli,
        smoke_app_id,
        &ports,
        &install,
        &resources,
        &config,
        service_bin,
    );
    let mut child = cmd
        .spawn()
        .expect("dapr run --app-id cds-kernel-recheck-smoke");

    // Lean re-check budget mirrors `tests/lean_smoke.rs` (120 s),
    // wrapped in a generous HTTP timeout so the warden-driven solve
    // call + Kimina round-trip both fit.
    let result = async {
        let client = reqwest::Client::builder()
            .timeout(Duration::from_secs(180))
            .build()
            .expect("reqwest client");
        let deadline = Instant::now() + Duration::from_secs(25);
        await_dapr_ready(&client, &ports, deadline).await?;
        let trace = invoke_solve_smoke(&client, &ports, smoke_app_id, &z3, &cvc5).await?;
        invoke_recheck_smoke(&client, &ports, smoke_app_id, &trace, &url, custom_id).await?;
        Ok::<(), String>(())
    }
    .await;

    sigterm_then_kill(&mut child, Duration::from_secs(5)).await;

    if let Err(err) = result {
        panic!("kernel sidecar recheck smoke failed: {err}");
    }
}
