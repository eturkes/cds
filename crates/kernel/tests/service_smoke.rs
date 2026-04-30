//! Integration smoke for the Phase 0 kernel service.
//!
//! Three suites:
//!
//! 1. **Standalone HTTP** (Task 8.3a) — bind the axum router on an
//!    ephemeral port, issue an actual TCP request to `/healthz`, decode
//!    the body, and assert the response shape pinning the kernel
//!    invariants.
//!
//! 2. **Gated Dapr healthz sidecar** (Task 8.3a) — when `.bin/dapr`
//!    and the slim `.bin/.dapr/.dapr/bin/daprd` are staged, spawn
//!    `dapr run -- <bin>` around the just-built `cds-kernel-service`,
//!    wait for the `/v1.0/healthz/outbound` readiness probe, then drive
//!    `/v1.0/invoke/cds-kernel-smoke/method/healthz` through the
//!    sidecar and assert the same invariants. Skipped (loud notice)
//!    when Dapr is not staged.
//!
//! 3. **Gated Dapr deduce sidecar** (Task 8.3b2a — new) — same
//!    sidecar shape as suite 2, but driving
//!    `/v1.0/invoke/cds-kernel-deduce-smoke/method/v1/deduce` with a
//!    synthetic `ClinicalTelemetryPayload` whose readings span the
//!    canonical-vital allowlist. The payload includes one out-of-band
//!    reading (`heart_rate_bpm = 30`, below the default
//!    `Phase0Thresholds.heart_rate_bpm.low = 50`) so the
//!    `breach_summary.bradycardia` list comes back populated. No
//!    external solver / Kimina dependency is exercised — the deduce
//!    pipeline is pure Rust + ascent (ADR-013); this is the
//!    dependency-free half of the 8.3b2 daprd close-out (ADR-020 §1).
//!
//! ADR-018 / ADR-020 document the contracts these smokes gate.

mod common;

use std::time::{Duration, Instant};

use cds_kernel::KERNEL_ID;
use cds_kernel::deduce::Verdict;
use cds_kernel::schema::SCHEMA_VERSION;
use cds_kernel::service::{
    HEALTHZ_PATH, KernelHealthz, KernelServiceState, SERVICE_APP_ID, build_router,
    handlers::DEDUCE_PATH,
};
use serde_json::{Value, json};

use crate::common::{
    DaprPorts, build_dapr_command, dapr_paths, sigterm_then_kill, wait_until_ready,
};

#[tokio::test]
async fn standalone_axum_serves_healthz() {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
        .await
        .expect("bind");
    let addr = listener.local_addr().expect("local_addr");
    let server = tokio::spawn(async move {
        let _ = axum::serve(listener, build_router(KernelServiceState::default())).await;
    });

    let client = reqwest::Client::new();
    let url = format!("http://{addr}{HEALTHZ_PATH}");
    let resp = client
        .get(&url)
        .timeout(Duration::from_secs(5))
        .send()
        .await
        .expect("send");
    assert_eq!(resp.status(), reqwest::StatusCode::OK);
    let body: KernelHealthz = resp.json().await.expect("decode body");
    assert_eq!(body, KernelHealthz::default());
    assert_eq!(body.kernel_id, KERNEL_ID);
    assert_eq!(body.schema_version, SCHEMA_VERSION);

    server.abort();
    // Ensure the abort completes before the test exits so the bound port
    // is released back to the OS deterministically.
    let _ = server.await;
}

