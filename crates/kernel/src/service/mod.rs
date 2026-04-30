//! Phase 0 Rust kernel HTTP service (Task 8.3a foundation).
//!
//! This module wires the kernel's existing in-process pipelines (the
//! deductive evaluator [`crate::deduce`], the SMT solver layer
//! [`crate::solver`], the Lean re-check bridge [`crate::lean`]) to a
//! thin `axum` JSON-over-TCP service. Task 8.3a (this module) ships
//! the foundation only:
//!
//! - [`build_router`] returns an `axum::Router` with the lifecycle
//!   middleware (`tower_http::trace::TraceLayer`) and a single
//!   liveness route at [`HEALTHZ_PATH`].
//! - [`config`] resolves the bind host + port from the
//!   `CDS_KERNEL_HOST` / `CDS_KERNEL_PORT` environment variables.
//! - [`errors`] ships the JSON-over-TCP error envelope (`{error,
//!   detail}`) used by every endpoint when an internal error lifts to
//!   HTTP 422 — Task 8.3b drops in pipeline-specific
//!   [`axum::response::IntoResponse`] impls on top of the same wire
//!   shape.
//!
//! Task 8.3b will extend [`build_router`] with `/v1/deduce`,
//! `/v1/solve`, and `/v1/recheck` handlers. The transport contract is
//! JSON-over-TCP only (constraint **C6**); the sidecar invokes the
//! service through `http://localhost:<dapr-http-port>/v1.0/invoke/
//! cds-kernel/method/...`. See ADR-018 for the kernel service contract
//! and ADR-016 §5 for the sidecar invocation contract.

pub mod app;
pub mod config;
pub mod errors;

pub use app::{HEALTHZ_PATH, KernelHealthz, SERVICE_APP_ID, build_router};
pub use config::{
    ConfigError, DEFAULT_HOST, DEFAULT_PORT, HOST_ENV, PORT_ENV, parse_port_raw, resolve_host,
    resolve_port,
};
pub use errors::{ErrorBody, error_response};
