//! Phase 0 Rust kernel service binary (Task 8.3a).
//!
//! Mirrors the Python harness's `cds-harness-service` entrypoint
//! (ADR-017 §1) so the Justfile contract stays symmetric: bind the
//! [`cds_kernel::service::build_router`] axum app to a TCP listener
//! resolved from `CDS_KERNEL_HOST` / `CDS_KERNEL_PORT` (or their
//! defaults), serve until SIGINT / SIGTERM, and exit cleanly.
//!
//! Usage (run by hand):
//!
//! ```text
//! $ CDS_KERNEL_PORT=8082 cargo run --bin cds-kernel-service
//! ```
//!
//! Usage (under Dapr — preferred path; see `just rs-service-dapr`):
//!
//! ```text
//! $ dapr run --app-id cds-kernel --app-port 8082 \
//!     --runtime-path .bin/.dapr --resources-path dapr/components \
//!     --config dapr/config.yaml -- cds-kernel-service
//! ```
//!
//! The binary deliberately stays tiny: argument parsing is limited to
//! `--help` (any other flag is a fail-fast). All knobs come from the
//! environment so the Justfile / Dapr CLI is the single source of
//! configuration truth.

use std::env;
use std::process::ExitCode;

use cds_kernel::service::{
    DEFAULT_HOST, DEFAULT_PORT, HOST_ENV, KernelServiceState, PORT_ENV, build_router, resolve_host,
    resolve_port,
};

const USAGE: &str = "\
Usage: cds-kernel-service [--help]

Boot the CDS Phase 0 Rust kernel HTTP service.

Environment (bind address):
  CDS_KERNEL_HOST          Bind address (default 127.0.0.1)
  CDS_KERNEL_PORT          Bind port    (default 8082)

Environment (option floors — per-request `options` envelopes still
override individual fields; see ADR-020 §5):
  CDS_Z3_PATH              Path to the Z3 binary (default: bare `z3` from $PATH).
  CDS_CVC5_PATH            Path to the cvc5 binary (default: bare `cvc5` from $PATH).
  CDS_SOLVER_TIMEOUT_MS    SMT solver wall-clock timeout, milliseconds (default: 30000).
  CDS_KIMINA_URL           Kimina REST endpoint (default: http://127.0.0.1:8000).
  CDS_LEAN_TIMEOUT_MS      Lean re-check wall-clock timeout, milliseconds (default: 60000).

Endpoints (Phase 0 / Task 8.3b1 + 8.3b2a):
  GET  /healthz     Liveness probe → {status, kernel_id, phase, schema_version}.
  POST /v1/deduce   {payload, rules?}  → Verdict (deductive evaluator).
  POST /v1/solve    {matrix, options?} → FormalVerificationTrace (Z3 + cvc5).
  POST /v1/recheck  {trace, options?}  → LeanRecheck (Kimina REST).

The deduce daprd smoke ships in Task 8.3b2a; the solve / recheck daprd
smokes ship in Task 8.3b2b (ADR-020 §3).
";

fn main() -> ExitCode {
    match run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(BinError::HelpRequested) => {
            print!("{USAGE}");
            ExitCode::SUCCESS
        }
        Err(BinError::UnknownArgument(arg)) => {
            eprintln!("cds-kernel-service: unknown argument: {arg}");
            eprint!("{USAGE}");
            ExitCode::from(2)
        }
        Err(BinError::Config(msg)) => {
            eprintln!("cds-kernel-service: configuration error: {msg}");
            ExitCode::FAILURE
        }
        Err(BinError::Bind { addr, source }) => {
            eprintln!("cds-kernel-service: failed to bind {addr}: {source}");
            ExitCode::FAILURE
        }
        Err(BinError::Serve(source)) => {
            eprintln!("cds-kernel-service: server terminated: {source}");
            ExitCode::FAILURE
        }
    }
}

#[derive(Debug)]
enum BinError {
    HelpRequested,
    UnknownArgument(String),
    Config(String),
    Bind {
        addr: String,
        source: std::io::Error,
    },
    Serve(std::io::Error),
}

