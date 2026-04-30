//! Phase 0 Rust kernel HTTP service (Tasks 8.3a foundation + 8.3b1
//! pipeline handlers).
//!
//! This module wires the kernel's existing in-process pipelines (the
//! deductive evaluator [`crate::deduce`], the SMT solver layer
//! [`crate::solver`], the Lean re-check bridge [`crate::lean`]) to a
//! thin `axum` JSON-over-TCP service. The current revision ships:
//!
//! - [`build_router`] returns an `axum::Router` with the lifecycle
//!   middleware (`tower_http::trace::TraceLayer`), a liveness route at
//!   [`HEALTHZ_PATH`], and three `POST` pipeline routes —
//!   [`handlers::DEDUCE_PATH`], [`handlers::SOLVE_PATH`],
//!   [`handlers::RECHECK_PATH`].
//! - [`config`] resolves the bind host + port from the
//!   `CDS_KERNEL_HOST` / `CDS_KERNEL_PORT` environment variables.
//! - [`errors`] ships the JSON-over-TCP error envelope (`{error,
//!   detail}`) plus per-pipeline [`axum::response::IntoResponse`] impls
//!   for `DeduceError` / `SolverError` / `LeanError`, every variant
//!   lifting to HTTP 422.
//! - [`handlers`] hosts the three pipeline handlers and their request
//!   envelopes / wire-format mirrors.
//!
//! Task 8.3b2 will add a Dapr-driven cargo integration test that drives
//! all three pipeline endpoints through daprd, plus an `AppState` if
//! environment-driven option overrides materially benefit from one-shot
//! resolution at boot. The transport contract is JSON-over-TCP only
//! (constraint **C6**); the sidecar invokes the service through
//! `http://localhost:<dapr-http-port>/v1.0/invoke/cds-kernel/method/...`.
//! See ADR-018 / ADR-019 for the kernel service contract and ADR-016 §5
//! for the sidecar invocation contract.

pub mod app;
pub mod config;
pub mod errors;
pub mod handlers;

pub use app::{HEALTHZ_PATH, KernelHealthz, SERVICE_APP_ID, build_router};
pub use config::{
    ConfigError, DEFAULT_HOST, DEFAULT_PORT, HOST_ENV, PORT_ENV, parse_port_raw, resolve_host,
    resolve_port,
};
pub use errors::{ErrorBody, error_response};
pub use handlers::{
    DEDUCE_PATH, DeduceRequest, LeanMessageWire, LeanRecheckWire, LeanSeverityWire, RECHECK_PATH,
    RecheckOptionsWire, RecheckRequest, SOLVE_PATH, SolveOptionsWire, SolveRequest,
};
