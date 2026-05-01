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
from pathlib import Path
from typing import Any

from dapr.ext.workflow import (
    DaprWorkflowClient,
    WorkflowRuntime,
    WorkflowStatus,
)

from cds_harness.workflow.activities import register_activities
from cds_harness.workflow.pipeline import (
    WORKFLOW_NAME,
    PipelineInput,
    register_workflow,
)

_logger = logging.getLogger("cds_harness.workflow")

_DEFAULT_TIMEOUT_S: int = 600


def _build_input(args: argparse.Namespace) -> dict[str, Any]:
    payload_path = Path(args.payload).resolve()
    guideline_path = Path(args.guideline).resolve()
    recorded_path = Path(args.recorded).resolve() if args.recorded else None

    if recorded_path is None:
        # Default: same stem as the guideline plus `.recorded.json` in
        # the same directory — matches the layout under `data/guidelines/`.
        recorded_path = guideline_path.with_suffix("").with_suffix(".recorded.json")
        if guideline_path.suffix == ".txt":
            recorded_path = guideline_path.with_suffix(".recorded.json")

    raw_envelope = json.loads(payload_path.read_text(encoding="utf-8"))
    ingest_request = {"format": "json", "envelope": raw_envelope}

    guideline_text = guideline_path.read_text(encoding="utf-8")
    recorded = json.loads(recorded_path.read_text(encoding="utf-8"))
    if "root" not in recorded:
        raise SystemExit(
            f"recorded fixture {recorded_path} missing top-level `root` field"
        )

    doc_id = args.doc_id or guideline_path.stem

    kimina_url = args.kimina_url or os.environ.get("CDS_KIMINA_URL", "").strip()
    if not kimina_url:
        raise SystemExit(
            "Kimina URL required — pass --kimina-url or export CDS_KIMINA_URL "
            "(start Kimina via `python -m server` from the project-numina/"
            "kimina-lean-server checkout)."
        )

    spec: dict[str, Any] = {
        "doc_id": doc_id,
        "guideline_text": guideline_text,
        "guideline_root": recorded["root"],
        "ingest_request": ingest_request,
        "logic": args.logic,
        "smt_check": args.smt_check,
        "kimina_url": kimina_url,
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


def _run_pipeline_cmd(args: argparse.Namespace) -> int:
    workflow_input = _build_input(args)

    runtime = WorkflowRuntime()
    register_activities(runtime)
    register_workflow(runtime)
    runtime.start()
    try:
        runtime.wait_for_worker_ready(timeout_s=30.0)
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
                instance_id, timeout_in_seconds=args.timeout_s
            )
        finally:
            client.close()

        if state is None:
            print(
                f"workflow {instance_id} timed out after {args.timeout_s}s",
                file=sys.stderr,
            )
            return 1

        if state.runtime_status != WorkflowStatus.COMPLETED:
            print(
                f"workflow {instance_id} terminated with status="
                f"{state.runtime_status.name}; details={state.failure_details!r}",
                file=sys.stderr,
            )
            return 1

        raw = state.serialized_output
        if not raw:
            print(
                f"workflow {instance_id} completed but output is empty",
                file=sys.stderr,
            )
            return 1
        try:
            envelope = json.loads(raw)
        except json.JSONDecodeError as exc:
            print(
                f"workflow {instance_id} output is not JSON: {exc}; raw={raw!r}",
                file=sys.stderr,
            )
            return 1

        summary = _summarise_envelope(envelope)
        print(f"workflow summary: {json.dumps(summary)}", file=sys.stderr)

        json.dump(envelope, sys.stdout)
        sys.stdout.write("\n")
        sys.stdout.flush()

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
