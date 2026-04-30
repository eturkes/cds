//! Phase 0 Rust kernel HTTP service (Tasks 8.3a foundation + 8.3b1
//! pipeline handlers + 8.3b2a env-driven option floors).
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
//!   [`handlers::RECHECK_PATH`]. The factory takes a
//!   [`state::KernelServiceState`] which `axum::extract::State` plumbs
//!   to the pipeline handlers; the liveness handler stays stateless.
//! - [`config`] resolves the bind host + port from the
//!   `CDS_KERNEL_HOST` / `CDS_KERNEL_PORT` environment variables.
//! - [`errors`] ships the JSON-over-TCP error envelope (`{error,
//!   detail}`) plus per-pipeline [`axum::response::IntoResponse`] impls
//!   for `DeduceError` / `SolverError` / `LeanError`, every variant
//!   lifting to HTTP 422.
//! - [`handlers`] hosts the three pipeline handlers and their request
//!   envelopes / wire-format mirrors.
//! - [`state`] resolves the per-handler option floors
//!   ([`crate::solver::VerifyOptions`] / [`crate::lean::LeanOptions`])
//!   from `CDS_Z3_PATH` / `CDS_CVC5_PATH` / `CDS_SOLVER_TIMEOUT_MS` /
//!   `CDS_KIMINA_URL` / `CDS_LEAN_TIMEOUT_MS` at boot. Per-request
//!   `options` envelopes still replace individual fields on top of the
//!   state floor (ADR-020 §5).
//!
//! Task 8.3b2b will add the daprd-driven cargo integration tests for
//! `/v1/solve` + `/v1/recheck` (gated on `.bin/z3`+`.bin/cvc5` and
//! `CDS_KIMINA_URL` respectively); 8.3b2a (this revision) ships the
//! foundation refactor plus the dependency-free `/v1/deduce` daprd
//! smoke. The transport contract is JSON-over-TCP only (constraint
//! **C6**); the sidecar invokes the service through
//! `http://localhost:<dapr-http-port>/v1.0/invoke/cds-kernel/method/...`.
//! See ADR-018 / ADR-019 / ADR-020 for the kernel service contract and
//! ADR-016 §5 for the sidecar invocation contract.

pub mod app;
pub mod config;
pub mod errors;
pub mod handlers;
pub mod state;

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
pub use state::{
    CVC5_PATH_ENV, KIMINA_URL_ENV, KernelServiceState, LEAN_TIMEOUT_MS_ENV, SOLVER_TIMEOUT_MS_ENV,
    Z3_PATH_ENV,
};
