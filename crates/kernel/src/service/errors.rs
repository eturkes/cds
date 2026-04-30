//! Phase 0 kernel-service error envelope.
//!
//! Mirrors the Python harness service's `{error, detail}` HTTP 422
//! envelope (ADR-017 §2 / app.py exception handlers) so polyglot
//! callers see one wire shape across both services. Task 8.3a shipped
//! the response helper; Task 8.3b1 (this module) ships the three
//! pipeline-specific [`IntoResponse`] impls — [`crate::deduce::DeduceError`],
//! [`crate::solver::SolverError`], [`crate::lean::LeanError`] — that
//! produce the same envelope. Each handler in
//! [`crate::service::handlers`] uses these impls via `?` so domain
//! errors lift transparently to HTTP 422.

use axum::Json;
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use serde::{Deserialize, Serialize};

use crate::deduce::DeduceError;
use crate::lean::LeanError;
use crate::solver::SolverError;

/// On-the-wire error envelope: `{"error": "...", "detail": "..."}`.
///
/// Matches the Python harness service's `JSONResponse({"error", "detail"})`
/// shape exactly so a single client decoder handles both backends.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ErrorBody {
    pub error: String,
    pub detail: String,
}

impl ErrorBody {
    /// Build an [`ErrorBody`] from any string-like inputs.
    pub fn new(error: impl Into<String>, detail: impl Into<String>) -> Self {
        Self {
            error: error.into(),
            detail: detail.into(),
        }
    }
}

impl IntoResponse for ErrorBody {
    fn into_response(self) -> Response {
        // Default lift: HTTP 422. Per-pipeline `IntoResponse` impls below
        // funnel through this same shape so every domain error is
        // wire-identical to the harness side.
        (StatusCode::UNPROCESSABLE_ENTITY, Json(self)).into_response()
    }
}

/// Build a `(status, Json<ErrorBody>)` response in one call. Useful for
/// non-422 statuses (e.g., 500) without rebuilding the envelope.
#[must_use]
pub fn error_response(status: StatusCode, error: &str, detail: impl Into<String>) -> Response {
    (status, Json(ErrorBody::new(error, detail))).into_response()
}

/// Stable error-kind tag for [`DeduceError`] on the wire.
fn deduce_error_kind(err: &DeduceError) -> &'static str {
    match err {
        DeduceError::NonCanonicalVital(_) => "non_canonical_vital",
        DeduceError::NonFiniteReading { .. } => "non_finite_reading",
        DeduceError::Domain(_) => "domain_error",
    }
}

/// Stable error-kind tag for [`SolverError`] on the wire.
fn solver_error_kind(err: &SolverError) -> &'static str {
    match err {
        SolverError::Warden(_) => "warden",
        SolverError::UnparseableOutput(_) => "solver_unparseable_output",
        SolverError::Z3Error(_) => "z3_error",
        SolverError::Cvc5Error(_) => "cvc5_error",
        SolverError::UnknownVerdict => "solver_unknown_verdict",
        SolverError::SolverDisagreement { .. } => "solver_disagreement",
    }
}

/// Stable error-kind tag for [`LeanError`] on the wire.
fn lean_error_kind(err: &LeanError) -> &'static str {
    match err {
        LeanError::NoProof { .. } => "lean_no_proof",
        LeanError::Transport { .. } => "lean_transport",
        LeanError::ServerError { .. } => "lean_server_error",
        LeanError::DecodeFailed { .. } => "lean_decode_failed",
    }
}

impl IntoResponse for DeduceError {
    fn into_response(self) -> Response {
        let kind = deduce_error_kind(&self);
        ErrorBody::new(kind, self.to_string()).into_response()
    }
}

impl IntoResponse for SolverError {
    fn into_response(self) -> Response {
        let kind = solver_error_kind(&self);
        ErrorBody::new(kind, self.to_string()).into_response()
    }
}

impl IntoResponse for LeanError {
    fn into_response(self) -> Response {
        let kind = lean_error_kind(&self);
        ErrorBody::new(kind, self.to_string()).into_response()
    }
}

#[cfg(test)]
mod tests {
    use super::{ErrorBody, deduce_error_kind, error_response, lean_error_kind, solver_error_kind};
    use crate::deduce::{DeduceError, DomainError};
    use crate::lean::LeanError;
    use crate::solver::{SolverError, Verdict, WardenError};
    use axum::body::to_bytes;
    use axum::http::StatusCode;
    use axum::response::IntoResponse;

    async fn extract_body(response: axum::response::Response) -> (StatusCode, serde_json::Value) {
        let status = response.status();
        let bytes = to_bytes(response.into_body(), 64 * 1024)
            .await
            .expect("collect body");
        let parsed: serde_json::Value = serde_json::from_slice(&bytes).expect("json body");
        (status, parsed)
    }

