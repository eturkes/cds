"""End-to-end Dapr Workflow harness — Phase 0 close-out (Task 8.4b).

Composes the five Phase 0 sidecar endpoints into a single deterministic
:mod:`dapr.ext.workflow` orchestration that produces the aggregated
verification envelope:

    ingest   →  /v1/ingest    (cds-harness)
    translate → /v1/translate (cds-harness)
    deduce   →  /v1/deduce    (cds-kernel)
    solve    →  /v1/solve     (cds-kernel)
    recheck  →  /v1/recheck   (cds-kernel)

Each activity is a thin :mod:`httpx`-over-daprd wrapper POSTing
``application/json`` bodies to
``http://127.0.0.1:$DAPR_HTTP_PORT/v1.0/invoke/<app-id>/method/<path>``;
the WorkflowRuntime + DaprWorkflowClient connect to the same daprd
sidecar via gRPC for replay-deterministic orchestration. The aggregated
envelope (``{payload, ir, matrix, verdict, trace, recheck}``) is the
single in-band JSON return value of the workflow (constraint **C6**;
ADR-021 §7 — state-store handles deferred to Phase 1+).
"""

from __future__ import annotations

from cds_harness.workflow.activities import (
    DEDUCE_PATH,
    DEFAULT_RECHECK_TIMEOUT_MS,
    DEFAULT_SOLVE_TIMEOUT_MS,
    HARNESS_APP_ID,
    INGEST_PATH,
    KERNEL_APP_ID,
    RECHECK_PATH,
    SOLVE_PATH,
    TRANSLATE_PATH,
    WORKFLOW_APP_ID,
    WorkflowActivityError,
    deduce_activity,
    ingest_activity,
    recheck_activity,
    register_activities,
    solve_activity,
    translate_activity,
)
from cds_harness.workflow.fhir_axis import (
    assert_muc_topology,
    build_patient_close_event,
    build_patient_open_event,
    build_subscription_notification,
    collect_atom_spans,
    iter_observation_entries,
    parse_muc_entry,
)
from cds_harness.workflow.pipeline import (
    WORKFLOW_NAME,
    PipelineInput,
    pipeline_workflow,
    register_workflow,
)

__all__ = [
    "DEDUCE_PATH",
    "DEFAULT_RECHECK_TIMEOUT_MS",
    "DEFAULT_SOLVE_TIMEOUT_MS",
    "HARNESS_APP_ID",
    "INGEST_PATH",
    "KERNEL_APP_ID",
    "RECHECK_PATH",
    "SOLVE_PATH",
    "TRANSLATE_PATH",
    "WORKFLOW_APP_ID",
    "WORKFLOW_NAME",
    "PipelineInput",
    "WorkflowActivityError",
    "assert_muc_topology",
    "build_patient_close_event",
    "build_patient_open_event",
    "build_subscription_notification",
    "collect_atom_spans",
    "deduce_activity",
    "ingest_activity",
    "iter_observation_entries",
    "parse_muc_entry",
    "pipeline_workflow",
    "recheck_activity",
    "register_activities",
    "register_workflow",
    "solve_activity",
    "translate_activity",
]
