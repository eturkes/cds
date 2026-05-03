"""CLI entrypoint for the Phase 0 Dapr Workflow harness.

Two subcommands:

* ``run-pipeline``  — register the workflow + activities with a fresh
  :class:`dapr.ext.workflow.WorkflowRuntime`, schedule one instance with
  the canonical ``--payload`` + ``--guideline`` inputs, wait for
  completion, and print the aggregated envelope to stdout.

* ``serve``         — register the workflow + activities and block until
  killed. Useful when an operator wants to drive the workflow from a
  separate :class:`dapr.ext.workflow.DaprWorkflowClient` process.

Per ADR-021 §3 the orchestrator runs **inside** ``dapr run --app-id
cds-workflow`` so the SDK can connect to daprd's gRPC port (auto-
discovered from the ``DAPR_GRPC_PORT`` env var the runtime injects).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Final

import httpx
from dapr.ext.workflow import (
    DaprWorkflowClient,
    WorkflowRuntime,
    WorkflowStatus,
)

from cds_harness.workflow.activities import register_activities
from cds_harness.workflow.fhir_axis import (
    assert_muc_topology,
    build_patient_close_event,
    build_patient_open_event,
    build_subscription_notification,
)
from cds_harness.workflow.pipeline import (
    WORKFLOW_NAME,
    PipelineInput,
    register_workflow,
)

_logger = logging.getLogger("cds_harness.workflow")

_DEFAULT_TIMEOUT_S: int = 600
_DAPR_HTTP_PORT_ENV: Final[str] = "DAPR_HTTP_PORT"
_HARNESS_APP_ID: Final[str] = "cds-harness"
_FHIR_NOTIFICATION_PATH: Final[str] = "/v1/fhir/notification"
_FHIRCAST_OPEN_PATH: Final[str] = "/v1/fhircast/patient-open"
_FHIRCAST_CLOSE_PATH: Final[str] = "/v1/fhircast/patient-close"
_FHIRCAST_SESSIONS_PATH: Final[str] = "/v1/fhircast/sessions"
_FHIRCAST_IDENTIFIER_SYSTEM: Final[str] = "urn:cds:fhir-axis-smoke"


def _resolve_recorded_path(
    guideline_path: Path, recorded_arg: str | None
) -> Path:
    if recorded_arg is not None:
        return Path(recorded_arg).resolve()
    # Default: same stem as the guideline plus `.recorded.json` in the
    # same directory — matches the layout under `data/guidelines/`.
    candidate = guideline_path.with_suffix("").with_suffix(".recorded.json")
    if guideline_path.suffix == ".txt":
        candidate = guideline_path.with_suffix(".recorded.json")
    return candidate


def _resolve_kimina_url(arg_value: str | None) -> str:
    kimina_url = arg_value or os.environ.get("CDS_KIMINA_URL", "").strip()
    if not kimina_url:
        raise SystemExit(
            "Kimina URL required — pass --kimina-url or export CDS_KIMINA_URL "
            "(start Kimina via `python -m server` from the project-numina/"
            "kimina-lean-server checkout)."
        )
    return kimina_url


def _build_workflow_spec(
    *,
    args: argparse.Namespace,
    ingest_request: dict[str, Any],
    guideline_text: str,
    recorded_root: dict[str, Any],
    doc_id: str,
) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "doc_id": doc_id,
        "guideline_text": guideline_text,
        "guideline_root": recorded_root,
        "ingest_request": ingest_request,
        "logic": args.logic,
        "smt_check": args.smt_check,
        "kimina_url": _resolve_kimina_url(args.kimina_url),
        "custom_id": args.custom_id,
        "solve_timeout_ms": args.solve_timeout_ms,
        "recheck_timeout_ms": args.recheck_timeout_ms,
    }
    if args.z3_path:
        spec["z3_path"] = args.z3_path
    if args.cvc5_path:
        spec["cvc5_path"] = args.cvc5_path

    # Round-trip through PipelineInput once so any operator typo surfaces
    # before we schedule a workflow instance.
    return PipelineInput.model_validate(spec).model_dump(mode="json")


def _build_input(args: argparse.Namespace) -> dict[str, Any]:
    payload_path = Path(args.payload).resolve()
    guideline_path = Path(args.guideline).resolve()
    recorded_path = _resolve_recorded_path(guideline_path, args.recorded)

    raw_envelope = json.loads(payload_path.read_text(encoding="utf-8"))
    ingest_request = {"format": "json", "envelope": raw_envelope}

    guideline_text = guideline_path.read_text(encoding="utf-8")
    recorded = json.loads(recorded_path.read_text(encoding="utf-8"))
    if "root" not in recorded:
        raise SystemExit(
            f"recorded fixture {recorded_path} missing top-level `root` field"
        )

    doc_id = args.doc_id or guideline_path.stem
    return _build_workflow_spec(
        args=args,
        ingest_request=ingest_request,
        guideline_text=guideline_text,
        recorded_root=recorded["root"],
        doc_id=doc_id,
    )


def _summarise_envelope(envelope: dict[str, Any]) -> dict[str, Any]:
    """Compact summary for stderr — the full envelope still goes to stdout."""
    verdict = envelope.get("verdict") or {}
    trace = envelope.get("trace") or {}
    recheck = envelope.get("recheck") or {}
    breach_summary = verdict.get("breach_summary")
    return {
        "doc_id": (envelope.get("ir") or {}).get("doc_id"),
        "trace_sat": trace.get("sat"),
        "muc_len": len(trace.get("muc") or []),
        "recheck_ok": recheck.get("ok"),
        "breach_count": len(breach_summary) if isinstance(breach_summary, dict) else None,
    }


def _schedule_and_wait(
    *,
    workflow_input: dict[str, Any],
    timeout_s: int,
) -> dict[str, Any] | None:
    """Schedule one workflow instance and return its parsed envelope.

    Returns ``None`` if the workflow timed out, terminated abnormally, or
    produced an empty / non-JSON output. Diagnostics are written to
    stderr by the caller; this helper limits its surface to the happy
    path.
    """
    client = DaprWorkflowClient()
    try:
        instance_id = client.schedule_new_workflow(
            workflow=WORKFLOW_NAME,
            input=workflow_input,
        )
        _logger.info(
            "workflow scheduled",
            extra={"instance_id": instance_id, "workflow": WORKFLOW_NAME},
        )
        print(f"workflow instance scheduled: {instance_id}", file=sys.stderr)

        state = client.wait_for_workflow_completion(
            instance_id, timeout_in_seconds=timeout_s
        )
    finally:
        client.close()

    if state is None:
        print(
            f"workflow {instance_id} timed out after {timeout_s}s",
            file=sys.stderr,
        )
        return None
    if state.runtime_status != WorkflowStatus.COMPLETED:
        print(
            f"workflow {instance_id} terminated with status="
            f"{state.runtime_status.name}; details={state.failure_details!r}",
            file=sys.stderr,
        )
        return None
    raw = state.serialized_output
    if not raw:
        print(
            f"workflow {instance_id} completed but output is empty",
            file=sys.stderr,
        )
        return None
    try:
        envelope = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(
            f"workflow {instance_id} output is not JSON: {exc}; raw={raw!r}",
            file=sys.stderr,
        )
        return None
    return envelope


def _check_envelope_assertions(envelope: dict[str, Any], args: argparse.Namespace) -> int:
    if args.assert_unsat:
        trace_sat = (envelope.get("trace") or {}).get("sat")
        if trace_sat is not False:
            print(
                f"--assert-unsat: trace.sat must be false; got {trace_sat!r}",
                file=sys.stderr,
            )
            return 1
    if args.assert_sat:
        trace_sat = (envelope.get("trace") or {}).get("sat")
        if trace_sat is not True:
            print(
                f"--assert-sat: trace.sat must be true; got {trace_sat!r}",
                file=sys.stderr,
            )
            return 1
    if args.assert_recheck_ok:
        recheck_ok = (envelope.get("recheck") or {}).get("ok")
        if recheck_ok is not True:
            print(
                f"--assert-recheck-ok: recheck.ok must be true; got {recheck_ok!r}",
                file=sys.stderr,
            )
            return 1
    return 0


def _run_pipeline_cmd(args: argparse.Namespace) -> int:
    workflow_input = _build_input(args)

    runtime = WorkflowRuntime()
    register_activities(runtime)
    register_workflow(runtime)
    runtime.start()
    try:
        runtime.wait_for_worker_ready(timeout_s=30.0)
        envelope = _schedule_and_wait(
            workflow_input=workflow_input, timeout_s=args.timeout_s
        )
        if envelope is None:
            return 1

        summary = _summarise_envelope(envelope)
        print(f"workflow summary: {json.dumps(summary)}", file=sys.stderr)

        json.dump(envelope, sys.stdout)
        sys.stdout.write("\n")
        sys.stdout.flush()

        return _check_envelope_assertions(envelope, args)
    finally:
        runtime.shutdown()


def _dapr_invoke_url(app_id: str, path: str) -> str:
    raw = os.environ.get(_DAPR_HTTP_PORT_ENV)
    if not raw:
        raise SystemExit(
            f"{_DAPR_HTTP_PORT_ENV} unset — `run-fhir-pipeline` must run under "
            "`dapr run` so daprd can route service-invocation calls."
        )
    try:
        port = int(raw)
    except ValueError as exc:
        raise SystemExit(
            f"{_DAPR_HTTP_PORT_ENV}={raw!r} is not an integer"
        ) from exc
    return f"http://127.0.0.1:{port}/v1.0/invoke/{app_id}/method{path}"


def _run_fhir_pipeline_cmd(args: argparse.Namespace) -> int:
    """End-to-end FHIR axis close-out runner (Task 10.4 — ADR-027).

    Drives the FHIR axis through the existing Phase 0 Workflow:

    1. Reads a FHIR R5 collection ``Bundle`` (default
       ``data/fhir/icu-monitor-02.observations.json``).
    2. Wraps it as a subscription-notification (SubscriptionStatus at
       ``entry[0]``, locked by ADR-025 §4 + R5 Subscriptions Backport
       IG v1.2.0).
    3. POSTs to harness ``/v1/fhir/notification`` via daprd → projects
       to :class:`ClinicalTelemetryPayload` (Task 10.2).
    4. POSTs FHIRcast ``patient-open`` carrying the projected
       ``patient_pseudo_id`` via daprd → registry transition
       (Task 10.3).
    5. Asserts ``GET /v1/fhircast/sessions`` reflects the open session.
    6. Schedules the canonical Workflow with the projected envelope as
       its ``ingest_request`` (``format = json``).
    7. Waits for completion + asserts ``trace.sat == false`` +
       ``recheck.ok == true``.
    8. Verifies every ``trace.muc`` entry topologically maps back to an
       Atom span in the IR tree (constraint **C4**).
    9. POSTs FHIRcast ``patient-close`` via daprd; asserts the registry
       no longer contains the session topic.
    """
    fhir_bundle_path = Path(args.fhir_bundle).resolve()
    guideline_path = Path(args.guideline).resolve()
    recorded_path = _resolve_recorded_path(guideline_path, args.recorded)

    collection_bundle = json.loads(fhir_bundle_path.read_text(encoding="utf-8"))
    notification = build_subscription_notification(
        collection_bundle,
        notification_id=args.notification_id,
        subscription_reference=args.subscription_reference,
        topic_url=args.topic_url,
    )

    guideline_text = guideline_path.read_text(encoding="utf-8")
    recorded = json.loads(recorded_path.read_text(encoding="utf-8"))
    if "root" not in recorded:
        raise SystemExit(
            f"recorded fixture {recorded_path} missing top-level `root` field"
        )
    doc_id = args.doc_id or guideline_path.stem

    timeout_s = float(args.http_timeout_s)

    # Stage 1 — FHIR Subscriptions notification → ClinicalTelemetryPayload.
    notify_url = _dapr_invoke_url(_HARNESS_APP_ID, _FHIR_NOTIFICATION_PATH)
    print(
        f"→ FHIR notification: POST {notify_url} (bundle entries="
        f"{len(notification.get('entry') or [])})",
        file=sys.stderr,
    )
    notify_response = httpx.post(
        notify_url, json={"bundle": notification}, timeout=timeout_s
    )
    notify_response.raise_for_status()
    notify_body = notify_response.json()
    payload = notify_body.get("payload") if isinstance(notify_body, dict) else None
    if not isinstance(payload, dict):
        print(
            f"FHIR notification response missing `payload`: {notify_body!r}",
            file=sys.stderr,
        )
        return 1
    patient_pseudo_id = (payload.get("source") or {}).get("patient_pseudo_id")
    if not isinstance(patient_pseudo_id, str) or not patient_pseudo_id:
        print(
            f"projected payload missing source.patient_pseudo_id: {payload!r}",
            file=sys.stderr,
        )
        return 1

    # Stage 2 — FHIRcast patient-open.
    hub_topic = (
        args.fhircast_topic
        or f"https://hub.example.org/topic/cds-fhir-axis-{uuid.uuid4()}"
    )
    open_event = build_patient_open_event(
        hub_topic=hub_topic,
        event_id=f"evt-axis-open-{uuid.uuid4()}",
        timestamp="2026-05-03T00:00:00.000000Z",
        patient_pseudo_id=patient_pseudo_id,
        identifier_system=_FHIRCAST_IDENTIFIER_SYSTEM,
    )
    open_url = _dapr_invoke_url(_HARNESS_APP_ID, _FHIRCAST_OPEN_PATH)
    print(f"→ FHIRcast patient-open: POST {open_url}", file=sys.stderr)
    open_response = httpx.post(open_url, json=open_event, timeout=timeout_s)
    open_response.raise_for_status()

    sessions_url = _dapr_invoke_url(_HARNESS_APP_ID, _FHIRCAST_SESSIONS_PATH)
    sessions_after_open = httpx.get(sessions_url, timeout=timeout_s).json()
    active_open = (
        sessions_after_open.get("active")
        if isinstance(sessions_after_open, dict)
        else None
    )
    if not isinstance(active_open, dict) or active_open.get(hub_topic) != patient_pseudo_id:
        print(
            f"session registry missing topic {hub_topic!r} → {patient_pseudo_id!r} "
            f"after patient-open: {sessions_after_open!r}",
            file=sys.stderr,
        )
        return 1

    # Stage 3 — Workflow over the projected envelope.
    ingest_request = {"format": "json", "envelope": payload}
    workflow_input = _build_workflow_spec(
        args=args,
        ingest_request=ingest_request,
        guideline_text=guideline_text,
        recorded_root=recorded["root"],
        doc_id=doc_id,
    )

    runtime = WorkflowRuntime()
    register_activities(runtime)
    register_workflow(runtime)
    runtime.start()
    try:
        runtime.wait_for_worker_ready(timeout_s=30.0)
        envelope = _schedule_and_wait(
            workflow_input=workflow_input, timeout_s=args.timeout_s
        )
        if envelope is None:
            return 1

        summary = _summarise_envelope(envelope)
        print(f"workflow summary: {json.dumps(summary)}", file=sys.stderr)

        json.dump(envelope, sys.stdout)
        sys.stdout.write("\n")
        sys.stdout.flush()

        rc = _check_envelope_assertions(envelope, args)
        if rc != 0:
            return rc

        # Stage 4 — MUC ↔ source_span topology (constraint C4).
        try:
            parsed_muc = assert_muc_topology(envelope, expected_doc_id=doc_id)
        except AssertionError as exc:
            print(f"MUC topology assertion failed: {exc}", file=sys.stderr)
            return 1
        print(
            f"✓ MUC topology: {len(parsed_muc)} entries → atoms "
            f"{sorted({(s, e) for _doc, s, e in parsed_muc})}",
            file=sys.stderr,
        )

        # Stage 5 — FHIRcast patient-close + session registry teardown.
        close_event = build_patient_close_event(
            hub_topic=hub_topic,
            event_id=f"evt-axis-close-{uuid.uuid4()}",
            timestamp="2026-05-03T01:00:00.000000Z",
            patient_pseudo_id=patient_pseudo_id,
            identifier_system=_FHIRCAST_IDENTIFIER_SYSTEM,
        )
        close_url = _dapr_invoke_url(_HARNESS_APP_ID, _FHIRCAST_CLOSE_PATH)
        print(f"→ FHIRcast patient-close: POST {close_url}", file=sys.stderr)
        close_response = httpx.post(close_url, json=close_event, timeout=timeout_s)
        close_response.raise_for_status()

        sessions_after_close = httpx.get(sessions_url, timeout=timeout_s).json()
        active_close = (
            sessions_after_close.get("active")
            if isinstance(sessions_after_close, dict)
            else None
        )
        if not isinstance(active_close, dict) or hub_topic in active_close:
            print(
                f"session registry still contains topic {hub_topic!r} after "
                f"patient-close: {sessions_after_close!r}",
                file=sys.stderr,
            )
            return 1

        print(
            "✓ fhir-axis-smoke: notification → workflow → recheck → close OK",
            file=sys.stderr,
        )
        return 0
    finally:
        runtime.shutdown()


def _serve_cmd(args: argparse.Namespace) -> int:
    runtime = WorkflowRuntime()
    register_activities(runtime)
    register_workflow(runtime)
    runtime.start()
    print("workflow runtime serving — Ctrl-C to exit", file=sys.stderr)
    try:
        while True:
            time.sleep(args.poll_s)
    except KeyboardInterrupt:
        print("stopping workflow runtime", file=sys.stderr)
        return 0
    finally:
        runtime.shutdown()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m cds_harness.workflow",
        description="Phase 0 Dapr Workflow harness — chain ingest → translate "
        "→ deduce → solve → recheck.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser(
        "run-pipeline",
        help="Schedule one workflow instance against the canonical Phase 0 fixtures.",
    )
    run.add_argument("--payload", required=True, help="Path to a JSON telemetry envelope.")
    run.add_argument("--guideline", required=True, help="Path to a guideline .txt file.")
    run.add_argument(
        "--recorded",
        default=None,
        help="Path to the recorded OnionL JSON. Defaults to <guideline>.recorded.json.",
    )
    run.add_argument("--doc-id", default=None, help="OnionL doc_id (defaults to guideline stem).")
    run.add_argument(
        "--kimina-url", default=None, help="Kimina REST URL (overrides $CDS_KIMINA_URL)."
    )
    run.add_argument(
        "--custom-id", default="cds-pipeline", help="Lean re-check correlation id."
    )
    run.add_argument(
        "--logic", default="QF_LRA", help="SMT-LIBv2 logic for the matrix preamble."
    )
    run.add_argument(
        "--smt-check", action="store_true", help="Enable harness-side Z3 sanity check."
    )
    run.add_argument("--solve-timeout-ms", type=int, default=30_000)
    run.add_argument("--recheck-timeout-ms", type=int, default=120_000)
    run.add_argument("--z3-path", default=None, help="Override solve.options.z3_path.")
    run.add_argument("--cvc5-path", default=None, help="Override solve.options.cvc5_path.")
    run.add_argument(
        "--timeout-s",
        type=int,
        default=_DEFAULT_TIMEOUT_S,
        help="Workflow completion wall-clock budget.",
    )
    run.add_argument("--assert-unsat", action="store_true", help="Fail unless trace.sat==False.")
    run.add_argument("--assert-sat", action="store_true", help="Fail unless trace.sat==True.")
    run.add_argument(
        "--assert-recheck-ok",
        action="store_true",
        help="Fail unless recheck.ok==True.",
    )
    run.set_defaults(func=_run_pipeline_cmd)

    fhir = sub.add_parser(
        "run-fhir-pipeline",
        help=(
            "End-to-end FHIR axis close-out: subscription-notification → "
            "harness projection → FHIRcast patient-open → Workflow → MUC "
            "topology check → FHIRcast patient-close. Task 10.4 / ADR-027."
        ),
    )
    fhir.add_argument(
        "--fhir-bundle",
        required=True,
        help="Path to a FHIR R5 collection Bundle (canonical fixture).",
    )
    fhir.add_argument("--guideline", required=True, help="Path to a guideline .txt file.")
    fhir.add_argument(
        "--recorded",
        default=None,
        help="Path to the recorded OnionL JSON. Defaults to <guideline>.recorded.json.",
    )
    fhir.add_argument(
        "--doc-id", default=None, help="OnionL doc_id (defaults to guideline stem)."
    )
    fhir.add_argument(
        "--kimina-url", default=None, help="Kimina REST URL (overrides $CDS_KIMINA_URL)."
    )
    fhir.add_argument("--custom-id", default="cds-fhir-axis", help="Lean re-check correlation id.")
    fhir.add_argument(
        "--logic", default="QF_LRA", help="SMT-LIBv2 logic for the matrix preamble."
    )
    fhir.add_argument(
        "--smt-check", action="store_true", help="Enable harness-side Z3 sanity check."
    )
    fhir.add_argument("--solve-timeout-ms", type=int, default=30_000)
    fhir.add_argument("--recheck-timeout-ms", type=int, default=120_000)
    fhir.add_argument("--z3-path", default=None)
    fhir.add_argument("--cvc5-path", default=None)
    fhir.add_argument(
        "--timeout-s",
        type=int,
        default=_DEFAULT_TIMEOUT_S,
        help="Workflow completion wall-clock budget.",
    )
    fhir.add_argument(
        "--http-timeout-s",
        type=float,
        default=30.0,
        help="Per-request httpx timeout for daprd-routed boundary calls.",
    )
    fhir.add_argument(
        "--notification-id",
        default="ntfn-fhir-axis",
        help="Bundle.id for the synthetic subscription-notification.",
    )
    fhir.add_argument(
        "--subscription-reference",
        default="Subscription/sub-fhir-axis",
        help="SubscriptionStatus.subscription.reference value.",
    )
    fhir.add_argument(
        "--topic-url",
        default="http://example.org/SubscriptionTopic/icu-vitals",
        help="SubscriptionStatus.topic value.",
    )
    fhir.add_argument(
        "--fhircast-topic",
        default=None,
        help=(
            "Override hub.topic value (defaults to a fresh UUID-tagged URL "
            "so multiple runs do not collide)."
        ),
    )
    fhir.add_argument("--assert-unsat", action="store_true")
    fhir.add_argument("--assert-sat", action="store_true")
    fhir.add_argument("--assert-recheck-ok", action="store_true")
    fhir.set_defaults(func=_run_fhir_pipeline_cmd)

    serve = sub.add_parser(
        "serve",
        help="Register the workflow + activities and block until killed.",
    )
    serve.add_argument("--poll-s", type=float, default=1.0, help="Idle-poll interval.")
    serve.set_defaults(func=_serve_cmd)

    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
