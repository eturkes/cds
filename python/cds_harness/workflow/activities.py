"""Five Phase 0 Workflow activities — thin httpx-over-daprd wrappers.

Each activity is registered with the :class:`dapr.ext.workflow.WorkflowRuntime`
and called from :func:`cds_harness.workflow.pipeline.pipeline_workflow`. The
runtime supplies a :class:`dapr.ext.workflow.WorkflowActivityContext` and a
JSON-serialisable input dict; the activity issues a single
``POST /v1.0/invoke/<app-id>/method/<path>`` against the host daprd's HTTP
port and returns a JSON-serialisable result.

Per ADR-017 §5: service-invocation calls stay on plain :mod:`httpx`
(constraint **C6** is satisfied by JSON-over-TCP without typed bindings).
ADR-021 §6 reverses the deferral of the Dapr Python SDK only for the
``WorkflowRuntime`` + ``@workflow`` / ``@activity`` decorator surfaces in
:mod:`cds_harness.workflow.pipeline`; activity bodies remain SDK-free.

Per ADR-021 §3 the aggregated envelope is in-band JSON, so each activity
returns a plain :class:`dict` — the workflow accumulates them and the
:class:`dapr.ext.workflow.DaprWorkflowClient` deserialises the final
return value through the runtime's standard serialiser.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Final

import httpx
from dapr.ext.workflow import WorkflowActivityContext, WorkflowRuntime

# ---------------------------------------------------------------------------
# Constants

WORKFLOW_APP_ID: Final[str] = "cds-workflow"
HARNESS_APP_ID: Final[str] = "cds-harness"
KERNEL_APP_ID: Final[str] = "cds-kernel"

INGEST_PATH: Final[str] = "/v1/ingest"
TRANSLATE_PATH: Final[str] = "/v1/translate"
DEDUCE_PATH: Final[str] = "/v1/deduce"
SOLVE_PATH: Final[str] = "/v1/solve"
RECHECK_PATH: Final[str] = "/v1/recheck"

# Phase 0 wall-clock budgets — solver matches `tests/solver_smoke.rs`'s
# 10 s ceiling (bumped to 30 s on the wire to give daprd + sidecar
# bring-up some headroom on a cold start), recheck matches
# `tests/lean_smoke.rs`'s 120 s. Operators can override per-invocation
# through the `solve_timeout_ms` / `recheck_timeout_ms` PipelineInput
# fields.
DEFAULT_SOLVE_TIMEOUT_MS: Final[int] = 30_000
DEFAULT_RECHECK_TIMEOUT_MS: Final[int] = 120_000

# httpx wall-clocks for the activity itself. The kernel's solve / recheck
# budgets already wrap the warden + Kimina round-trips; the outer httpx
# timeout adds a generous slack so a cold daprd does not flake the gate.
_INGEST_TIMEOUT_S: Final[float] = 30.0
_TRANSLATE_TIMEOUT_S: Final[float] = 30.0
_DEDUCE_TIMEOUT_S: Final[float] = 30.0
_SOLVE_HTTP_TIMEOUT_S: Final[float] = 60.0
_RECHECK_HTTP_TIMEOUT_S: Final[float] = 180.0

_DAPR_HTTP_PORT_ENV: Final[str] = "DAPR_HTTP_PORT"

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors


class WorkflowActivityError(RuntimeError):
    """Raised when a sidecar invocation does not return 2xx.

    The Dapr Workflow runtime treats raised exceptions as activity
    failures and applies its retry policy (Phase 0 default — no retry;
    Phase 1+ will surface the policy on the
    :func:`dapr.ext.workflow.WorkflowRuntime.register_activity` call).
    """


# ---------------------------------------------------------------------------
# Helpers


def _dapr_invoke_url(app_id: str, path: str) -> str:
    raw = os.environ.get(_DAPR_HTTP_PORT_ENV)
    if not raw:
        raise WorkflowActivityError(
            f"{_DAPR_HTTP_PORT_ENV} unset — activity must run under `dapr run` "
            "so daprd can route service-invocation calls."
        )
    try:
        port = int(raw)
    except ValueError as exc:
        raise WorkflowActivityError(
            f"{_DAPR_HTTP_PORT_ENV}={raw!r} is not an integer"
        ) from exc
    return f"http://127.0.0.1:{port}/v1.0/invoke/{app_id}/method{path}"


def _post_json(
    *,
    stage: str,
    app_id: str,
    path: str,
    body: dict[str, Any],
    timeout_s: float,
) -> dict[str, Any]:
    url = _dapr_invoke_url(app_id, path)
    _logger.info(
        "workflow stage start", extra={"stage": stage, "app_id": app_id, "path": path}
    )
    try:
        response = httpx.post(url, json=body, timeout=timeout_s)
    except httpx.HTTPError as exc:
        raise WorkflowActivityError(
            f"stage={stage} app_id={app_id} path={path}: transport error: {exc}"
        ) from exc
    if response.status_code >= 300:
        # The kernel + harness both surface 422 with `{error, detail}`;
        # propagate verbatim so the workflow runtime captures the diagnostic.
        raise WorkflowActivityError(
            f"stage={stage} app_id={app_id} path={path}: "
            f"HTTP {response.status_code}: {response.text}"
        )
    try:
        out = response.json()
    except ValueError as exc:
        raise WorkflowActivityError(
            f"stage={stage} app_id={app_id} path={path}: "
            f"response is not JSON: {response.text!r}"
        ) from exc
    if not isinstance(out, dict):
        raise WorkflowActivityError(
            f"stage={stage} app_id={app_id} path={path}: "
            f"expected JSON object, got {type(out).__name__}"
        )
    _logger.info(
        "workflow stage ok", extra={"stage": stage, "app_id": app_id, "path": path}
    )
    return out


# ---------------------------------------------------------------------------
# Activities


def ingest_activity(
    ctx: WorkflowActivityContext, ingest_body: dict[str, Any]
) -> dict[str, Any]:
    """POST ``/v1/ingest`` against the harness sidecar; return ``payload``."""
    del ctx  # activity-id is correlated by the runtime
    out = _post_json(
        stage="ingest",
        app_id=HARNESS_APP_ID,
        path=INGEST_PATH,
        body=ingest_body,
        timeout_s=_INGEST_TIMEOUT_S,
    )
    payload = out.get("payload")
    if not isinstance(payload, dict):
        raise WorkflowActivityError(
            f"ingest response missing `payload` object: {out!r}"
        )
    return payload


def translate_activity(
    ctx: WorkflowActivityContext, translate_body: dict[str, Any]
) -> dict[str, Any]:
    """POST ``/v1/translate``; return ``{tree, matrix}``."""
    del ctx
    out = _post_json(
        stage="translate",
        app_id=HARNESS_APP_ID,
        path=TRANSLATE_PATH,
        body=translate_body,
        timeout_s=_TRANSLATE_TIMEOUT_S,
    )
    tree = out.get("tree")
    matrix = out.get("matrix")
    if not isinstance(tree, dict) or not isinstance(matrix, dict):
        raise WorkflowActivityError(
            f"translate response missing `tree`/`matrix` objects: keys={list(out)}"
        )
    return {"tree": tree, "matrix": matrix}


def deduce_activity(
    ctx: WorkflowActivityContext, deduce_body: dict[str, Any]
) -> dict[str, Any]:
    """POST ``/v1/deduce`` against the kernel sidecar; return the verdict."""
    del ctx
    return _post_json(
        stage="deduce",
        app_id=KERNEL_APP_ID,
        path=DEDUCE_PATH,
        body=deduce_body,
        timeout_s=_DEDUCE_TIMEOUT_S,
    )


def solve_activity(
    ctx: WorkflowActivityContext, solve_body: dict[str, Any]
) -> dict[str, Any]:
    """POST ``/v1/solve``; return the :class:`FormalVerificationTrace`."""
    del ctx
    return _post_json(
        stage="solve",
        app_id=KERNEL_APP_ID,
        path=SOLVE_PATH,
        body=solve_body,
        timeout_s=_SOLVE_HTTP_TIMEOUT_S,
    )


def recheck_activity(
    ctx: WorkflowActivityContext, recheck_body: dict[str, Any]
) -> dict[str, Any]:
    """POST ``/v1/recheck``; return the :class:`LeanRecheckWire`."""
    del ctx
    return _post_json(
        stage="recheck",
        app_id=KERNEL_APP_ID,
        path=RECHECK_PATH,
        body=recheck_body,
        timeout_s=_RECHECK_HTTP_TIMEOUT_S,
    )


def register_activities(runtime: WorkflowRuntime) -> None:
    """Register all five activities under their canonical names.

    The default ``register_activity`` name is the function's ``__name__``
    (e.g. ``ingest_activity``); pinning the name explicitly keeps the
    Workflow's ``call_activity`` strings stable across refactors.
    """
    runtime.register_activity(ingest_activity, name="ingest_activity")
    runtime.register_activity(translate_activity, name="translate_activity")
    runtime.register_activity(deduce_activity, name="deduce_activity")
    runtime.register_activity(solve_activity, name="solve_activity")
    runtime.register_activity(recheck_activity, name="recheck_activity")
