//! Phase 0 kernel-service pipeline endpoint handlers (Tasks 8.3b1 +
//! 8.3b2a).
//!
//! Three thin axum handlers that lift the kernel's existing in-process
//! pipelines onto JSON-over-TCP routes (constraint **C6**):
//!
//! | Method | Path           | Backed by                            | Response                    |
//! | ------ | -------------- | ------------------------------------ | --------------------------- |
//! | POST   | `/v1/deduce`   | [`crate::deduce::evaluate`]          | [`crate::deduce::Verdict`]  |
//! | POST   | `/v1/solve`    | [`crate::solver::verify`]            | [`crate::schema::FormalVerificationTrace`] |
//! | POST   | `/v1/recheck`  | [`crate::lean::recheck`]             | [`LeanRecheckWire`]         |
//!
//! 8.3b1 shipped the handlers stateless. 8.3b2a (this revision) plumbs
//! a [`KernelServiceState`] in via [`axum::extract::State`]: the state
//! defines the **floor** for [`crate::solver::VerifyOptions`] /
//! [`crate::lean::LeanOptions`] (resolved at boot from `CDS_Z3_PATH` /
//! `CDS_CVC5_PATH` / `CDS_SOLVER_TIMEOUT_MS` / `CDS_KIMINA_URL` /
//! `CDS_LEAN_TIMEOUT_MS`); per-request `options` envelopes still
//! **replace** individual fields on top of that floor (ADR-020 §5).
//! `/healthz` does not extract `State<_>` and therefore stays
//! stateless even though the router carries the state for axum's
//! typestate machinery.
//!
//! ## Error mapping
//!
//! Each pipeline error type ([`crate::deduce::DeduceError`],
//! [`crate::solver::SolverError`], [`crate::lean::LeanError`]) implements
//! [`axum::response::IntoResponse`] in [`crate::service::errors`]; every
//! variant lifts to the [`crate::service::errors::ErrorBody`] envelope at
//! HTTP 422 (parity with the Python harness service per ADR-018 §1).
//!
//! ## Subprocess hygiene
//!
//! The warden's `Command::kill_on_drop(true)` contract (ADR-004) survives
//! the HTTP path because each handler simply awaits
//! [`crate::solver::verify`] / [`crate::lean::recheck`] directly. Tower /
//! axum cancellation drops the handler future, which drops the in-flight
//! `Child` handles and kills any running Z3 / cvc5 / Lean child. SIGTERM-
//! first escalation for the warden's children remains deferred to Task
//! 8.4 (ADR-014 §9 → ADR-015 §8 → ADR-016 §7 → ADR-018 §6 → ADR-019 §11
//! → ADR-020 §6).
//!
//! ## Tracing
//!
//! Each handler is `#[tracing::instrument(...)]`-annotated with a
//! `stage = "<deduce|solve|recheck>"` field so the Workflow harness
//! (Task 8.4) can correlate per-stage events without parsing free-form
//! messages. The router-level `tower_http::trace::TraceLayer` (see
//! [`crate::service::app::build_router`]) emits a span per HTTP request.

use std::collections::BTreeMap;
use std::path::PathBuf;
use std::time::Duration;

use axum::Json;
use axum::extract::State;
use axum::response::Response;
use serde::{Deserialize, Serialize};

use crate::deduce::{Phase0Thresholds, Verdict, evaluate as deduce_evaluate};
use crate::lean::{LeanMessage, LeanOptions, LeanRecheck, LeanSeverity, recheck as lean_recheck};
use crate::schema::{ClinicalTelemetryPayload, FormalVerificationTrace, SmtConstraintMatrix};
use crate::service::state::KernelServiceState;
use crate::solver::{VerifyOptions, verify as solver_verify};

/// HTTP path for the deductive endpoint.
pub const DEDUCE_PATH: &str = "/v1/deduce";

/// HTTP path for the SMT-solver endpoint.
pub const SOLVE_PATH: &str = "/v1/solve";

/// HTTP path for the Lean re-check endpoint.
pub const RECHECK_PATH: &str = "/v1/recheck";

