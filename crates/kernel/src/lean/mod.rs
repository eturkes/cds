//! Headless Lean 4 interop (Phase 0, Task 7) — Kimina REST bridge.
//!
//! Consumes a [`FormalVerificationTrace::alethe_proof`] (cvc5-emitted
//! Alethe S-expression from Task 6), wraps it in a self-contained Lean
//! 4 snippet (see [`snippet`]), and POSTs it to a running Kimina Lean
//! Server (see [`client`]). The response is decoded into a
//! [`LeanRecheck`] that surfaces:
//!
//! - `ok` — every probe passed and Lean reported no errors.
//! - `messages` — verbatim Lean info / warning / error messages.
//! - `probes` — the four `PROBE name=value` payloads parsed out of
//!   the Lean info messages (see [`snippet`] for the contract).
//! - `elapsed_ms` + `env_id` — Kimina-side timing + REPL env handle
//!   for diagnostics.
//!
//! ## Phase 0 scope (binding)
//!
//! The Phase 0 re-check is **structural**, not foundational. It proves
//! that the Alethe certificate has been ingested by the Lean 4 kernel
//! and that the certificate carries the structural invariants every
//! Alethe proof must (non-empty, S-expression-shaped, references at
//! least one `(assume …)` and one `:rule …`). A *foundational*
//! re-check that lifts the Alethe proof into Lean's kernel as a
//! certified theorem requires `lean-smt`'s Alethe importer (or
//! Carcara-as-Lean-tactic), both of which add Mathlib / project
//! scaffolding that would explode Kimina's LRU header cache. That swap
//! is deferred to a Phase 1 ADR; the bridge surface stays the same.
//!
//! ## ADR alignment
//!
//! - ADR-002 / **C6**: REST is JSON-over-TCP. No proprietary RPC.
//! - ADR-004: Kimina is an *operator-managed daemon*, not a per-call
//!   child of the warden. The warden discipline still applies to any
//!   binary the *kernel* spawns; Kimina is brought up by `just kimina-up`
//!   (future task) or by hand. Process supervision of the daemon is
//!   not the kernel's job.
//! - ADR-014 §9 deferred SIGTERM-first escalation to Task 7 alongside
//!   Lean. This module spawns no children — the deferral is rolled
//!   forward to Task 8 (Dapr workflow) where the operator-launched
//!   sidecar boundary will own daemon lifecycle. ADR-015 captures the
//!   amendment.

pub mod client;
pub mod snippet;

use std::collections::BTreeMap;
use std::time::Duration;

use crate::schema::FormalVerificationTrace;

pub use client::{extract_probes, parse_response, post_verify, probes_satisfied};
pub use snippet::render as render_snippet;

/// Knobs for [`recheck`].
///
/// `kimina_url` defaults to `http://127.0.0.1:8000`, matching Kimina's
/// out-of-the-box `LEAN_SERVER_HOST=0.0.0.0 LEAN_SERVER_PORT=8000`.
/// The `/verify` suffix is appended automatically if absent.
#[derive(Debug, Clone)]
pub struct LeanOptions {
    pub kimina_url: String,
    pub timeout: Duration,
    pub custom_id: String,
    pub extra_headers: BTreeMap<String, String>,
}

impl Default for LeanOptions {
    fn default() -> Self {
        Self {
            kimina_url: "http://127.0.0.1:8000".to_string(),
            timeout: Duration::from_secs(60),
            custom_id: "cds-recheck-0".to_string(),
            extra_headers: BTreeMap::new(),
        }
    }
}

/// Severity surfaced for each Lean message returned by Kimina.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LeanSeverity {
    Info,
    Warning,
    Error,
}

/// One Lean compiler message (info / warning / error) returned from
/// the Kimina REPL.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LeanMessage {
    pub severity: LeanSeverity,
    pub body: String,
}

/// Outcome of one Lean re-check round-trip.
#[derive(Debug, Clone)]
pub struct LeanRecheck {
    /// `true` iff every Phase 0 probe landed and Lean reported no
    /// `error`-severity message.
    pub ok: bool,
    /// Custom id round-tripped from the request (per-call correlation).
    pub custom_id: String,
    /// Kimina REPL environment id (opaque, useful for diagnostics).
    pub env_id: Option<String>,
    /// Wall-clock time the Kimina worker spent on this call.
    pub elapsed_ms: u64,
    /// Verbatim Lean compiler messages (info / warn / error).
    pub messages: Vec<LeanMessage>,
    /// Parsed `PROBE name=value` payloads (see [`snippet`] for the
    /// four Phase 0 probes).
    pub probes: BTreeMap<String, String>,
}

