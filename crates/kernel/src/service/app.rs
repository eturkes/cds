//! Phase 0 kernel-service axum application factory.
//!
//! Task 8.3a shipped the foundation; Task 8.3b1 wired the three pipeline
//! endpoints onto the same [`Router`]; Task 8.3b2a (this module's current
//! revision) plumbs a [`KernelServiceState`] through the pipeline routes
//! while keeping `/healthz` stateless.
//!
//! - [`SERVICE_APP_ID`] — Dapr `--app-id` for the kernel sidecar.
//! - [`HEALTHZ_PATH`] — liveness probe.
//! - [`KernelHealthz`] — `{status, kernel_id, phase, schema_version}`
//!   response shape; `kernel_id` mirrors [`crate::KERNEL_ID`] and
//!   `schema_version` mirrors [`crate::schema::SCHEMA_VERSION`] so
//!   polyglot callers can pin both invariants in one round-trip.
//! - [`build_router`] — assembles the axum [`Router<()>`] with the
//!   `tower_http::trace::TraceLayer` middleware so every endpoint
//!   inherits per-request tracing spans (Task 8.4 trace plumbing).
//!   Takes a [`KernelServiceState`] which is `.with_state(...)`-merged
//!   into the pipeline routes; `/healthz` does not extract `State<_>`,
//!   so it remains stateless even though the router carries the state
//!   handle for axum's typestate machinery.
//!
//! The pipeline endpoints themselves live in
//! [`crate::service::handlers`]: `/v1/deduce`, `/v1/solve`, `/v1/recheck`.
//! The deduce daprd smoke ships in Task 8.3b2a; the solve / recheck
//! daprd smokes ship in Task 8.3b2b (ADR-020 §3).

use axum::Json;
use axum::Router;
use axum::routing::{get, post};
use serde::{Deserialize, Serialize};
use tower_http::trace::TraceLayer;

use crate::schema::SCHEMA_VERSION;
use crate::service::handlers;
use crate::service::state::KernelServiceState;
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
/// One instance per process; no globals beyond the
/// environment-driven host / port (resolved by the binary, not this
/// factory) and the [`KernelServiceState`] passed in. The [`TraceLayer`]
/// is wired here so the pipeline handlers and Task 8.4's Workflow
/// events inherit a single tracing convention.
///
/// The returned [`Router<()>`] has had its [`KernelServiceState`] floor
/// merged in via `.with_state(...)`; the binary can call
/// [`axum::serve`] on it directly without further state plumbing.
pub fn build_router(state: KernelServiceState) -> Router {
    Router::new()
        .route(HEALTHZ_PATH, get(healthz))
        .route(handlers::DEDUCE_PATH, post(handlers::deduce))
        .route(handlers::SOLVE_PATH, post(handlers::solve))
        .route(handlers::RECHECK_PATH, post(handlers::recheck))
        .layer(TraceLayer::new_for_http())
        .with_state(state)
}

#[allow(clippy::unused_async)] // axum handlers must be async even when pure.
async fn healthz() -> Json<KernelHealthz> {
    Json(KernelHealthz::default())
}

#[cfg(test)]
mod tests {
    use super::{HEALTHZ_PATH, KernelHealthz, SERVICE_APP_ID, build_router};
    use crate::schema::SCHEMA_VERSION;
    use crate::service::handlers::{DEDUCE_PATH, RECHECK_PATH, SOLVE_PATH};
    use crate::service::state::KernelServiceState;
    use crate::{KERNEL_ID, PHASE};
    use axum::body::{Body, to_bytes};
    use axum::http::{Method, Request, StatusCode};
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
        let app = build_router(KernelServiceState::default());
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
        let app = build_router(KernelServiceState::default());
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

    #[tokio::test]
    async fn pipeline_routes_reject_get() {
        for path in [DEDUCE_PATH, SOLVE_PATH, RECHECK_PATH] {
            let app = build_router(KernelServiceState::default());
            let response = app
                .oneshot(
                    Request::builder()
                        .method(Method::GET)
                        .uri(path)
                        .body(Body::empty())
                        .expect("request"),
                )
                .await
                .expect("router response");
            assert_eq!(
                response.status(),
                StatusCode::METHOD_NOT_ALLOWED,
                "path {path} returned {}",
                response.status()
            );
        }
    }
}
