//! Phase 0 kernel-service axum application factory.
//!
//! Task 8.3a (this layer) ships only the foundation:
//!
//! - [`SERVICE_APP_ID`] — Dapr `--app-id` for the kernel sidecar.
//! - [`HEALTHZ_PATH`] — liveness probe.
//! - [`KernelHealthz`] — `{status, kernel_id, phase, schema_version}`
//!   response shape; `kernel_id` mirrors [`crate::KERNEL_ID`] and
//!   `schema_version` mirrors [`crate::schema::SCHEMA_VERSION`] so
//!   polyglot callers can pin both invariants in one round-trip.
//! - [`build_router`] — assembles the axum [`Router`] with the
//!   `tower_http::trace::TraceLayer` middleware so future endpoints
//!   inherit per-request tracing spans (Task 8.4 trace plumbing).
//!
//! Task 8.3b will extend [`build_router`] with the `/v1/deduce`,
//! `/v1/solve`, `/v1/recheck` handlers, each lifting domain errors to
//! the [`crate::service::errors::ErrorBody`] envelope.

use axum::Json;
use axum::Router;
use axum::routing::get;
use serde::{Deserialize, Serialize};
use tower_http::trace::TraceLayer;

use crate::schema::SCHEMA_VERSION;
use crate::{KERNEL_ID, PHASE};

/// Dapr `--app-id` for the kernel sidecar. Matches the value advertised
/// by the Justfile `rs-service-dapr` recipe so callers can bake the
/// invocation route at compile time.
pub const SERVICE_APP_ID: &str = "cds-kernel";

/// Liveness probe path. Used both by the standalone HTTP smoke test
/// and by the Dapr sidecar app-readiness probe.
pub const HEALTHZ_PATH: &str = "/healthz";

/// Liveness response. Field order matches the Python harness service's
/// `_Healthz` response so a polyglot smoke client can decode either
/// without reshaping (ADR-017 §2). Owns its strings (instead of
/// borrowing the static [`crate::KERNEL_ID`] / [`crate::schema::SCHEMA_VERSION`])
/// so callers can also `serde_json::from_slice` the JSON envelope back
/// into a `KernelHealthz` without lifetime gymnastics.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct KernelHealthz {
    pub status: String,
    pub kernel_id: String,
    pub phase: u8,
    pub schema_version: String,
}

impl Default for KernelHealthz {
    fn default() -> Self {
        Self {
            status: "ok".to_string(),
            kernel_id: KERNEL_ID.to_string(),
            phase: PHASE,
            schema_version: SCHEMA_VERSION.to_string(),
        }
    }
}

/// Construct the Phase 0 kernel-service [`Router`].
///
/// One instance per process; no globals beyond environment-driven host
/// / port (resolved by the binary, not this factory). The
/// [`TraceLayer`] is wired here so Task 8.3b's `/v1/*` handlers and
/// Task 8.4's Workflow events inherit a single tracing convention.
pub fn build_router() -> Router {
    Router::new()
        .route(HEALTHZ_PATH, get(healthz))
        .layer(TraceLayer::new_for_http())
}

#[allow(clippy::unused_async)] // axum handlers must be async even when pure.
async fn healthz() -> Json<KernelHealthz> {
    Json(KernelHealthz::default())
}

#[cfg(test)]
mod tests {
    use super::{HEALTHZ_PATH, KernelHealthz, SERVICE_APP_ID, build_router};
    use crate::schema::SCHEMA_VERSION;
    use crate::{KERNEL_ID, PHASE};
    use axum::body::{Body, to_bytes};
    use axum::http::{Request, StatusCode};
    use tower::util::ServiceExt;

    #[test]
    fn service_app_id_is_pinned_to_dapr_app_id() {
        assert_eq!(SERVICE_APP_ID, "cds-kernel");
    }

    #[test]
    fn healthz_response_pins_the_kernel_invariants() {
        let body = KernelHealthz::default();
        assert_eq!(body.status, "ok");
        assert_eq!(body.kernel_id.as_str(), KERNEL_ID);
        assert_eq!(body.phase, PHASE);
        assert_eq!(body.schema_version.as_str(), SCHEMA_VERSION);
    }

    #[test]
    fn kernel_healthz_serializes_with_a_stable_field_order() {
        let body = KernelHealthz::default();
        let json = serde_json::to_string(&body).expect("serialize");
        assert_eq!(
            json,
            format!(
                "{{\"status\":\"ok\",\"kernel_id\":\"{KERNEL_ID}\",\"phase\":{PHASE},\"schema_version\":\"{SCHEMA_VERSION}\"}}"
            )
        );
    }

    #[tokio::test]
    async fn router_serves_healthz_with_default_body() {
        let app = build_router();
        let response = app
            .oneshot(
                Request::builder()
                    .uri(HEALTHZ_PATH)
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("router response");
        assert_eq!(response.status(), StatusCode::OK);
        let bytes = to_bytes(response.into_body(), 64 * 1024)
            .await
            .expect("collect body");
        let body: KernelHealthz = serde_json::from_slice(&bytes).expect("decode body");
        assert_eq!(body, KernelHealthz::default());
    }

    #[tokio::test]
    async fn router_returns_404_for_unknown_routes() {
        let app = build_router();
        let response = app
            .oneshot(
                Request::builder()
                    .uri("/does-not-exist")
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("router response");
        assert_eq!(response.status(), StatusCode::NOT_FOUND);
    }
}
