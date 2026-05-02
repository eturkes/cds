"""Tests for ``cds_harness.service`` (Task 8.2 — Python harness Dapr service).

Two layers:

* **In-process FastAPI tests** drive the app directly through
  :class:`fastapi.testclient.TestClient`. Fast, hermetic, no Dapr.
* **Sidecar smoke** spawns ``dapr run`` + uvicorn in a subprocess and
  drives both endpoints through the Dapr service-invocation API
  (``http://localhost:<sidecar>/v1.0/invoke/cds-harness/method/v1/...``).
  Gated by the same shape as ``test_dapr_foundation``: skip-with-reason
  when the staged Dapr CLI/runtime is missing.
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
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from cds_harness import HARNESS_ID, PHASE
from cds_harness.schema import SCHEMA_VERSION
from cds_harness.service import (
    FHIR_NOTIFICATION_PATH,
    HEALTHZ_PATH,
    INGEST_PATH,
    SERVICE_APP_ID,
    TRANSLATE_PATH,
    create_app,
    resolve_host,
    resolve_port,
)
from cds_harness.translate.adapter import AutoformalAdapter

# ---------------------------------------------------------------------------
# Project anchors


def _project_root() -> Path:
    here = Path(__file__).resolve()
    for ancestor in (here, *here.parents):
        if (ancestor / "Cargo.toml").is_file():
            return ancestor
    raise RuntimeError("could not locate project root")


REPO_ROOT = _project_root()
SAMPLE_DIR = REPO_ROOT / "data" / "sample"
GUIDELINES_DIR = REPO_ROOT / "data" / "guidelines"
FHIR_DIR = REPO_ROOT / "data" / "fhir"
HYPOXEMIA_TXT = GUIDELINES_DIR / "hypoxemia-trigger.txt"
HYPOXEMIA_RECORDED = GUIDELINES_DIR / "hypoxemia-trigger.recorded.json"
CONTRADICTORY_TXT = GUIDELINES_DIR / "contradictory-bound.txt"
CONTRADICTORY_RECORDED = GUIDELINES_DIR / "contradictory-bound.recorded.json"
ICU_CSV = SAMPLE_DIR / "icu-monitor-01.csv"
ICU_META = SAMPLE_DIR / "icu-monitor-01.meta.json"
ICU_JSON = SAMPLE_DIR / "icu-monitor-02.json"
FHIR_BUNDLE_02 = FHIR_DIR / "icu-monitor-02.observations.json"

DAPR_DIR = REPO_ROOT / "dapr"
COMPONENTS_DIR = DAPR_DIR / "components"
CONFIG_PATH = DAPR_DIR / "config.yaml"
DAPR_CLI = REPO_ROOT / ".bin" / "dapr"
DAPR_INSTALL_DIR = REPO_ROOT / ".bin" / ".dapr"
DAPRD_BIN = DAPR_INSTALL_DIR / ".dapr" / "bin" / "daprd"

# ---------------------------------------------------------------------------
# In-process tests


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as inner:
        yield inner


def test_healthz_reports_phase0(client: TestClient) -> None:
    response = client.get(HEALTHZ_PATH)
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "status": "ok",
        "harness_id": HARNESS_ID,
        "phase": PHASE,
        "schema_version": SCHEMA_VERSION,
    }


def test_constants_match_dapr_app_id() -> None:
    assert SERVICE_APP_ID == "cds-harness"
    assert INGEST_PATH == "/v1/ingest"
    assert FHIR_NOTIFICATION_PATH == "/v1/fhir/notification"
    assert TRANSLATE_PATH == "/v1/translate"
    assert HEALTHZ_PATH == "/healthz"


def test_inline_adapter_satisfies_protocol(client: TestClient) -> None:
    """The translator's ``AutoformalAdapter`` Protocol holds for the inline adapter."""
    from cds_harness.schema import Atom, SourceSpan
    from cds_harness.service.app import _InlineAdapter

    root = Atom(
        predicate="x",
        terms=[],
        source_span=SourceSpan(start=0, end=1, doc_id="x"),
    )
    inline = _InlineAdapter(root=root)
    # Structural conformance: callable signature matches the Protocol.
    adapter: AutoformalAdapter = inline  # type-checked structurally
    assert adapter.formalize(doc_id="x", text="x") is root
    del client  # fixture only used to keep app warm; suppresses unused warn


