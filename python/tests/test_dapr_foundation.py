"""Foundation tests for the Phase 0 Dapr scaffold (Task 8.1).

Validates:
- The component manifests under ``dapr/components/`` are well-formed.
- The Configuration at ``dapr/config.yaml`` is well-formed.
- The slim Dapr CLI / runtime is staged under ``.bin/.dapr/`` (skipped
  with a loud notice when absent — same gating shape as ``rs-lean``).
- ``dapr run`` boots ``daprd`` against the project component manifests
  and ``daprd`` reports both ``cds-pubsub`` and ``cds-statestore`` as
  loaded plus ``Workflow engine started`` before clean shutdown.

The end-to-end smoke is the same gate that ``just dapr-smoke`` runs;
keeping it in pytest pins it inside the regular ``uv run pytest`` sweep
and gives the failure mode the same surface as the rest of the suite.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DAPR_DIR = REPO_ROOT / "dapr"
COMPONENTS_DIR = DAPR_DIR / "components"
CONFIG_PATH = DAPR_DIR / "config.yaml"
PUBSUB_PATH = COMPONENTS_DIR / "pubsub-inmemory.yaml"
STATESTORE_PATH = COMPONENTS_DIR / "state-store-inmemory.yaml"

DAPR_CLI = REPO_ROOT / ".bin" / "dapr"
DAPR_INSTALL_DIR = REPO_ROOT / ".bin" / ".dapr"
DAPRD_BIN = DAPR_INSTALL_DIR / ".dapr" / "bin" / "daprd"


def _load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def test_components_dir_exists() -> None:
    assert COMPONENTS_DIR.is_dir(), f"missing {COMPONENTS_DIR}"
    assert PUBSUB_PATH.is_file(), f"missing {PUBSUB_PATH}"
    assert STATESTORE_PATH.is_file(), f"missing {STATESTORE_PATH}"
    assert CONFIG_PATH.is_file(), f"missing {CONFIG_PATH}"


def test_pubsub_manifest_well_formed() -> None:
    doc = _load_yaml(PUBSUB_PATH)
    assert doc["apiVersion"] == "dapr.io/v1alpha1"
    assert doc["kind"] == "Component"
    assert doc["metadata"]["name"] == "cds-pubsub"
    assert doc["spec"]["type"] == "pubsub.in-memory"
    assert doc["spec"]["version"] == "v1"


def test_state_store_manifest_well_formed() -> None:
    doc = _load_yaml(STATESTORE_PATH)
    assert doc["apiVersion"] == "dapr.io/v1alpha1"
    assert doc["kind"] == "Component"
    assert doc["metadata"]["name"] == "cds-statestore"
    assert doc["spec"]["type"] == "state.in-memory"
    assert doc["spec"]["version"] == "v1"
    metadata = {entry["name"]: entry["value"] for entry in doc["spec"]["metadata"]}
    assert metadata["actorStateStore"] == "true", (
        "Workflow engine on Dapr 1.17 requires actorStateStore=true on the "
        "named state-store component"
    )


def test_configuration_well_formed() -> None:
    doc = _load_yaml(CONFIG_PATH)
    assert doc["apiVersion"] == "dapr.io/v1alpha1"
    assert doc["kind"] == "Configuration"
    assert doc["metadata"]["name"] == "cds-config"
    assert doc["spec"]["tracing"]["samplingRate"] == "1"
    assert doc["spec"]["tracing"]["stdout"] is True
    assert doc["spec"]["mtls"]["enabled"] is False


def test_component_names_unique() -> None:
    names = [_load_yaml(p)["metadata"]["name"] for p in sorted(COMPONENTS_DIR.glob("*.yaml"))]
    assert len(names) == len(set(names)), f"duplicate component names: {names}"


def test_dapr_cli_present_and_pinned() -> None:
    assert DAPR_CLI.is_file(), f"{DAPR_CLI} missing — run `just fetch-dapr`"
    out = subprocess.run(
        [str(DAPR_CLI), "--version"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout
    assert "CLI version: 1.17" in out, f"unexpected dapr CLI version: {out!r}"


def test_daprd_runtime_staged() -> None:
    assert DAPRD_BIN.is_file(), f"{DAPRD_BIN} missing — run `just fetch-dapr`"
    out = subprocess.run(
        [str(DAPRD_BIN), "--version"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout
    assert out.strip().startswith("1.17"), f"unexpected daprd version: {out!r}"


@pytest.mark.skipif(
    not DAPR_CLI.is_file() or not DAPRD_BIN.is_file(),
    reason="dapr CLI / slim runtime not staged — run `just fetch-dapr`",
)
def test_daprd_smoke_loads_components_and_starts_workflow() -> None:
    """Boot `dapr run` for ~2 s; assert components + workflow engine logs."""
    timeout_bin = shutil.which("timeout")
    assert timeout_bin is not None, "GNU coreutils `timeout` required"
    cmd = [
        timeout_bin,
        "8",
        str(DAPR_CLI),
        "run",
        "--app-id",
        "cds-dapr-foundation-pytest",
        "--runtime-path",
        str(DAPR_INSTALL_DIR),
        "--resources-path",
        str(COMPONENTS_DIR),
        "--config",
        str(CONFIG_PATH),
        "--log-level",
        "info",
        "--",
        "sleep",
        "2",
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    log = proc.stdout + proc.stderr
    assert "Component loaded: cds-pubsub (pubsub.in-memory/v1)" in log, log
    assert "Component loaded: cds-statestore (state.in-memory/v1)" in log, log
    assert "Using 'cds-statestore' as actor state store" in log, log
    assert "Workflow engine started" in log, log
    assert "Exited Dapr successfully" in log, log
