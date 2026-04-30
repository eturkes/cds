//! Shared cargo-integration-test helpers (Task 8.3b2a lift).
//!
//! Each integration-test file under `tests/` is compiled as its own
//! crate, so cross-test sharing happens by declaring `mod common;`
//! against this directory module. Items not used by every consumer
//! file get `#[allow(dead_code)]` because cargo's per-crate dead-code
//! analysis can't see cross-test usage.
//!
//! ## What lives here
//!
//! - [`pick_free_port`] — bind ephemeral, capture port, drop socket.
//!   Single-use TCP port lease for tests; race-window with another
//!   binder is theoretical at the timescale of one test pass.
//! - [`wait_until_ready`] — poll a URL until it returns one of
//!   `accept_status`, or the deadline expires. Used for app-readiness
//!   and Dapr-sidecar-readiness gates.
//! - [`sigterm_then_kill`] — SIGTERM-first cleanup of a tokio child,
//!   escalating to SIGKILL after a grace window. **Narrowly authorized**
//!   for the dapr CLI in test cleanup only — production solver-warden
//!   children stay on the SIGKILL-on-drop discipline (ADR-014 §9 →
//!   ADR-015 §8 → ADR-016 §7 → ADR-018 §6 → ADR-019 §11 → ADR-020 §6).
//! - [`repo_root`] / [`dapr_paths`] — locate the repo root from the
//!   manifest dir and resolve `.bin/dapr` / slim runtime / components
//!   / config paths relative to it.
//! - [`DaprPorts`] / [`build_dapr_command`] — bundle the four
//!   per-sidecar ports and assemble the `dapr run -- <bin>` command
//!   line. Extracted from each test body so `clippy::too_many_lines`
//!   doesn't flag the (legitimately long) test drivers.

#![allow(dead_code)]

use std::net::TcpListener as StdTcpListener;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

use cds_kernel::service::{HOST_ENV, PORT_ENV};
use nix::sys::signal::{Signal, kill};
use nix::unistd::Pid;
use tokio::process::{Child, Command};

/// Bind ephemeral, capture port, drop socket — single-use TCP port lease
/// for tests. Race window with another binder is theoretical at the
/// timescale of a test pass.
pub fn pick_free_port() -> u16 {
    let listener = StdTcpListener::bind("127.0.0.1:0").expect("bind ephemeral");
    listener.local_addr().expect("local_addr").port()
}

/// Wait until `url` responds with one of `accept_status`, or the deadline
/// expires. Returns the final HTTP status on success.
pub async fn wait_until_ready(
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

/// Repo root resolved from `CARGO_MANIFEST_DIR` (the kernel crate is
/// `crates/kernel/` under the workspace root).
pub fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .map(Path::to_path_buf)
        .expect("kernel crate is two levels under repo root")
}

/// `(cli, daprd, install, resources, config)` — the five filesystem
/// paths the gated daprd smokes need.
pub fn dapr_paths() -> (PathBuf, PathBuf, PathBuf, PathBuf, PathBuf) {
    let root = repo_root();
    let cli = root.join(".bin").join("dapr");
    let install = root.join(".bin").join(".dapr");
    let daprd = install.join(".dapr").join("bin").join("daprd");
    let resources = root.join("dapr").join("components");
    let config = root.join("dapr").join("config.yaml");
    (cli, daprd, install, resources, config)
}

/// Bundle the four ports each daprd sidecar needs so the helper
/// signatures stay readable.
pub struct DaprPorts {
    pub app: u16,
    pub http: u16,
    pub grpc: u16,
    pub metrics: u16,
}

impl DaprPorts {
    /// Allocate four free ports in one call.
    pub fn allocate() -> Self {
        Self {
            app: pick_free_port(),
            http: pick_free_port(),
            grpc: pick_free_port(),
            metrics: pick_free_port(),
        }
    }
}

/// Build the `dapr run -- <service-bin>` command line.
///
/// `kill_on_drop` is the ADR-004 §7 hammer; the test additionally sends
/// SIGTERM-first via [`sigterm_then_kill`] so the dapr CLI's signal
/// handler has a chance to forward termination to its grandchildren
/// before SIGKILL orphans them to PID 1 (ADR-018 §6).
pub fn build_dapr_command(
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

/// SIGTERM the child first, then SIGKILL after `grace` if it has not
/// exited. **Narrowly authorized** for the dapr CLI in test cleanup
/// only — production solver-warden children stay on SIGKILL-on-drop
/// (ADR-014 §9 → ADR-015 §8 → ADR-016 §7 → ADR-018 §6 → ADR-019 §11 →
/// ADR-020 §6).
pub async fn sigterm_then_kill(child: &mut Child, grace: Duration) {
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
