"""End-to-end Dapr Workflow pipeline smoke (Task 8.4b close-out).

One ``@pytest.mark.skipif``-gated integration test that drives the
canonical contradictory guideline through the
:func:`cds_harness.workflow.pipeline.pipeline_workflow` chain. The test
is the CI-friendly counterpart of ``just dapr-pipeline``: same flow,
same assertions, same cleanup discipline.

## Gates (per ADR-021 §3)

The test skips loudly (``pytest.skip`` with reason) when any of:

* ``.bin/dapr`` / slim runtime missing — needs ``just fetch-dapr``.
* ``.bin/.dapr/.dapr/bin/{placement,scheduler}`` missing — same fix.
* ``.bin/z3`` / ``.bin/cvc5`` missing — needs ``just fetch-bins``.
* ``CDS_KIMINA_URL`` unset — operator must point at a reachable
  Kimina daemon (``python -m server`` from
  ``project-numina/kimina-lean-server``).

## Flow

1. ``just dapr-cluster-up`` — placement + scheduler. The fixture
   pre-flights ``/v1.0/healthz`` (full readiness) on both children
   per ADR-021 §5.
2. ``dapr run --app-id cds-harness ...`` — uvicorn + harness sidecar.
3. ``dapr run --app-id cds-kernel ...`` — axum + kernel sidecar.
4. ``dapr run --app-id cds-workflow ...`` — Python workflow runner.
5. The workflow runner schedules one instance against
   ``data/guidelines/contradictory-bound.txt`` and asserts the same
   three flags as ``just dapr-pipeline``:
   * ``verdict.breach_summary`` non-empty (deduce stage active);
   * ``trace.sat == false`` (canonical contradictory matrix is unsat);
   * ``recheck.ok == true`` (Lean re-checks the Alethe proof).
6. Reverse teardown: workflow → kernel sidecar → harness sidecar →
   ``dapr-cluster-down``.

The cleanup discipline matches ``crates/kernel/tests/common.rs::sigterm_then_kill``
(SIGTERM → grace → SIGKILL); per-child grace is 5 s.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
SAMPLE_DIR = DATA_DIR / "sample"
GUIDELINES_DIR = DATA_DIR / "guidelines"
ICU_JSON = SAMPLE_DIR / "icu-monitor-02.json"
CONTRADICTORY_TXT = GUIDELINES_DIR / "contradictory-bound.txt"
CONTRADICTORY_RECORDED = GUIDELINES_DIR / "contradictory-bound.recorded.json"

DAPR_DIR = REPO_ROOT / "dapr"
COMPONENTS_DIR = DAPR_DIR / "components"
CONFIG_PATH = DAPR_DIR / "config.yaml"
DAPR_CLI = REPO_ROOT / ".bin" / "dapr"
DAPR_INSTALL_DIR = REPO_ROOT / ".bin" / ".dapr"
DAPRD_BIN = DAPR_INSTALL_DIR / ".dapr" / "bin" / "daprd"
PLACEMENT_BIN = DAPR_INSTALL_DIR / ".dapr" / "bin" / "placement"
SCHEDULER_BIN = DAPR_INSTALL_DIR / ".dapr" / "bin" / "scheduler"
Z3_BIN = REPO_ROOT / ".bin" / "z3"
CVC5_BIN = REPO_ROOT / ".bin" / "cvc5"

# Kernel binary the cds-kernel sidecar runs. Built once before spawning
# so daprd's app-discovery does not race a cold cargo build.
KERNEL_BIN = REPO_ROOT / "target" / "debug" / "cds-kernel-service"

# Per-child grace before SIGKILL escalation.
TEARDOWN_GRACE_S: float = 5.0


def _kimina_url() -> str | None:
    raw = os.environ.get("CDS_KIMINA_URL", "").strip()
    return raw or None


_GATE_REASON: str | None = None
if not DAPR_CLI.is_file() or not DAPRD_BIN.is_file():
    _GATE_REASON = "dapr CLI / slim runtime not staged — run `just fetch-dapr`"
elif not PLACEMENT_BIN.is_file() or not SCHEDULER_BIN.is_file():
    _GATE_REASON = "dapr placement / scheduler binaries missing — run `just fetch-dapr`"
elif not Z3_BIN.is_file() or not CVC5_BIN.is_file():
    _GATE_REASON = "Z3 / cvc5 missing under .bin/ — run `just fetch-bins`"
elif _kimina_url() is None:
    _GATE_REASON = (
        "CDS_KIMINA_URL unset — start Kimina (`python -m server` from the "
        "project-numina/kimina-lean-server checkout) and re-run with that URL exported"
    )

pytestmark = pytest.mark.skipif(_GATE_REASON is not None, reason=_GATE_REASON or "")


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_until_2xx(url: str, *, deadline: float, label: str) -> None:
    last_err: Exception | None = None
    last_status: int | None = None
    while time.monotonic() < deadline:
        try:
            response = httpx.get(url, timeout=2.0)
            last_status = response.status_code
            if 200 <= response.status_code < 300:
                return
        except httpx.HTTPError as exc:
            last_err = exc
        time.sleep(0.25)
    raise TimeoutError(
        f"readiness wait timed out for {label} at {url}: "
        f"status={last_status} err={last_err!r}"
    )


def _sigterm_then_kill(proc: subprocess.Popen[Any], *, grace_s: float) -> None:
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=grace_s)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        proc.kill()
        proc.wait(timeout=grace_s)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        pass


def _just(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    just_bin = shutil.which("just") or "just"
    return subprocess.run(
        [just_bin, *args],
        cwd=str(REPO_ROOT),
        check=check,
        capture_output=True,
        text=True,
        timeout=60,
    )


@contextmanager
def _dapr_cluster() -> Iterator[None]:
    _just("dapr-cluster-up")
    try:
        # ADR-021 §5: pipeline test pre-flights `/v1.0/healthz` on
        # placement + scheduler since both must be reachable for
        # Workflow to schedule activities.
        deadline = time.monotonic() + 30.0
        # placement healthz default port is pinned in the Justfile
        # (50007); scheduler is pinned at 50009.
        _wait_until_2xx(
            "http://127.0.0.1:50007/healthz", deadline=deadline, label="placement"
        )
        _wait_until_2xx(
            "http://127.0.0.1:50009/healthz", deadline=deadline, label="scheduler"
        )
        yield
    finally:
        _just("dapr-cluster-down", check=False)


@contextmanager
def _dapr_sidecar(
    *,
    app_id: str,
    app_port: int | None,
    inner_argv: list[str],
    env_overrides: dict[str, str],
    log_path: Path,
) -> Iterator[dict[str, int]]:
    """Spawn `dapr run --app-id ...` with allocated ports; yield the port map.

    Reverse-order teardown is the caller's responsibility (the
    ``finally`` here SIGTERM-then-SIGKILLs the daprd CLI, which
    propagates to its child sidecar + app processes).
    """
    dapr_http_port = _pick_free_port()
    dapr_grpc_port = _pick_free_port()
    metrics_port = _pick_free_port()

    cmd: list[str] = [
        str(DAPR_CLI),
        "run",
        "--app-id",
        app_id,
    ]
    if app_port is not None:
        cmd += [
            "--app-port",
            str(app_port),
            "--app-protocol",
            "http",
        ]
    cmd += [
        "--dapr-http-port",
        str(dapr_http_port),
        "--dapr-grpc-port",
        str(dapr_grpc_port),
        "--metrics-port",
        str(metrics_port),
        "--runtime-path",
        str(DAPR_INSTALL_DIR),
        "--resources-path",
        str(COMPONENTS_DIR),
        "--config",
        str(CONFIG_PATH),
        "--log-level",
        "info",
        "--",
        *inner_argv,
    ]

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env.update(env_overrides)

    log_handle = log_path.open("w", encoding="utf-8")
    proc = subprocess.Popen(
        cmd,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        env=env,
        cwd=str(REPO_ROOT),
        text=True,
    )
    try:
        yield {
            "app_port": app_port or 0,
            "dapr_http_port": dapr_http_port,
            "dapr_grpc_port": dapr_grpc_port,
            "metrics_port": metrics_port,
        }
    finally:
        _sigterm_then_kill(proc, grace_s=TEARDOWN_GRACE_S)
        log_handle.close()


def _build_kernel_binary() -> None:
    cargo = shutil.which("cargo")
    assert cargo is not None, "cargo missing on PATH"
    subprocess.run(
        [cargo, "build", "--bin", "cds-kernel-service"],
        check=True,
        cwd=str(REPO_ROOT),
        timeout=600,
    )
    assert KERNEL_BIN.is_file(), f"{KERNEL_BIN} not produced by cargo build"


def test_dapr_workflow_drives_contradictory_pipeline(tmp_path: Path) -> None:
    """Drive ingest → translate → deduce → solve → recheck end-to-end.

    Asserts the same three flags ``just dapr-pipeline`` does, plus the
    aggregated envelope shape (six top-level keys).
    """
    kimina_url = _kimina_url()
    assert kimina_url is not None  # gated by `pytestmark`

    _build_kernel_binary()

    py_app_port = _pick_free_port()
    rs_app_port = _pick_free_port()

    py_log = tmp_path / "harness-sidecar.log"
    rs_log = tmp_path / "kernel-sidecar.log"
    wf_log = tmp_path / "workflow-sidecar.log"

    with (
        _dapr_cluster(),
        _dapr_sidecar(
            app_id="cds-harness",
            app_port=py_app_port,
            inner_argv=[
                sys.executable,
                "-m",
                "cds_harness.service",
                "--host",
                "127.0.0.1",
                "--port",
                str(py_app_port),
            ],
            env_overrides={
                "CDS_HARNESS_HOST": "127.0.0.1",
                "CDS_HARNESS_PORT": str(py_app_port),
            },
            log_path=py_log,
        ) as harness_ports,
        _dapr_sidecar(
            app_id="cds-kernel",
            app_port=rs_app_port,
            inner_argv=[str(KERNEL_BIN)],
            env_overrides={
                "CDS_KERNEL_HOST": "127.0.0.1",
                "CDS_KERNEL_PORT": str(rs_app_port),
            },
            log_path=rs_log,
        ) as kernel_ports,
    ):
            deadline = time.monotonic() + 60.0
            _wait_until_2xx(
                f"http://127.0.0.1:{py_app_port}/healthz",
                deadline=deadline,
                label="harness app",
            )
            _wait_until_2xx(
                f"http://127.0.0.1:{rs_app_port}/healthz",
                deadline=deadline,
                label="kernel app",
            )
            # Full-readiness probe (placement-bound) — must be green
            # before Workflow can schedule activities (ADR-021 §5).
            _wait_until_2xx(
                f"http://127.0.0.1:{harness_ports['dapr_http_port']}/v1.0/healthz",
                deadline=deadline,
                label="harness daprd full-readiness",
            )
            _wait_until_2xx(
                f"http://127.0.0.1:{kernel_ports['dapr_http_port']}/v1.0/healthz",
                deadline=deadline,
                label="kernel daprd full-readiness",
            )

            # Run the workflow harness inside its own dapr sidecar; the
            # SDK auto-discovers the gRPC port via DAPR_GRPC_PORT (set by
            # `dapr run`). The orchestrator binary writes the aggregated
            # envelope as a single JSON line on stdout — capture it
            # through the sidecar log file.
            inner_argv = [
                "uv",
                "run",
                "python",
                "-m",
                "cds_harness.workflow",
                "run-pipeline",
                "--payload",
                str(ICU_JSON),
                "--guideline",
                str(CONTRADICTORY_TXT),
                "--doc-id",
                "contradictory-bound",
                "--kimina-url",
                kimina_url,
                "--z3-path",
                str(Z3_BIN),
                "--cvc5-path",
                str(CVC5_BIN),
                "--timeout-s",
                "600",
                "--assert-unsat",
                "--assert-recheck-ok",
            ]
            with _dapr_sidecar(
                app_id="cds-workflow",
                app_port=None,
                inner_argv=inner_argv,
                env_overrides={"CDS_KIMINA_URL": kimina_url},
                log_path=wf_log,
            ):
                # The workflow sidecar exits when the orchestrator
                # finishes. Poll the log file for the envelope, with a
                # generous wall-clock so a cold solver / Kimina round-
                # trip does not flake the gate.
                envelope: dict[str, Any] | None = None
                wf_deadline = time.monotonic() + 600.0
                while time.monotonic() < wf_deadline:
                    if not wf_log.is_file():
                        time.sleep(0.5)
                        continue
                    text = wf_log.read_text(encoding="utf-8")
                    # The orchestrator prints the envelope on a single
                    # stdout line; daprd interleaves its own logs but
                    # never produces a JSON line that starts with `{"`
                    # and contains all six envelope keys.
                    for line in reversed(text.splitlines()):
                        line = line.strip()
                        if not line.startswith("{"):
                            continue
                        try:
                            candidate = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if isinstance(candidate, dict) and all(
                            k in candidate
                            for k in ("payload", "ir", "matrix", "verdict", "trace", "recheck")
                        ):
                            envelope = candidate
                            break
                    if envelope is not None:
                        break
                    time.sleep(1.0)

                assert envelope is not None, (
                    f"workflow did not emit an envelope; tail of {wf_log}:\n"
                    f"{wf_log.read_text(encoding='utf-8')[-4000:]}"
                )

            # Three close-out flags from ADR-021 §3 + the aggregated
            # envelope shape.
            verdict = envelope["verdict"]
            assert isinstance(verdict, dict)
            breach_summary = verdict.get("breach_summary")
            assert isinstance(breach_summary, dict), (
                f"verdict.breach_summary must be a dict; got {breach_summary!r}"
            )
            assert len(breach_summary) > 0, (
                f"verdict.breach_summary must be non-empty; got {breach_summary!r}"
            )

            trace = envelope["trace"]
            assert isinstance(trace, dict)
            assert trace["sat"] is False, f"trace.sat must be False; got {trace!r}"
            muc = trace["muc"]
            assert isinstance(muc, list), f"trace.muc must be a list; got {muc!r}"
            assert len(muc) >= 2, (
                f"contradictory matrix must produce ≥ 2 MUC entries; got {muc!r}"
            )

            recheck = envelope["recheck"]
            assert isinstance(recheck, dict)
            assert (
                recheck["ok"] is True
            ), f"recheck.ok must be True; got {recheck!r}"
            assert recheck["custom_id"] == "cds-pipeline"

            # Make sure stage spans were emitted on the workflow side
            # (per-stage tracing — ADR-021 §3 bullet on tracing). The
            # orchestrator logs include `stage=ingest|translate|...`;
            # at minimum we expect each stage name to appear.
            wf_text = wf_log.read_text(encoding="utf-8")
            for stage in ("ingest", "translate", "deduce", "solve", "recheck"):
                assert stage in wf_text, (
                    f"per-stage trace missing `{stage}` in workflow log; "
                    f"tail:\n{wf_text[-2000:]}"
                )

    # `_dapr_cluster` cleans up placement+scheduler on exit.
