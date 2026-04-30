//! Phase 0 kernel-service error envelope.
//!
//! Mirrors the Python harness service's `{error, detail}` HTTP 422
//! envelope (ADR-017 §2 / app.py exception handlers) so polyglot
//! callers see one wire shape across both services. Task 8.3a only
//! ships the response helper; Task 8.3b will wire pipeline-specific
//! `IntoResponse` impls (`DeduceError`, `SolverError`, `LeanError`)
//! that produce the same envelope.

use axum::Json;
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use serde::{Deserialize, Serialize};

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
        // Default lift: HTTP 422. Task 8.3b's per-pipeline `IntoResponse`
        // impls may return other statuses for their own error variants.
        (StatusCode::UNPROCESSABLE_ENTITY, Json(self)).into_response()
    }
}

/// Build a `(status, Json<ErrorBody>)` response in one call. Useful
/// when Task 8.3b wants a non-422 status (e.g., 500) without rebuilding
/// the envelope.
#[must_use]
pub fn error_response(status: StatusCode, error: &str, detail: impl Into<String>) -> Response {
    (status, Json(ErrorBody::new(error, detail))).into_response()
}

#[cfg(test)]
mod tests {
    use super::{ErrorBody, error_response};
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
}