/// Request envelope for [`POST /v1/deduce`](DEDUCE_PATH).
#[derive(Debug, Clone, PartialEq, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DeduceRequest {
    pub payload: ClinicalTelemetryPayload,
    /// Optional Phase 0 threshold band overrides. Falls back to
    /// [`Phase0Thresholds::default`] (clinically-illustrative defaults
    /// per `crate::deduce::rules`) when absent.
    #[serde(default)]
    pub rules: Option<Phase0Thresholds>,
}

/// Request envelope for [`POST /v1/solve`](SOLVE_PATH).
#[derive(Debug, Clone, PartialEq, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SolveRequest {
    pub matrix: SmtConstraintMatrix,
    /// Optional knobs surfaced from [`VerifyOptions`].
    #[serde(default)]
    pub options: Option<SolveOptionsWire>,
}

/// JSON-friendly mirror of [`VerifyOptions`].
///
/// Wire shape uses `timeout_ms` (`u64` milliseconds) instead of a
/// [`Duration`] so the format is unambiguous for polyglot callers; paths
/// are accepted verbatim and the binary is responsible for ensuring they
/// resolve under `$PATH` (Phase 0 convention: `.bin/` is `PATH`-prefixed
/// by the `Justfile`).
#[derive(Debug, Clone, Default, PartialEq, Eq, Deserialize)]
#[serde(deny_unknown_fields, default)]
pub struct SolveOptionsWire {
    pub timeout_ms: Option<u64>,
    pub z3_path: Option<PathBuf>,
    pub cvc5_path: Option<PathBuf>,
}

impl SolveOptionsWire {
    /// Lower the wire knobs onto a [`VerifyOptions`], replacing each
    /// caller-supplied field on top of the `floor` (per-field replace
    /// semantics — ADR-020 §5). `floor` is typically
    /// [`KernelServiceState::verify_options`] but unit tests may pass
    /// [`VerifyOptions::default`] directly.
    #[must_use]
    pub fn into_verify_options(self, floor: VerifyOptions) -> VerifyOptions {
        VerifyOptions {
            timeout: self.timeout_ms.map_or(floor.timeout, Duration::from_millis),
            z3_path: self.z3_path.unwrap_or(floor.z3_path),
            cvc5_path: self.cvc5_path.unwrap_or(floor.cvc5_path),
        }
    }
}

/// Request envelope for [`POST /v1/recheck`](RECHECK_PATH).
#[derive(Debug, Clone, PartialEq, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RecheckRequest {
    pub trace: FormalVerificationTrace,
    /// Optional knobs surfaced from [`LeanOptions`].
    #[serde(default)]
    pub options: Option<RecheckOptionsWire>,
}

/// JSON-friendly mirror of [`LeanOptions`]. See [`SolveOptionsWire`] for
/// the `timeout_ms` rationale.
#[derive(Debug, Clone, Default, PartialEq, Eq, Deserialize)]
#[serde(deny_unknown_fields, default)]
pub struct RecheckOptionsWire {
    pub kimina_url: Option<String>,
    pub timeout_ms: Option<u64>,
    pub custom_id: Option<String>,
    pub extra_headers: Option<BTreeMap<String, String>>,
}

impl RecheckOptionsWire {
    /// Lower the wire knobs onto a [`LeanOptions`], replacing each
    /// caller-supplied field on top of the `floor` (per-field replace
    /// semantics — ADR-020 §5). `floor` is typically
    /// [`KernelServiceState::lean_options`] but unit tests may pass
    /// [`LeanOptions::default`] directly.
    #[must_use]
    pub fn into_lean_options(self, floor: LeanOptions) -> LeanOptions {
        LeanOptions {
            kimina_url: self.kimina_url.unwrap_or(floor.kimina_url),
            timeout: self.timeout_ms.map_or(floor.timeout, Duration::from_millis),
            custom_id: self.custom_id.unwrap_or(floor.custom_id),
            extra_headers: self.extra_headers.unwrap_or(floor.extra_headers),
        }
    }
}