def test_resolve_host_and_port_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CDS_HARNESS_PORT", raising=False)
    monkeypatch.delenv("CDS_HARNESS_HOST", raising=False)
    assert resolve_host() == "127.0.0.1"
    assert resolve_port() == 8081


def test_resolve_port_rejects_garbage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CDS_HARNESS_PORT", "not-a-port")
    with pytest.raises(ValueError, match="not an integer"):
        resolve_port()
    monkeypatch.setenv("CDS_HARNESS_PORT", "70000")
    with pytest.raises(ValueError, match="outside"):
        resolve_port()
    monkeypatch.setenv("CDS_HARNESS_PORT", "9999")
    assert resolve_port() == 9999


def test_ingest_json_envelope_canonicalizes(client: TestClient) -> None:
    raw = json.loads(ICU_JSON.read_text(encoding="utf-8"))
    body = {"format": "json", "envelope": raw}
    response = client.post(INGEST_PATH, json=body)
    assert response.status_code == 200, response.text
    payload = response.json()["payload"]
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["source"]["device_id"] == "icu-monitor-02"
    assert len(payload["samples"]) == 2
    assert payload["samples"][0]["wall_clock_utc"].endswith("Z")
    # Map ordering is lexicographic; round-trip stays stable.
    vitals = payload["samples"][0]["vitals"]
    assert list(vitals.keys()) == sorted(vitals.keys())


def test_ingest_csv_inline_matches_disk_loader(client: TestClient) -> None:
    csv_text = ICU_CSV.read_text(encoding="utf-8")
    meta = json.loads(ICU_META.read_text(encoding="utf-8"))
    body = {
        "format": "csv",
        "csv_text": csv_text,
        "meta": meta,
        "file_label": ICU_CSV.name,
    }
    response = client.post(INGEST_PATH, json=body)
    assert response.status_code == 200, response.text
    payload = response.json()["payload"]
    assert payload["source"]["device_id"] == "icu-monitor-01"
    assert len(payload["samples"]) == 10
    bucketed = [s for s in payload["samples"] if s["events"]]
    assert len(bucketed) == 1
    assert bucketed[0]["events"][0]["name"] == "manual_bp_cuff_inflate"


def test_ingest_json_invalid_envelope_returns_422(client: TestClient) -> None:
    body = {"format": "json", "envelope": {"schema_version": SCHEMA_VERSION}}
    response = client.post(INGEST_PATH, json=body)
    assert response.status_code == 422


def test_ingest_csv_missing_source_returns_422(client: TestClient) -> None:
    csv_text = ICU_CSV.read_text(encoding="utf-8")
    body = {"format": "csv", "csv_text": csv_text, "meta": {"events": []}}
    response = client.post(INGEST_PATH, json=body)
    assert response.status_code == 422
    detail = response.json()
    assert detail["error"] == "ingest_error"
    assert "source" in detail["detail"]


def test_ingest_unknown_format_rejected(client: TestClient) -> None:
    response = client.post(INGEST_PATH, json={"format": "yaml", "envelope": {}})
    assert response.status_code == 422  # discriminator mismatch


def test_fhir_notification_collection_round_trips(client: TestClient) -> None:
    bundle = json.loads(FHIR_BUNDLE_02.read_text(encoding="utf-8"))
    response = client.post(FHIR_NOTIFICATION_PATH, json={"bundle": bundle})
    assert response.status_code == 200, response.text
    payload = response.json()["payload"]
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["source"]["device_id"] == "fhir:icu-monitor-02"
    assert payload["source"]["patient_pseudo_id"] == "pseudo-def456"
    assert len(payload["samples"]) == 2
    assert list(payload["samples"][0]["vitals"].keys()) == ["heart_rate_bpm", "spo2_percent"]


