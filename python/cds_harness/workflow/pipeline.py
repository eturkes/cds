"""Phase 0 Dapr Workflow chaining the five sidecar activities.

Per ADR-021 §3 the Workflow is **deterministic** — all non-determinism
(HTTP, environment) lives in :mod:`cds_harness.workflow.activities`. The
return value is the in-band aggregated envelope:

    { payload, ir, matrix, verdict, trace, recheck }

ADR-021 §3 picks the in-band shape over state-store handles for Phase 0
because (a) payload sizes are low-kB; (b) state-store handles add a
serialisation indirection that complicates Workflow replay debugging;
and (c) constraint **C6** (JSON-over-TCP) is satisfied without a
secondary state-store hop. Phase 1+ revisits when payload shape grows.
"""

from __future__ import annotations

import logging
from collections.abc import Generator
from typing import Any, Final

from dapr.ext.workflow import DaprWorkflowContext, WorkflowRuntime
from pydantic import BaseModel, ConfigDict, Field

from cds_harness.workflow.activities import (
    DEFAULT_RECHECK_TIMEOUT_MS,
    DEFAULT_SOLVE_TIMEOUT_MS,
)

WORKFLOW_NAME: Final[str] = "cds_pipeline_workflow"

_logger = logging.getLogger(__name__)


class PipelineInput(BaseModel):
    """Workflow input — one canonical guideline run.

    Frozen + ``extra='forbid'`` so the SDK's JSON deserialiser will surface
    any operator typos as validation errors rather than silently ignoring
    them on replay.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    doc_id: str = Field(..., min_length=1)
    guideline_text: str = Field(..., description="Raw UTF-8 guideline body.")
    guideline_root: dict[str, Any] = Field(
        ...,
        description="Pre-formalised OnionL root node (matches the harness "
        "`/v1/translate` `root` field).",
    )
    ingest_request: dict[str, Any] = Field(
        ...,
        description="Body for `/v1/ingest` — either `{format:'json', envelope:...}` "
        "or `{format:'csv', csv_text:..., meta:...}`.",
    )
    logic: str = Field(
        default="QF_LRA",
        description="SMT-LIBv2 logic for the emitter preamble.",
    )
    smt_check: bool = Field(
        default=False,
        description="Run the harness in-process Z3 sanity check during translate.",
    )
    kimina_url: str = Field(
        ...,
        description="Kimina headless server URL for the recheck stage; "
        "operator-supplied because the kernel does not bake a default.",
    )
    custom_id: str = Field(
        default="cds-pipeline",
        description="Lean re-check correlation ID (round-trips through `LeanRecheckWire`).",
    )
    solve_timeout_ms: int = Field(
        default=DEFAULT_SOLVE_TIMEOUT_MS,
        ge=1,
        description="Per-request `solve.options.timeout_ms` override.",
    )
    recheck_timeout_ms: int = Field(
        default=DEFAULT_RECHECK_TIMEOUT_MS,
        ge=1,
        description="Per-request `recheck.options.timeout_ms` override.",
    )
    z3_path: str | None = Field(
        default=None,
        description="Optional `solve.options.z3_path` override (absolute path).",
    )
    cvc5_path: str | None = Field(
        default=None,
        description="Optional `solve.options.cvc5_path` override (absolute path).",
    )


def _solve_options(model: PipelineInput) -> dict[str, Any]:
    out: dict[str, Any] = {"timeout_ms": model.solve_timeout_ms}
    if model.z3_path is not None:
        out["z3_path"] = model.z3_path
    if model.cvc5_path is not None:
        out["cvc5_path"] = model.cvc5_path
    return out


def _recheck_options(model: PipelineInput) -> dict[str, Any]:
    return {
        "kimina_url": model.kimina_url,
        "timeout_ms": model.recheck_timeout_ms,
        "custom_id": model.custom_id,
    }


def pipeline_workflow(
    ctx: DaprWorkflowContext, raw_input: dict[str, Any]
) -> Generator[Any, Any, dict[str, Any]]:
    """Chain ingest → translate → deduce → solve → recheck.

    The Workflow runtime serialises the input as JSON and re-hydrates it on
    each replay; we re-validate through :class:`PipelineInput` inside the
    workflow body so the model stays the canonical shape both for
    operators (typo-catching) and for the runtime (deterministic
    deserialisation).
    """
    model = PipelineInput.model_validate(raw_input)
    if not ctx.is_replaying:
        _logger.info(
            "workflow start",
            extra={
                "stage": "workflow",
                "doc_id": model.doc_id,
                "instance_id": ctx.instance_id,
            },
        )

    # Stage 1 — ingest (cds-harness)
    payload: dict[str, Any] = yield ctx.call_activity(
        "ingest_activity", input=model.ingest_request
    )

    # Stage 2 — translate (cds-harness)
    translate_body = {
        "doc_id": model.doc_id,
        "text": model.guideline_text,
        "root": model.guideline_root,
        "logic": model.logic,
        "smt_check": model.smt_check,
    }
    translated: dict[str, Any] = yield ctx.call_activity(
        "translate_activity", input=translate_body
    )
    ir = translated["tree"]
    matrix = translated["matrix"]

    # Stage 3 — deduce (cds-kernel; uses the canonical thresholds when
    # `rules` is absent).
    verdict: dict[str, Any] = yield ctx.call_activity(
        "deduce_activity", input={"payload": payload}
    )

    # Stage 4 — solve (cds-kernel)
    trace: dict[str, Any] = yield ctx.call_activity(
        "solve_activity",
        input={"matrix": matrix, "options": _solve_options(model)},
    )

    # Stage 5 — recheck (cds-kernel)
    recheck: dict[str, Any] = yield ctx.call_activity(
        "recheck_activity",
        input={"trace": trace, "options": _recheck_options(model)},
    )

    if not ctx.is_replaying:
        _logger.info(
            "workflow done",
            extra={
                "stage": "workflow",
                "doc_id": model.doc_id,
                "instance_id": ctx.instance_id,
                "trace_sat": trace.get("sat"),
                "recheck_ok": recheck.get("ok"),
            },
        )

    return {
        "payload": payload,
        "ir": ir,
        "matrix": matrix,
        "verdict": verdict,
        "trace": trace,
        "recheck": recheck,
    }


def register_workflow(runtime: WorkflowRuntime) -> None:
    """Register the workflow under its canonical name."""
    runtime.register_workflow(pipeline_workflow, name=WORKFLOW_NAME)