/// Wire-format mirror of [`LeanRecheck`].
///
/// The kernel's internal [`LeanRecheck`] does not derive `Serialize`
/// because the `severity` enum's case (`Info` / `Warning` / `Error`) is
/// not the same as the snake-case wire shape we want for HTTP. Mirroring
/// the struct here keeps the wire form locked at the service boundary
/// without forcing a `serde(rename_all)` layer on the public Lean type.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct LeanRecheckWire {
    pub ok: bool,
    pub custom_id: String,
    pub env_id: Option<String>,
    pub elapsed_ms: u64,
    pub messages: Vec<LeanMessageWire>,
    pub probes: BTreeMap<String, String>,
}

impl From<LeanRecheck> for LeanRecheckWire {
    fn from(value: LeanRecheck) -> Self {
        Self {
            ok: value.ok,
            custom_id: value.custom_id,
            env_id: value.env_id,
            elapsed_ms: value.elapsed_ms,
            messages: value
                .messages
                .into_iter()
                .map(LeanMessageWire::from)
                .collect(),
            probes: value.probes,
        }
    }
}

/// Wire-format mirror of [`LeanMessage`].
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct LeanMessageWire {
    pub severity: LeanSeverityWire,
    pub body: String,
}

impl From<LeanMessage> for LeanMessageWire {
    fn from(value: LeanMessage) -> Self {
        Self {
            severity: value.severity.into(),
            body: value.body,
        }
    }
}

/// Wire-format mirror of [`LeanSeverity`] — snake-case to match Lean's
/// own message-severity nomenclature on the wire.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum LeanSeverityWire {
    Info,
    Warning,
    Error,
}

impl From<LeanSeverity> for LeanSeverityWire {
    fn from(value: LeanSeverity) -> Self {
        match value {
            LeanSeverity::Info => Self::Info,
            LeanSeverity::Warning => Self::Warning,
            LeanSeverity::Error => Self::Error,
        }
    }
}

/// Handler for [`POST /v1/deduce`](DEDUCE_PATH).
///
/// The deductive evaluator is CPU-bound and pure (per `crate::deduce`'s
/// concurrency contract); we delegate it to [`tokio::task::spawn_blocking`]
/// so a long-running payload cannot starve the async runtime that is
/// also driving the warden + Lean network paths.
///
/// `State<KernelServiceState>` is extracted to keep the handler
/// signature uniform across the three pipeline endpoints; the deductive
/// path itself does not consult any field on the state today (no env
/// override applies to the pure-Rust `crate::deduce::evaluate`).
///
/// # Errors
/// Lifts every [`crate::deduce::DeduceError`] variant to HTTP 422 with
/// the standard `{error, detail}` envelope.
#[tracing::instrument(skip(_state, req), fields(stage = "deduce"))]
pub async fn deduce(
    State(_state): State<KernelServiceState>,
    Json(req): Json<DeduceRequest>,
) -> Result<Json<Verdict>, Response> {
    let DeduceRequest { payload, rules } = req;
    let rules = rules.unwrap_or_default();
    let verdict = tokio::task::spawn_blocking(move || deduce_evaluate(&payload, &rules))
        .await
        .map_err(|e| {
            tracing::error!(error = %e, "deduce join error");
            crate::service::errors::error_response(
                axum::http::StatusCode::INTERNAL_SERVER_ERROR,
                "internal",
                e.to_string(),
            )
        })?
        .map_err(axum::response::IntoResponse::into_response)?;
    Ok(Json(verdict))
}

/// Handler for [`POST /v1/solve`](SOLVE_PATH).
///
/// Drives the warden + Z3 + cvc5 pipeline (`crate::solver::verify`).
/// Cancelling the handler future drops the in-flight `Child` handles per
/// ADR-004's `kill_on_drop` contract.
///
/// Per-request `options` envelope replaces individual fields on top of
/// the [`KernelServiceState::verify_options`] floor (ADR-020 §5):
/// `timeout_ms` / `z3_path` / `cvc5_path` each independently override
/// the env-resolved boot value.
///
/// # Errors
/// Lifts every [`crate::solver::SolverError`] variant to HTTP 422 with
/// the standard `{error, detail}` envelope.
#[tracing::instrument(skip(state, req), fields(stage = "solve"))]
pub async fn solve(
    State(state): State<KernelServiceState>,
    Json(req): Json<SolveRequest>,
) -> Result<Json<FormalVerificationTrace>, Response> {
    let opts = req
        .options
        .unwrap_or_default()
        .into_verify_options(state.verify_options.clone());
    let trace = solver_verify(&req.matrix, &opts)
        .await
        .map_err(axum::response::IntoResponse::into_response)?;
    Ok(Json(trace))
}