def test_fhir_notification_subscription_skips_status(client: TestClient) -> None:
    """A FHIR R5 notification Bundle (entry[0] = SubscriptionStatus) projects fine."""
    coll = json.loads(FHIR_BUNDLE_02.read_text(encoding="utf-8"))
    notification = {
        "resourceType": "Bundle",
        "id": "ntfn-svc-test",
        "type": "subscription-notification",
        "entry": [
            {
                "fullUrl": "urn:uuid:status",
                "resource": {
                    "resourceType": "SubscriptionStatus",
                    "status": "active",
                    "type": "event-notification",
                    "subscription": {"reference": "Subscription/sub-icu-01"},
                    "topic": "http://example.org/SubscriptionTopic/icu-vitals",
                },
            },
            *coll["entry"],
        ],
    }
    response = client.post(FHIR_NOTIFICATION_PATH, json={"bundle": notification})
    assert response.status_code == 200, response.text
    payload = response.json()["payload"]
    assert payload["source"]["device_id"] == "fhir:ntfn-svc-test"
    assert payload["source"]["patient_pseudo_id"] == "pseudo-def456"
    assert len(payload["samples"]) == 2


def test_fhir_notification_invalid_bundle_returns_422(client: TestClient) -> None:
    response = client.post(
        FHIR_NOTIFICATION_PATH,
        json={"bundle": {"resourceType": "Bundle", "type": "transaction"}},
    )
    assert response.status_code == 422
    detail = response.json()
    assert detail["error"] == "ingest_error"
    assert "unsupported Bundle.type" in detail["detail"]


def test_translate_happy_path_no_smt_check(client: TestClient) -> None:
    text = HYPOXEMIA_TXT.read_text(encoding="utf-8")
    recorded = json.loads(HYPOXEMIA_RECORDED.read_text(encoding="utf-8"))
    body = {
        "doc_id": "hypoxemia-trigger",
        "text": text,
        "root": recorded["root"],
    }
    response = client.post(TRANSLATE_PATH, json=body)
    assert response.status_code == 200, response.text
    out = response.json()
    assert out["smt_check"] is None
    assert out["tree"]["schema_version"] == SCHEMA_VERSION
    assert out["matrix"]["logic"] == "QF_LRA"
    assert len(out["matrix"]["assumptions"]) == 2


def test_translate_smt_check_consistent_returns_sat(client: TestClient) -> None:
    text = HYPOXEMIA_TXT.read_text(encoding="utf-8")
    recorded = json.loads(HYPOXEMIA_RECORDED.read_text(encoding="utf-8"))
    body = {
        "doc_id": "hypoxemia-trigger",
        "text": text,
        "root": recorded["root"],
        "smt_check": True,
    }
    response = client.post(TRANSLATE_PATH, json=body)
    assert response.status_code == 200
    assert response.json()["smt_check"] == "sat"


def test_translate_smt_check_contradictory_returns_unsat(client: TestClient) -> None:
    text = CONTRADICTORY_TXT.read_text(encoding="utf-8")
    recorded = json.loads(CONTRADICTORY_RECORDED.read_text(encoding="utf-8"))
    body = {
        "doc_id": "contradictory-bound",
        "text": text,
        "root": recorded["root"],
        "smt_check": True,
    }
    response = client.post(TRANSLATE_PATH, json=body)
    assert response.status_code == 200
    assert response.json()["smt_check"] == "unsat"


def test_translate_doc_id_mismatch_is_translate_error(client: TestClient) -> None:
    text = HYPOXEMIA_TXT.read_text(encoding="utf-8")
    recorded = json.loads(HYPOXEMIA_RECORDED.read_text(encoding="utf-8"))
    body = {
        "doc_id": "wrong-doc-id",
        "text": text,
        "root": recorded["root"],
    }
    response = client.post(TRANSLATE_PATH, json=body)
    assert response.status_code == 422
    detail = response.json()
    assert detail["error"] == "translate_error"
    assert "doc_id" in detail["detail"]