/// Errors raised by the Lean re-check bridge.
#[derive(Debug, thiserror::Error)]
pub enum LeanError {
    /// The trace under re-check carried no Alethe proof — typically
    /// the SMT verdict was `sat` and there is nothing to certify.
    #[error("no Alethe proof to re-check (trace.sat={sat})")]
    NoProof { sat: bool },
    /// Network / TLS / connect failure talking to Kimina.
    #[error("transport failure talking to `{url}`: {detail}")]
    Transport { url: String, detail: String },
    /// Kimina returned a non-2xx HTTP status.
    #[error("kimina returned http {status} from `{url}`: {body}")]
    ServerError {
        url: String,
        status: u16,
        body: String,
    },
    /// Response body did not match a recognisable Kimina envelope.
    #[error("kimina response decode failed: {reason}")]
    DecodeFailed { reason: String },
}

/// Re-check `trace.alethe_proof` against the Kimina Lean Server.
///
/// # Errors
/// See [`LeanError`].
pub async fn recheck(
    trace: &FormalVerificationTrace,
    opts: &LeanOptions,
) -> Result<LeanRecheck, LeanError> {
    let proof = trace
        .alethe_proof
        .as_deref()
        .ok_or(LeanError::NoProof { sat: trace.sat })?;
    let lean_source = snippet::render(proof);
    client::post_verify(
        &opts.kimina_url,
        &opts.custom_id,
        &lean_source,
        opts.timeout,
        &opts.extra_headers,
    )
    .await
}

#[cfg(test)]
mod tests {
    use super::{LeanError, LeanOptions, recheck};
    use crate::schema::{FormalVerificationTrace, SCHEMA_VERSION};

    #[test]
    fn default_options_are_sane() {
        let o = LeanOptions::default();
        assert!(o.kimina_url.starts_with("http://"));
        assert!(o.timeout.as_secs() > 0);
        assert!(!o.custom_id.is_empty());
        assert!(o.extra_headers.is_empty());
    }

    #[tokio::test]
    async fn recheck_refuses_sat_traces() {
        let trace = FormalVerificationTrace {
            schema_version: SCHEMA_VERSION.to_string(),
            sat: true,
            muc: Vec::new(),
            alethe_proof: None,
        };
        let err = recheck(&trace, &LeanOptions::default())
            .await
            .expect_err("sat trace must reject");
        match err {
            LeanError::NoProof { sat } => assert!(sat),
            other => panic!("expected NoProof, got {other:?}"),
        }
    }

    #[tokio::test]
    async fn recheck_refuses_unsat_trace_without_proof() {
        let trace = FormalVerificationTrace {
            schema_version: SCHEMA_VERSION.to_string(),
            sat: false,
            muc: vec!["atom:x:0-1".to_string()],
            alethe_proof: None,
        };
        let err = recheck(&trace, &LeanOptions::default())
            .await
            .expect_err("missing-proof trace must reject");
        match err {
            LeanError::NoProof { sat } => assert!(!sat),
            other => panic!("expected NoProof, got {other:?}"),
        }
    }

    #[tokio::test]
    async fn recheck_surfaces_transport_error_for_bogus_url() {
        let trace = FormalVerificationTrace {
            schema_version: SCHEMA_VERSION.to_string(),
            sat: false,
            muc: vec![],
            alethe_proof: Some("(proof)".to_string()),
        };
        let opts = LeanOptions {
            kimina_url: "http://127.0.0.1:1".to_string(), // never bound
            timeout: std::time::Duration::from_millis(500),
            ..LeanOptions::default()
        };
        let err = recheck(&trace, &opts)
            .await
            .expect_err("connect to :1 must fail");
        match err {
            LeanError::Transport { url, .. } => assert!(url.contains("127.0.0.1:1")),
            other => panic!("expected Transport, got {other:?}"),
        }
    }
}