/// Handler for [`POST /v1/recheck`](RECHECK_PATH).
///
/// Forwards to the Kimina REST bridge (`crate::lean::recheck`); the
/// response is rendered through [`LeanRecheckWire`] so the on-the-wire
/// `severity` field is snake-case.
///
/// Per-request `options` envelope replaces individual fields on top of
/// the [`KernelServiceState::lean_options`] floor (ADR-020 §5):
/// `kimina_url` / `timeout_ms` / `custom_id` / `extra_headers` each
/// independently override the env-resolved boot value.
///
/// # Errors
/// Lifts every [`crate::lean::LeanError`] variant to HTTP 422 with the
/// standard `{error, detail}` envelope.
#[tracing::instrument(skip(state, req), fields(stage = "recheck"))]
pub async fn recheck(
    State(state): State<KernelServiceState>,
    Json(req): Json<RecheckRequest>,
) -> Result<Json<LeanRecheckWire>, Response> {
    let opts = req
        .options
        .unwrap_or_default()
        .into_lean_options(state.lean_options.clone());
    let outcome = lean_recheck(&req.trace, &opts)
        .await
        .map_err(axum::response::IntoResponse::into_response)?;
    Ok(Json(LeanRecheckWire::from(outcome)))
}

#[cfg(test)]
mod tests {
    use super::{
        DeduceRequest, LeanMessageWire, LeanRecheckWire, LeanSeverityWire, RecheckOptionsWire,
        RecheckRequest, SolveOptionsWire, SolveRequest,
    };
    use crate::deduce::{Phase0Thresholds, ThresholdBand};
    use crate::lean::{LeanMessage, LeanOptions, LeanRecheck, LeanSeverity};
    use crate::schema::{
        ClinicalTelemetryPayload, FormalVerificationTrace, LabelledAssertion, SCHEMA_VERSION,
        SmtConstraintMatrix, TelemetrySample, TelemetrySource,
    };
    use crate::solver::VerifyOptions;
    use std::collections::BTreeMap;
    use std::path::PathBuf;
    use std::time::Duration;

    fn payload_with_one_sample() -> ClinicalTelemetryPayload {
        ClinicalTelemetryPayload {
            schema_version: SCHEMA_VERSION.to_string(),
            source: TelemetrySource {
                device_id: "test-dev".to_string(),
                patient_pseudo_id: "pseudo-001".to_string(),
            },
            samples: vec![TelemetrySample {
                wall_clock_utc: "2026-04-29T12:55:00.000000Z".to_string(),
                monotonic_ns: 1,
                vitals: BTreeMap::from([
                    ("heart_rate_bpm".to_string(), 80.0),
                    ("spo2_percent".to_string(), 97.0),
                ]),
                events: vec![],
            }],
        }
    }