#[tokio::test]
async fn dapr_sidecar_drives_healthz_through_service_invocation() {
    // Path to the just-built service binary, set by cargo at compile time.
    let service_bin = env!("CARGO_BIN_EXE_cds-kernel-service");

    let (cli, daprd, install, resources, config) = dapr_paths();
    if !cli.is_file() || !daprd.is_file() {
        eprintln!(
            "==> SKIP: dapr CLI / slim runtime not staged (run `just fetch-dapr`); skipping kernel sidecar healthz smoke"
        );
        return;
    }
    if !resources.is_dir() || !config.is_file() {
        eprintln!(
            "==> SKIP: dapr/components or dapr/config.yaml missing; skipping kernel sidecar healthz smoke"
        );
        return;
    }

    let ports = DaprPorts::allocate();

    // Use a smoke-specific app-id so a parallel `cds-kernel` (e.g. a
    // long-running developer sidecar) does not collide.
    let smoke_app_id = "cds-kernel-smoke";

    let mut cmd = build_dapr_command(
        &cli,
        smoke_app_id,
        &ports,
        &install,
        &resources,
        &config,
        service_bin,
    );
    let mut child = cmd.spawn().expect("dapr run --app-id cds-kernel-smoke");

    let result = async {
        let client = reqwest::Client::builder()
            .timeout(Duration::from_secs(5))
            .build()
            .expect("reqwest client");
        let deadline = Instant::now() + Duration::from_secs(25);

        // App readiness — the binary's own /healthz must answer first
        // (matches the Python harness's readiness wait shape from
        // ADR-017 §4 → daprd otherwise blocks invocation routing).
        wait_until_ready(
            &client,
            &format!("http://127.0.0.1:{}{HEALTHZ_PATH}", ports.app),
            &[200],
            deadline,
        )
        .await
        .map_err(|e| format!("app readiness: {e}"))?;

        // Sidecar readiness — Phase 0 placement is down (ADR-016 §6),
        // so /v1.0/healthz/outbound (204) is the right gate. Task 8.4
        // may flip this back to /v1.0/healthz once placement is up.
        wait_until_ready(
            &client,
            &format!("http://127.0.0.1:{}/v1.0/healthz/outbound", ports.http),
            &[200, 204],
            deadline,
        )
        .await
        .map_err(|e| format!("sidecar readiness: {e}"))?;

        // Drive /healthz through service invocation.
        let invoke_url = format!(
            "http://127.0.0.1:{}/v1.0/invoke/{smoke_app_id}/method{HEALTHZ_PATH}",
            ports.http
        );
        let resp = client
            .get(&invoke_url)
            .send()
            .await
            .map_err(|e| format!("invoke: {e}"))?;
        let status = resp.status();
        let body: Value = resp
            .json()
            .await
            .map_err(|e| format!("invoke decode: {e}"))?;
        if status != reqwest::StatusCode::OK {
            return Err(format!("invoke status: {status}; body={body}"));
        }
        if body["status"] != "ok" {
            return Err(format!("invoke body status: {body}"));
        }
        if body["kernel_id"] != KERNEL_ID {
            return Err(format!("invoke kernel_id mismatch: {body}"));
        }
        if body["schema_version"] != SCHEMA_VERSION {
            return Err(format!("invoke schema_version mismatch: {body}"));
        }
        // SERVICE_APP_ID lives at compile time; the sidecar uses
        // `smoke_app_id` for invocation routing. Invariant: the SDK
        // constant is the value baked into the Justfile recipe.
        assert_eq!(SERVICE_APP_ID, "cds-kernel");
        Ok::<(), String>(())
    }
    .await;

    // Tear down — SIGTERM-first so the dapr CLI's signal handler
    // forwards termination to daprd + the kernel binary (its
    // grandchildren). SIGKILL on the immediate child would orphan the
    // grandchildren to PID 1. SIGKILL is the 5 s fallback. ADR-018 §6
    // captures the contract; the kernel-side warden's SIGTERM-first
    // escalation (ADR-014 §9) remains deferred to Task 8.4.
    sigterm_then_kill(&mut child, Duration::from_secs(5)).await;

    if let Err(err) = result {
        panic!("kernel sidecar healthz smoke failed: {err}");
    }
}

/// Canonical vitals expected on every deduce verdict's `octagon_bounds`
/// envelope. Matches `crate::canonical::CANONICAL_VITALS` and the
/// payload sample shape below.
const EXPECTED_CANONICAL_VITALS: &[&str] = &[
    "diastolic_mmhg",
    "heart_rate_bpm",
    "respiratory_rate_bpm",
    "spo2_percent",
    "systolic_mmhg",
    "temp_celsius",
];

/// Decode the deduce response body and assert the verdict shape this
/// smoke pins: 3 samples processed, `bradycardia == [1]` (sample 1's
/// `heart_rate_bpm = 30` trips the default low-bound), and the octagon
/// hull names every canonical vital. Extracted from the test body so
/// `clippy::too_many_lines` stays satisfied.
fn assert_expected_deduce_verdict(body_bytes: &[u8]) -> Result<(), String> {
    let verdict: Verdict = serde_json::from_slice(body_bytes)
        .map_err(|e| format!("decode Verdict: {e}; body={body_bytes:?}"))?;
    if verdict.samples_processed != 3 {
        return Err(format!(
            "samples_processed mismatch: got {} (expected 3)",
            verdict.samples_processed
        ));
    }
    if verdict.breach_summary.bradycardia != vec![1u64] {
        return Err(format!(
            "bradycardia breach list mismatch: got {:?} (expected [1])",
            verdict.breach_summary.bradycardia
        ));
    }
    for name in EXPECTED_CANONICAL_VITALS {
        if !verdict.octagon_bounds.contains_key(*name) {
            return Err(format!(
                "octagon_bounds missing canonical vital `{name}`; keys={:?}",
                verdict.octagon_bounds.keys().collect::<Vec<_>>()
            ));
        }
    }
    Ok(())
}