def test_translate_invalid_root_rejected(client: TestClient) -> None:
    body = {
        "doc_id": "x",
        "text": "x",
        "root": {"kind": "totally-bogus-kind"},
    }
    response = client.post(TRANSLATE_PATH, json=body)
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Sidecar smoke (Dapr service-invocation)


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_until_ready(url: str, *, deadline: float) -> None:
    """Probe ``url`` until it returns 2xx or the deadline expires."""
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
        f"readiness wait timed out for {url}: status={last_status} err={last_err!r}"
    )


@pytest.mark.skipif(
    not DAPR_CLI.is_file() or not DAPRD_BIN.is_file(),
    reason="dapr CLI / slim runtime not staged — run `just fetch-dapr`",
)
def test_dapr_sidecar_drives_ingest_and_translate(tmp_path: Path) -> None:
    """Smoke: dapr run → uvicorn → /v1/{ingest,translate} via service invocation."""
    timeout_bin = shutil.which("timeout")
    assert timeout_bin is not None, "GNU coreutils `timeout` required"

    app_port = _pick_free_port()
    dapr_http_port = _pick_free_port()
    dapr_grpc_port = _pick_free_port()
    metrics_port = _pick_free_port()

    env = os.environ.copy()
    env["CDS_HARNESS_HOST"] = "127.0.0.1"
    env["CDS_HARNESS_PORT"] = str(app_port)
    # Push uvicorn logs to stderr; let dapr take stdout.
    env["PYTHONUNBUFFERED"] = "1"

    log_path = tmp_path / "sidecar.log"
    stdout_handle = log_path.open("w", encoding="utf-8")

    cmd = [
        timeout_bin,
        "30",
        str(DAPR_CLI),
        "run",
        "--app-id",
        SERVICE_APP_ID,
        "--app-port",
        str(app_port),
        "--app-protocol",
        "http",
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
        sys.executable,
        "-m",
        "cds_harness.service",
        "--host",
        "127.0.0.1",
        "--port",
        str(app_port),
    ]

    proc = subprocess.Popen(
        cmd,
        stdout=stdout_handle,
        stderr=subprocess.STDOUT,
        env=env,
        text=True,
    )
    try:
        deadline = time.monotonic() + 25.0
        # `/v1.0/healthz` would return 503 until the placement service is
        # reachable; placement bring-up is deferred to Task 8.4 (ADR-016
        # §6). For Phase 0 service-invocation the right gate is
        # `/v1.0/healthz/outbound`, which flips ready as soon as daprd can
        # route calls to the app port.
        _wait_until_ready(f"http://127.0.0.1:{app_port}{HEALTHZ_PATH}", deadline=deadline)
        _wait_until_ready(
            f"http://127.0.0.1:{dapr_http_port}/v1.0/healthz/outbound",
            deadline=deadline,
        )

        invoke = f"http://127.0.0.1:{dapr_http_port}/v1.0/invoke/{SERVICE_APP_ID}/method"

        # /v1/ingest via service invocation
        envelope = json.loads(ICU_JSON.read_text(encoding="utf-8"))
        ingest_body: dict[str, Any] = {"format": "json", "envelope": envelope}
        response = httpx.post(f"{invoke}/v1/ingest", json=ingest_body, timeout=10.0)
        assert response.status_code == 200, response.text
        payload = response.json()["payload"]
        assert payload["source"]["device_id"] == "icu-monitor-02"

        # /v1/translate via service invocation
        text = HYPOXEMIA_TXT.read_text(encoding="utf-8")
        recorded = json.loads(HYPOXEMIA_RECORDED.read_text(encoding="utf-8"))
        translate_body: dict[str, Any] = {
            "doc_id": "hypoxemia-trigger",
            "text": text,
            "root": recorded["root"],
            "smt_check": True,
        }
        response = httpx.post(
            f"{invoke}/v1/translate", json=translate_body, timeout=20.0
        )
        assert response.status_code == 200, response.text
        out = response.json()
        assert out["smt_check"] == "sat"
        assert out["matrix"]["logic"] == "QF_LRA"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        stdout_handle.close()
