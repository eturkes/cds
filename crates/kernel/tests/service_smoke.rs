//! Integration smoke for the Phase 0 kernel service (Task 8.3a).
//!
//! Two suites:
//!
//! 1. **Standalone HTTP** — bind the axum router on an ephemeral port,
//!    issue an actual TCP request to `/healthz`, decode the body, and
//!    assert the response shape pinning the kernel invariants.
//!
//! 2. **Gated Dapr sidecar** — when `.bin/dapr` and the slim
//!    `.bin/.dapr/.dapr/bin/daprd` are staged, spawn `dapr run -- <bin>`
//!    around the just-built `cds-kernel-service`, wait for the
//!    `/v1.0/healthz/outbound` readiness probe, then drive
//!    `/v1.0/invoke/cds-kernel-smoke/method/healthz` through the
//!    sidecar and assert the same invariants. Skipped (loud notice)
//!    when Dapr is not staged. Mirrors the rs-lean gating pattern.
//!
//! ADR-018 documents the contract this smoke gates.

use std::net::TcpListener as StdTcpListener;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

use cds_kernel::KERNEL_ID;
use cds_kernel::schema::SCHEMA_VERSION;
use cds_kernel::service::{
    HEALTHZ_PATH, HOST_ENV, KernelHealthz, PORT_ENV, SERVICE_APP_ID, build_router,
};
use nix::sys::signal::{Signal, kill};
use nix::unistd::Pid;
use serde_json::Value;
use tokio::process::{Child, Command};

/// Bind ephemeral, capture port, drop socket — single-use TCP port lease
/// for tests. Race window with another binder is theoretical at the
/// timescale of a test pass.
fn pick_free_port() -> u16 {
    let listener = StdTcpListener::bind("127.0.0.1:0").expect("bind ephemeral");
    listener.local_addr().expect("local_addr").port()
}

/// Wait until `url` responds with one of `accept_status`, or the deadline
/// expires. Returns the final HTTP status on success.
async fn wait_until_ready(
    client: &reqwest::Client,
    url: &str,
    accept_status: &[u16],
    deadline: Instant,
) -> Result<reqwest::StatusCode, String> {
    let mut last_status: Option<reqwest::StatusCode> = None;
    let mut last_err: Option<String> = None;
    while Instant::now() < deadline {
        match client.get(url).send().await {
            Ok(resp) => {
                last_status = Some(resp.status());
                if accept_status.contains(&resp.status().as_u16()) {
                    return Ok(resp.status());
                }
            }
            Err(err) => last_err = Some(err.to_string()),
        }
        tokio::time::sleep(Duration::from_millis(150)).await;
    }
    Err(format!(
        "readiness wait timed out for {url}: status={last_status:?} err={last_err:?}"
    ))
}

#[tokio::test]
async fn standalone_axum_serves_healthz() {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
        .await
        .expect("bind");
    let addr = listener.local_addr().expect("local_addr");
    let server = tokio::spawn(async move {
        let _ = axum::serve(listener, build_router()).await;
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

fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .map(Path::to_path_buf)
        .expect("kernel crate is two levels under repo root")
}

fn dapr_paths() -> (PathBuf, PathBuf, PathBuf, PathBuf, PathBuf) {
    let root = repo_root();
    let cli = root.join(".bin").join("dapr");
    let install = root.join(".bin").join(".dapr");
    let daprd = install.join(".dapr").join("bin").join("daprd");
    let resources = root.join("dapr").join("components");
    let config = root.join("dapr").join("config.yaml");
    (cli, daprd, install, resources, config)
}

/// Bundle the four ports the sidecar needs so the helper signature stays
/// readable.
struct DaprPorts {
    app: u16,
    http: u16,
    grpc: u16,
    metrics: u16,
}

/// Build the `dapr run -- <bin>` command. Extracted from the test body so
/// `clippy::too_many_lines` doesn't flag the (legitimately long) test driver.
/// `kill_on_drop` is the ADR-004 §7 hammer; the test additionally sends
/// SIGTERM-first via `sigterm_then_kill` so the dapr CLI's signal handler
/// has a chance to forward termination to its grandchildren before SIGKILL
/// orphans them to PID 1 (ADR-018 §6).
fn build_dapr_command(
    cli: &Path,
    smoke_app_id: &str,
    ports: &DaprPorts,
    install: &Path,
    resources: &Path,
    config: &Path,
    service_bin: &str,
) -> Command {
    let mut cmd = Command::new(cli);
    cmd.arg("run")
        .arg("--app-id")
        .arg(smoke_app_id)
        .arg("--app-port")
        .arg(ports.app.to_string())
        .arg("--app-protocol")
        .arg("http")
        .arg("--dapr-http-port")
        .arg(ports.http.to_string())
        .arg("--dapr-grpc-port")
        .arg(ports.grpc.to_string())
        .arg("--metrics-port")
        .arg(ports.metrics.to_string())
        .arg("--runtime-path")
        .arg(install)
        .arg("--resources-path")
        .arg(resources)
        .arg("--config")
        .arg(config)
        .arg("--log-level")
        .arg("info")
        .arg("--")
        .arg(service_bin);
    cmd.env(HOST_ENV, "127.0.0.1")
        .env(PORT_ENV, ports.app.to_string())
        .kill_on_drop(true)
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null());
    cmd
}

#[tokio::test]
async fn dapr_sidecar_drives_healthz_through_service_invocation() {
    // Path to the just-built service binary, set by cargo at compile time.
    let service_bin = env!("CARGO_BIN_EXE_cds-kernel-service");

    let (cli, daprd, install, resources, config) = dapr_paths();
    if !cli.is_file() || !daprd.is_file() {
        eprintln!(
            "==> SKIP: dapr CLI / slim runtime not staged (run `just fetch-dapr`); skipping kernel sidecar smoke"
        );
        return;
    }
    if !resources.is_dir() || !config.is_file() {
        eprintln!(
            "==> SKIP: dapr/components or dapr/config.yaml missing; skipping kernel sidecar smoke"
        );
        return;
    }

    let ports = DaprPorts {
        app: pick_free_port(),
        http: pick_free_port(),
        grpc: pick_free_port(),
        metrics: pick_free_port(),
    };

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
        panic!("kernel sidecar smoke failed: {err}");
    }
}

async fn sigterm_then_kill(child: &mut Child, grace: Duration) {
    if let Some(pid_u32) = child.id() {
        if let Ok(pid_i32) = i32::try_from(pid_u32) {
            let _ = kill(Pid::from_raw(pid_i32), Signal::SIGTERM);
        }
    }
    if tokio::time::timeout(grace, child.wait()).await.is_err() {
        let _ = child.kill().await;
        let _ = child.wait().await;
    }
}