fn run() -> Result<(), BinError> {
    parse_argv(env::args().skip(1))?;

    init_tracing();

    let host = resolve_host();
    let port = resolve_port().map_err(|e| BinError::Config(e.to_string()))?;
    let addr_string = format!("{host}:{port}");

    let runtime = tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
        .expect("failed to construct tokio runtime");

    runtime.block_on(serve(addr_string))
}

async fn serve(addr_string: String) -> Result<(), BinError> {
    let listener = tokio::net::TcpListener::bind(&addr_string)
        .await
        .map_err(|source| BinError::Bind {
            addr: addr_string.clone(),
            source,
        })?;
    let bound = listener.local_addr().map_err(|source| BinError::Bind {
        addr: addr_string.clone(),
        source,
    })?;
    // Resolve the per-handler option floors at boot — fail-loud on bad
    // env values so an operator typo surfaces here rather than at first
    // request (ADR-020 §2).
    let state = KernelServiceState::from_env();
    tracing::info!(
        addr = %bound,
        host_env = HOST_ENV,
        port_env = PORT_ENV,
        default_host = DEFAULT_HOST,
        default_port = DEFAULT_PORT,
        z3_path = %state.verify_options.z3_path.display(),
        cvc5_path = %state.verify_options.cvc5_path.display(),
        solver_timeout_ms = state.verify_options.timeout.as_millis(),
        kimina_url = %state.lean_options.kimina_url,
        lean_timeout_ms = state.lean_options.timeout.as_millis(),
        "cds-kernel-service listening"
    );

    axum::serve(listener, build_router(state))
        .with_graceful_shutdown(shutdown_signal())
        .await
        .map_err(BinError::Serve)?;
    Ok(())
}

fn parse_argv<I: IntoIterator<Item = String>>(argv: I) -> Result<(), BinError> {
    let mut iter = argv.into_iter();
    if let Some(first) = iter.next() {
        match first.as_str() {
            "-h" | "--help" => return Err(BinError::HelpRequested),
            other => return Err(BinError::UnknownArgument(other.to_string())),
        }
    }
    Ok(())
}

fn init_tracing() {
    let filter = tracing_subscriber::EnvFilter::try_from_default_env()
        .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("info"));
    // Allow re-init in tests (or when both stdout + a Dapr sidecar set
    // RUST_LOG): swallow the "global subscriber already set" race.
    let _ = tracing_subscriber::fmt()
        .with_env_filter(filter)
        .with_target(false)
        .try_init();
}

async fn shutdown_signal() {
    let ctrl_c = async {
        if let Err(err) = tokio::signal::ctrl_c().await {
            tracing::warn!(
                ?err,
                "ctrl_c handler failed; shutdown will rely on SIGTERM only"
            );
        }
    };

    #[cfg(unix)]
    let terminate = async {
        match tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate()) {
            Ok(mut sig) => {
                sig.recv().await;
            }
            Err(err) => {
                tracing::warn!(?err, "SIGTERM handler init failed; ctrl-c only");
                std::future::pending::<()>().await;
            }
        }
    };

    #[cfg(not(unix))]
    let terminate = std::future::pending::<()>();

    tokio::select! {
        () = ctrl_c => {
            tracing::info!("ctrl-c received; shutting down");
        }
        () = terminate => {
            tracing::info!("SIGTERM received; shutting down");
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{BinError, parse_argv};

    fn args(literal: &[&str]) -> Vec<String> {
        literal.iter().map(|s| (*s).to_string()).collect()
    }

    #[test]
    fn parse_argv_accepts_no_arguments() {
        parse_argv(args(&[])).expect("no args is fine");
    }

    #[test]
    fn parse_argv_recognises_help_flag() {
        match parse_argv(args(&["--help"])) {
            Err(BinError::HelpRequested) => {}
            other => panic!("expected HelpRequested, got {other:?}"),
        }
        match parse_argv(args(&["-h"])) {
            Err(BinError::HelpRequested) => {}
            other => panic!("expected HelpRequested, got {other:?}"),
        }
    }

    #[test]
    fn parse_argv_rejects_unknown_flags() {
        match parse_argv(args(&["--port", "9000"])) {
            Err(BinError::UnknownArgument(arg)) => assert_eq!(arg, "--port"),
            other => panic!("expected UnknownArgument, got {other:?}"),
        }
    }
}