/// Synthetic telemetry payload used by the daprd `/v1/deduce` smoke.
///
/// Three samples spanning the canonical-vital allowlist
/// (`crate::canonical::CANONICAL_VITALS`); sample 1 includes
/// `heart_rate_bpm = 30` which is below the default
/// `Phase0Thresholds.heart_rate_bpm.low = 50`, so the bradycardia
/// breach list comes back non-empty. The other readings stay in-band so
/// the verdict's other lists are deliberately empty.
fn deduce_payload() -> Value {
    json!({
        "payload": {
            "schema_version": SCHEMA_VERSION,
            "source": {
                "device_id": "cds-deduce-smoke-dev",
                "patient_pseudo_id": "cds-deduce-smoke-pseudo",
            },
            "samples": [
                {
                    "wall_clock_utc": "2026-04-29T12:55:00.000000Z",
                    "monotonic_ns": 1u64,
                    "vitals": {
                        "diastolic_mmhg": 70.0,
                        "heart_rate_bpm": 30.0,            // out of band — bradycardia.
                        "respiratory_rate_bpm": 16.0,
                        "spo2_percent": 97.0,
                        "systolic_mmhg": 118.0,
                        "temp_celsius": 37.0,
                    },
                    "events": [],
                },
                {
                    "wall_clock_utc": "2026-04-29T12:55:01.000000Z",
                    "monotonic_ns": 2u64,
                    "vitals": {
                        "diastolic_mmhg": 72.0,
                        "heart_rate_bpm": 60.0,
                        "respiratory_rate_bpm": 18.0,
                        "spo2_percent": 96.0,
                        "systolic_mmhg": 120.0,
                        "temp_celsius": 36.9,
                    },
                    "events": [],
                },
                {
                    "wall_clock_utc": "2026-04-29T12:55:02.000000Z",
                    "monotonic_ns": 3u64,
                    "vitals": {
                        "diastolic_mmhg": 71.0,
                        "heart_rate_bpm": 65.0,
                        "respiratory_rate_bpm": 17.0,
                        "spo2_percent": 97.0,
                        "systolic_mmhg": 119.0,
                        "temp_celsius": 37.1,
                    },
                    "events": [],
                },
            ],
        },
    })
}

#[tokio::test]
async fn dapr_sidecar_drives_deduce_through_service_invocation() {
    let service_bin = env!("CARGO_BIN_EXE_cds-kernel-service");

    let (cli, daprd, install, resources, config) = dapr_paths();
    if !cli.is_file() || !daprd.is_file() {
        eprintln!(
            "==> SKIP: dapr CLI / slim runtime not staged (run `just fetch-dapr`); skipping kernel sidecar deduce smoke"
        );
        return;
    }
    if !resources.is_dir() || !config.is_file() {
        eprintln!(
            "==> SKIP: dapr/components or dapr/config.yaml missing; skipping kernel sidecar deduce smoke"
        );
        return;
    }

    let ports = DaprPorts::allocate();
    // Distinct app-id so this sidecar coexists with the healthz smoke
    // (and any developer sidecar) without colliding.
    let smoke_app_id = "cds-kernel-deduce-smoke";

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
        .expect("dapr run --app-id cds-kernel-deduce-smoke");

    let result = async {
        let client = reqwest::Client::builder()
            .timeout(Duration::from_secs(10))
            .build()
            .expect("reqwest client");
        let deadline = Instant::now() + Duration::from_secs(25);

        wait_until_ready(
            &client,
            &format!("http://127.0.0.1:{}{HEALTHZ_PATH}", ports.app),
            &[200],
            deadline,
        )
        .await
        .map_err(|e| format!("app readiness: {e}"))?;

        wait_until_ready(
            &client,
            &format!("http://127.0.0.1:{}/v1.0/healthz/outbound", ports.http),
            &[200, 204],
            deadline,
        )
        .await
        .map_err(|e| format!("sidecar readiness: {e}"))?;

        let invoke_url = format!(
            "http://127.0.0.1:{}/v1.0/invoke/{smoke_app_id}/method{DEDUCE_PATH}",
            ports.http
        );
        let resp = client
            .post(&invoke_url)
            .json(&deduce_payload())
            .send()
            .await
            .map_err(|e| format!("invoke: {e}"))?;
        let status = resp.status();
        let body_bytes = resp
            .bytes()
            .await
            .map_err(|e| format!("invoke read: {e}"))?;
        if status != reqwest::StatusCode::OK {
            return Err(format!(
                "invoke status: {status}; body={}",
                String::from_utf8_lossy(&body_bytes)
            ));
        }

        assert_expected_deduce_verdict(&body_bytes)?;
        Ok::<(), String>(())
    }
    .await;

    sigterm_then_kill(&mut child, Duration::from_secs(5)).await;

    if let Err(err) = result {
        panic!("kernel sidecar deduce smoke failed: {err}");
    }
}