    fn unsat_matrix() -> SmtConstraintMatrix {
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

    #[test]
    fn deduce_request_round_trips_through_serde() {
        let req = DeduceRequest {
            payload: payload_with_one_sample(),
            rules: Some(Phase0Thresholds {
                heart_rate_bpm: ThresholdBand {
                    low: 50.0,
                    high: 100.0,
                },
                spo2_percent: ThresholdBand {
                    low: 92.0,
                    high: 100.0,
                },
                systolic_mmhg: ThresholdBand {
                    low: 90.0,
                    high: 140.0,
                },
                diastolic_mmhg: ThresholdBand {
                    low: 60.0,
                    high: 90.0,
                },
                temp_celsius: ThresholdBand {
                    low: 36.0,
                    high: 38.0,
                },
                respiratory_rate_bpm: ThresholdBand {
                    low: 12.0,
                    high: 20.0,
                },
            }),
        };
        let json = serde_json::to_string(&serde_json::json!({
            "payload": req.payload,
            "rules": req.rules,
        }))
        .expect("compose envelope");
        let back: DeduceRequest = serde_json::from_str(&json).expect("decode");
        assert_eq!(back, req);
    }

    #[test]
    fn deduce_request_rejects_unknown_fields() {
        let raw = serde_json::json!({
            "payload": payload_with_one_sample(),
            "rules": null,
            "extra": 1,
        });
        let err = serde_json::from_value::<DeduceRequest>(raw).unwrap_err();
        let msg = err.to_string();
        assert!(
            msg.contains("unknown field"),
            "expected unknown-field error, got: {msg}"
        );
    }

    #[test]
    fn solve_options_wire_lowers_to_verify_options_replacing_floor() {
        let wire = SolveOptionsWire {
            timeout_ms: Some(2_500),
            z3_path: Some(PathBuf::from("/usr/local/bin/z3")),
            cvc5_path: Some(PathBuf::from("/usr/local/bin/cvc5")),
        };
        let floor = VerifyOptions {
            timeout: Duration::from_secs(99),
            z3_path: PathBuf::from("/floor/z3"),
            cvc5_path: PathBuf::from("/floor/cvc5"),
        };
        let opts = wire.into_verify_options(floor);
        assert_eq!(opts.timeout, Duration::from_millis(2_500));
        assert_eq!(opts.z3_path, PathBuf::from("/usr/local/bin/z3"));
        assert_eq!(opts.cvc5_path, PathBuf::from("/usr/local/bin/cvc5"));
    }

    #[test]
    fn solve_options_wire_default_preserves_floor_verbatim() {
        let baseline = VerifyOptions::default();
        let lowered = SolveOptionsWire::default().into_verify_options(baseline.clone());
        assert_eq!(lowered.timeout, baseline.timeout);
        assert_eq!(lowered.z3_path, baseline.z3_path);
        assert_eq!(lowered.cvc5_path, baseline.cvc5_path);
    }

    #[test]
    fn solve_options_wire_partial_override_keeps_other_fields_from_floor() {
        let wire = SolveOptionsWire {
            timeout_ms: Some(7_777),
            z3_path: None,
            cvc5_path: None,
        };
        let floor = VerifyOptions {
            timeout: Duration::from_secs(42),
            z3_path: PathBuf::from("/floor/z3"),
            cvc5_path: PathBuf::from("/floor/cvc5"),
        };
        let opts = wire.into_verify_options(floor);
        assert_eq!(opts.timeout, Duration::from_millis(7_777));
        // Untouched fields fall back to the floor (per-field replace).
        assert_eq!(opts.z3_path, PathBuf::from("/floor/z3"));
        assert_eq!(opts.cvc5_path, PathBuf::from("/floor/cvc5"));
    }

    #[test]
    fn solve_request_accepts_missing_options() {
        let raw = serde_json::json!({"matrix": unsat_matrix()});
        let req: SolveRequest = serde_json::from_value(raw).expect("decode");
        assert!(req.options.is_none());
    }

    #[test]
    fn solve_request_rejects_unknown_options_field() {
        let raw = serde_json::json!({
            "matrix": unsat_matrix(),
            "options": {"timeout_ms": 1, "bogus": true},
        });
        let err = serde_json::from_value::<SolveRequest>(raw).unwrap_err();
        assert!(err.to_string().contains("unknown field"));
    }

    #[test]
    fn recheck_options_wire_lowers_to_lean_options_replacing_floor() {
        let mut headers = BTreeMap::new();
        headers.insert("x-test".to_string(), "ok".to_string());
        let wire = RecheckOptionsWire {
            kimina_url: Some("http://kimina.local:9000".to_string()),
            timeout_ms: Some(7_500),
            custom_id: Some("cid-42".to_string()),
            extra_headers: Some(headers.clone()),
        };
        let mut floor_headers = BTreeMap::new();
        floor_headers.insert("x-floor".to_string(), "v".to_string());
        let floor = LeanOptions {
            kimina_url: "http://floor.local".to_string(),
            timeout: Duration::from_secs(99),
            custom_id: "floor-cid".to_string(),
            extra_headers: floor_headers,
        };
        let opts = wire.into_lean_options(floor);
        assert_eq!(opts.kimina_url, "http://kimina.local:9000");
        assert_eq!(opts.timeout, Duration::from_millis(7_500));
        assert_eq!(opts.custom_id, "cid-42");
        assert_eq!(opts.extra_headers, headers);
    }

    #[test]
    fn recheck_options_wire_default_preserves_floor_verbatim() {
        let baseline = LeanOptions::default();
        let lowered = RecheckOptionsWire::default().into_lean_options(baseline.clone());
        assert_eq!(lowered.kimina_url, baseline.kimina_url);
        assert_eq!(lowered.timeout, baseline.timeout);
        assert_eq!(lowered.custom_id, baseline.custom_id);
        assert_eq!(lowered.extra_headers, baseline.extra_headers);
    }

    #[test]
    fn recheck_options_wire_partial_override_keeps_other_fields_from_floor() {
        let wire = RecheckOptionsWire {
            kimina_url: Some("http://overridden:1234".to_string()),
            timeout_ms: None,
            custom_id: None,
            extra_headers: None,
        };
        let mut headers = BTreeMap::new();
        headers.insert("x-floor".to_string(), "v".to_string());
        let floor = LeanOptions {
            kimina_url: "http://floor.local".to_string(),
            timeout: Duration::from_secs(42),
            custom_id: "floor-cid".to_string(),
            extra_headers: headers.clone(),
        };
        let opts = wire.into_lean_options(floor);
        assert_eq!(opts.kimina_url, "http://overridden:1234");
        assert_eq!(opts.timeout, Duration::from_secs(42));
        assert_eq!(opts.custom_id, "floor-cid");
        assert_eq!(opts.extra_headers, headers);
    }

    #[test]
    fn recheck_request_accepts_minimal_envelope() {
        let trace = FormalVerificationTrace {
            schema_version: SCHEMA_VERSION.to_string(),
            sat: true,
            muc: vec![],
            alethe_proof: None,
        };
        let raw = serde_json::json!({"trace": trace});
        let req: RecheckRequest = serde_json::from_value(raw).expect("decode");
        assert!(req.trace.sat);
        assert!(req.options.is_none());
    }

    #[test]
    fn lean_recheck_wire_serializes_severity_as_snake_case() {
        let outcome = LeanRecheck {
            ok: true,
            custom_id: "cid-7".to_string(),
            env_id: Some("env-1".to_string()),
            elapsed_ms: 42,
            messages: vec![
                LeanMessage {
                    severity: LeanSeverity::Info,
                    body: "info".to_string(),
                },
                LeanMessage {
                    severity: LeanSeverity::Warning,
                    body: "warn".to_string(),
                },
                LeanMessage {
                    severity: LeanSeverity::Error,
                    body: "err".to_string(),
                },
            ],
            probes: BTreeMap::from([("byte_len".to_string(), "12".to_string())]),
        };
        let wire = LeanRecheckWire::from(outcome);
        let json = serde_json::to_string(&wire).expect("serialize");
        assert!(json.contains(r#""severity":"info""#));
        assert!(json.contains(r#""severity":"warning""#));
        assert!(json.contains(r#""severity":"error""#));
        assert!(json.contains(r#""ok":true"#));
        assert!(json.contains(r#""custom_id":"cid-7""#));
    }

    #[test]
    fn lean_severity_wire_round_trips_each_variant() {
        let pairs = [
            (LeanSeverity::Info, LeanSeverityWire::Info, "info"),
            (LeanSeverity::Warning, LeanSeverityWire::Warning, "warning"),
            (LeanSeverity::Error, LeanSeverityWire::Error, "error"),
        ];
        for (src, expected_wire, expected_token) in pairs {
            let wire = LeanSeverityWire::from(src);
            assert_eq!(wire, expected_wire);
            let json = serde_json::to_string(&wire).expect("serialize");
            assert_eq!(json, format!("\"{expected_token}\""));
        }
    }

    #[test]
    fn lean_message_wire_lifts_from_lean_message_verbatim() {
        let m = LeanMessage {
            severity: LeanSeverity::Info,
            body: "[probe] byte_len 12".to_string(),
        };
        let w = LeanMessageWire::from(m.clone());
        assert_eq!(w.severity, LeanSeverityWire::Info);
        assert_eq!(w.body, m.body);
    }
}

#[cfg(test)]
mod runtime_tests {
    //! End-to-end handler tests through the axum router via
    //! `tower::ServiceExt::oneshot`. Exercises request-body decoding +
    //! handler logic + `IntoResponse` lifts in one shot. Subprocess-
    //! backed paths (real Z3 / Kimina success) are deferred to Task
    //! 8.3b2's daprd-driven cargo integration tests; these tests cover
    //! only error-paths that complete without a real subprocess /
    //! network success.

    use crate::deduce::Verdict;
    use crate::schema::{
        ClinicalTelemetryPayload, FormalVerificationTrace, LabelledAssertion, SCHEMA_VERSION,
        SmtConstraintMatrix, TelemetrySample, TelemetrySource,
    };
    use crate::service::app::build_router;
    use crate::service::handlers::{DEDUCE_PATH, RECHECK_PATH, SOLVE_PATH};
    use crate::service::state::KernelServiceState;
    use axum::body::{Body, to_bytes};
    use axum::http::{Method, Request, StatusCode, header};
    use tower::util::ServiceExt;

    fn json_post(path: &str, body: &serde_json::Value) -> Request<Body> {
        Request::builder()
            .method(Method::POST)
            .uri(path)
            .header(header::CONTENT_TYPE, "application/json")
            .body(Body::from(serde_json::to_vec(body).expect("encode body")))
            .expect("request")
    }

    async fn collect_json(response: axum::response::Response) -> (StatusCode, serde_json::Value) {
        let status = response.status();
        let bytes = to_bytes(response.into_body(), 512 * 1024)
            .await
            .expect("collect body");
        let parsed: serde_json::Value = serde_json::from_slice(&bytes).expect("json body");
        (status, parsed)
    }

    fn payload(samples: Vec<TelemetrySample>) -> ClinicalTelemetryPayload {
        ClinicalTelemetryPayload {
            schema_version: SCHEMA_VERSION.to_string(),
            source: TelemetrySource {
                device_id: "smoke-dev".to_string(),
                patient_pseudo_id: "smoke-pseudo".to_string(),
            },
            samples,
        }
    }

    fn sample(t: u64, vs: &[(&str, f64)]) -> TelemetrySample {
        TelemetrySample {
            wall_clock_utc: "2026-04-29T12:55:00.000000Z".to_string(),
            monotonic_ns: t,
            vitals: vs.iter().map(|(k, v)| ((*k).to_string(), *v)).collect(),
            events: vec![],
        }
    }

    #[tokio::test]
    async fn deduce_handler_happy_path_returns_verdict() {
        let request_body = serde_json::json!({
            "payload": payload(vec![
                sample(1, &[("heart_rate_bpm", 80.0), ("spo2_percent", 97.0)]),
                sample(2, &[("heart_rate_bpm", 82.0), ("spo2_percent", 96.0)]),
            ]),
        });
        let response = build_router(KernelServiceState::default())
            .oneshot(json_post(DEDUCE_PATH, &request_body))
            .await
            .expect("router response");
        let (status, body) = collect_json(response).await;
        assert_eq!(status, StatusCode::OK);
        // Decode through the typed Verdict to pin the wire shape.
        let verdict: Verdict =
            serde_json::from_value(body).expect("decode Verdict from response body");
        assert_eq!(verdict.samples_processed, 2);
        assert!(
            verdict.octagon_bounds.contains_key("heart_rate_bpm"),
            "octagon_bounds missing canonical vital: keys={:?}",
            verdict.octagon_bounds.keys().collect::<Vec<_>>()
        );
    }

    #[tokio::test]
    async fn deduce_handler_lifts_non_canonical_vital_to_422() {
        let request_body = serde_json::json!({
            "payload": payload(vec![sample(1, &[("glucose_mgdl", 5.5)])]),
        });
        let response = build_router(KernelServiceState::default())
            .oneshot(json_post(DEDUCE_PATH, &request_body))
            .await
            .expect("router response");
        let (status, body) = collect_json(response).await;
        assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
        assert_eq!(body["error"], "non_canonical_vital");
        assert!(
            body["detail"]
                .as_str()
                .expect("detail")
                .contains("glucose_mgdl"),
            "detail was: {body}"
        );
    }

    // NOTE: there is no end-to-end runtime test for
    // `DeduceError::NonFiniteReading` because `serde_json` (correctly)
    // refuses to round-trip non-finite floats — `f64::NAN`/`±∞` cannot be
    // represented in strict JSON. The variant is covered by
    // `service::errors::tests::deduce_error_kinds_are_stable` (kind tag)
    // and by the deduce-module unit test
    // `nan_reading_is_rejected_at_boundary`. The Dapr-driven cargo
    // integration test in 8.3b2 does not need to revisit this either:
    // every payload that crosses the wire is finite by construction.

    fn unsat_matrix_with_provenance() -> SmtConstraintMatrix {
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
    async fn solve_handler_lifts_missing_z3_to_422_warden() {
        let request_body = serde_json::json!({
            "matrix": unsat_matrix_with_provenance(),
            "options": {
                "timeout_ms": 5_000,
                "z3_path": "/nonexistent/path/to/z3",
                "cvc5_path": "/nonexistent/path/to/cvc5",
            },
        });
        let response = build_router(KernelServiceState::default())
            .oneshot(json_post(SOLVE_PATH, &request_body))
            .await
            .expect("router response");
        let (status, body) = collect_json(response).await;
        assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
        assert_eq!(body["error"], "warden");
        let detail = body["detail"].as_str().expect("detail");
        assert!(
            detail.contains("/nonexistent/path/to/z3"),
            "detail was: {detail}"
        );
    }

    #[tokio::test]
    async fn recheck_handler_lifts_sat_trace_to_422_no_proof() {
        let trace = FormalVerificationTrace {
            schema_version: SCHEMA_VERSION.to_string(),
            sat: true,
            muc: vec![],
            alethe_proof: None,
        };
        let request_body = serde_json::json!({"trace": trace});
        let response = build_router(KernelServiceState::default())
            .oneshot(json_post(RECHECK_PATH, &request_body))
            .await
            .expect("router response");
        let (status, body) = collect_json(response).await;
        assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
        assert_eq!(body["error"], "lean_no_proof");
        let detail = body["detail"].as_str().expect("detail");
        assert!(detail.contains("trace.sat=true"), "detail was: {detail}");
    }

    #[tokio::test]
    async fn recheck_handler_lifts_unbound_url_to_422_transport() {
        let trace = FormalVerificationTrace {
            schema_version: SCHEMA_VERSION.to_string(),
            sat: false,
            muc: vec!["atom:contradictory-bound:0-4".to_string()],
            alethe_proof: Some("(proof (assume clause_000) :rule resolution)".to_string()),
        };
        let request_body = serde_json::json!({
            "trace": trace,
            "options": {
                // Port 1 is the canonical "never bound" port; a connect
                // attempt fails fast with a transport error.
                "kimina_url": "http://127.0.0.1:1",
                "timeout_ms": 500,
            },
        });
        let response = build_router(KernelServiceState::default())
            .oneshot(json_post(RECHECK_PATH, &request_body))
            .await
            .expect("router response");
        let (status, body) = collect_json(response).await;
        assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
        assert_eq!(body["error"], "lean_transport");
        let detail = body["detail"].as_str().expect("detail");
        assert!(detail.contains("127.0.0.1:1"), "detail was: {detail}");
    }
}