    #[test]
    fn error_body_roundtrips_through_serde_json() {
        let body = ErrorBody::new("kind", "explanation");
        let json = serde_json::to_string(&body).expect("serialize");
        assert_eq!(json, r#"{"error":"kind","detail":"explanation"}"#);
        let parsed: ErrorBody = serde_json::from_str(&json).expect("deserialize");
        assert_eq!(parsed, body);
    }

    #[tokio::test]
    async fn error_body_into_response_yields_422_with_envelope() {
        let response = ErrorBody::new("ingest_error", "row 3 missing 'source'").into_response();
        let (status, json) = extract_body(response).await;
        assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
        assert_eq!(json["error"], "ingest_error");
        assert_eq!(json["detail"], "row 3 missing 'source'");
    }

    #[tokio::test]
    async fn error_response_honours_explicit_status() {
        let response = error_response(StatusCode::INTERNAL_SERVER_ERROR, "warden", "spawn failed");
        let (status, json) = extract_body(response).await;
        assert_eq!(status, StatusCode::INTERNAL_SERVER_ERROR);
        assert_eq!(json["error"], "warden");
        assert_eq!(json["detail"], "spawn failed");
    }

    #[test]
    fn deduce_error_kinds_are_stable() {
        assert_eq!(
            deduce_error_kind(&DeduceError::NonCanonicalVital("glucose_mgdl".to_string())),
            "non_canonical_vital"
        );
        assert_eq!(
            deduce_error_kind(&DeduceError::NonFiniteReading {
                name: "heart_rate_bpm".to_string(),
                value: f64::NAN
            }),
            "non_finite_reading"
        );
        assert_eq!(
            deduce_error_kind(&DeduceError::Domain(DomainError::NonFinite(f64::NAN))),
            "domain_error"
        );
    }

    #[tokio::test]
    async fn deduce_error_into_response_lifts_to_422_envelope() {
        let response = DeduceError::NonCanonicalVital("glucose_mgdl".to_string()).into_response();
        let (status, json) = extract_body(response).await;
        assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
        assert_eq!(json["error"], "non_canonical_vital");
        assert!(
            json["detail"]
                .as_str()
                .expect("detail")
                .contains("glucose_mgdl")
        );
    }

    #[test]
    fn solver_error_kinds_cover_every_variant() {
        let cases: &[(SolverError, &str)] = &[
            (
                SolverError::Warden(WardenError::Spawn {
                    bin: "/nope".to_string(),
                    source: std::io::Error::other("missing"),
                }),
                "warden",
            ),
            (
                SolverError::UnparseableOutput("garbage".to_string()),
                "solver_unparseable_output",
            ),
            (SolverError::Z3Error("oops".to_string()), "z3_error"),
            (SolverError::Cvc5Error("oops".to_string()), "cvc5_error"),
            (SolverError::UnknownVerdict, "solver_unknown_verdict"),
            (
                SolverError::SolverDisagreement {
                    z3: Verdict::Sat,
                    cvc5: Verdict::Unsat,
                },
                "solver_disagreement",
            ),
        ];
        for (err, expected) in cases {
            assert_eq!(solver_error_kind(err), *expected, "for variant {err:?}");
        }
    }

    #[tokio::test]
    async fn solver_error_into_response_carries_warden_detail() {
        let response = SolverError::Warden(WardenError::Spawn {
            bin: "/nonexistent/z3".to_string(),
            source: std::io::Error::other("spawn failed"),
        })
        .into_response();
        let (status, json) = extract_body(response).await;
        assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
        assert_eq!(json["error"], "warden");
        let detail = json["detail"].as_str().expect("detail");
        assert!(detail.contains("/nonexistent/z3"), "detail was: {detail}");
    }

    #[test]
    fn lean_error_kinds_cover_every_variant() {
        let cases: &[(LeanError, &str)] = &[
            (LeanError::NoProof { sat: true }, "lean_no_proof"),
            (
                LeanError::Transport {
                    url: "http://x".to_string(),
                    detail: "down".to_string(),
                },
                "lean_transport",
            ),
            (
                LeanError::ServerError {
                    url: "http://x".to_string(),
                    status: 500,
                    body: "boom".to_string(),
                },
                "lean_server_error",
            ),
            (
                LeanError::DecodeFailed {
                    reason: "bad json".to_string(),
                },
                "lean_decode_failed",
            ),
        ];
        for (err, expected) in cases {
            assert_eq!(lean_error_kind(err), *expected, "for variant {err:?}");
        }
    }

    #[tokio::test]
    async fn lean_error_into_response_lifts_no_proof_to_422() {
        let response = LeanError::NoProof { sat: true }.into_response();
        let (status, json) = extract_body(response).await;
        assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
        assert_eq!(json["error"], "lean_no_proof");
        let detail = json["detail"].as_str().expect("detail");
        assert!(detail.contains("trace.sat=true"), "detail was: {detail}");
    }
}
