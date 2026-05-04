"""Offline tests for the Phase 1 cloud axis close-out (Task 11.4, ADR-031).

Validates:

- The Justfile registers the two close-out recipes (`cloud-axis-smoke` +
  `cloud-tear-down`) and the six `CLOUD_AXIS_*` constants.
- `cloud-axis-smoke` gates on `.bin/{kind,kubectl}`, uses
  `kubectl port-forward svc/cds-frontend`, drives the BFF `/api/*`
  surface, asserts `trace.sat == false` + `len(trace.muc) >= 2`, and
  probes Prometheus + the OTel Collector log stream.
- `cloud-tear-down` chains `cloud-observability-down` →
  `cloud-down` → `kind-down`.
- `k8s/cds-frontend.yaml` injects `DAPR_HTTP_PORT_HARNESS=3500` and
  `DAPR_HTTP_PORT_KERNEL=3500` so the BFF reaches the (single)
  in-pod daprd sidecar.
- The active Memory_Scratchpad pointer + Plan checklist row reflect
  Task 11.4 as DONE (catches future drift if a session forgets the
  close-out flip).

This is a pure offline test — no kind / kubectl / helm binaries
needed. The end-to-end live smoke is Task 11.4's runtime gate, run
manually via `just cloud-axis-smoke` after the cluster + cds-* +
observability stack are up.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
JUSTFILE_PATH = REPO_ROOT / "Justfile"
K8S_DIR = REPO_ROOT / "k8s"
FRONTEND_PATH = K8S_DIR / "cds-frontend.yaml"
README_PATH = K8S_DIR / "README.md"
PLAN_PATH = REPO_ROOT / ".agent" / "Plan.md"
SCRATCHPAD_PATH = REPO_ROOT / ".agent" / "Memory_Scratchpad.md"
ADR_PATH = REPO_ROOT / ".agent" / "Architecture_Decision_Log.md"

EXPECTED_CONSTANTS = (
    "CLOUD_AXIS_LOCAL_PORT",
    "CLOUD_AXIS_PAYLOAD",
    "CLOUD_AXIS_GUIDELINE",
    "CLOUD_AXIS_RECORDED",
    "CLOUD_AXIS_DOC_ID",
    "CLOUD_AXIS_HTTP_BUDGET",
)


def _load_yaml_all(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as fh:
        return [doc for doc in yaml.safe_load_all(fh) if doc is not None]


def test_justfile_registers_cloud_axis_recipes() -> None:
    text = JUSTFILE_PATH.read_text(encoding="utf-8")
    for recipe in ("cloud-axis-smoke:", "cloud-tear-down:"):
        assert recipe in text, f"Justfile missing recipe declaration: {recipe}"


def test_justfile_registers_cloud_axis_constants() -> None:
    text = JUSTFILE_PATH.read_text(encoding="utf-8")
    for constant in EXPECTED_CONSTANTS:
        assert re.search(rf"^{constant}\b", text, re.MULTILINE), (
            f"Justfile missing constant declaration: {constant}"
        )


def test_cloud_axis_smoke_gates_on_required_tooling() -> None:
    """The smoke recipe must gate on .bin/{kind,kubectl} + an active kind
    cluster + the cds-* deployments + the observability stack before
    driving traffic."""
    text = JUSTFILE_PATH.read_text(encoding="utf-8")
    section = _slice_recipe(text, "cloud-axis-smoke")
    for token in (
        '[ -x "$repo/.bin/kubectl" ]',
        '[ -x "$repo/.bin/kind" ]',
        '"$repo/.bin/kind" get clusters',
        "rollout status deployment/cds-frontend",
        "rollout status deployment/cds-harness",
        "rollout status deployment/cds-kernel",
    ):
        assert token in section, f"cloud-axis-smoke missing gate: {token!r}"


def test_cloud_axis_smoke_drives_bff_via_port_forward() -> None:
    """The smoke must use `kubectl port-forward svc/cds-frontend` and
    drive `/api/{ingest,translate,deduce,solve}` against the BFF."""
    text = JUSTFILE_PATH.read_text(encoding="utf-8")
    section = _slice_recipe(text, "cloud-axis-smoke")
    assert "port-forward svc/cds-frontend" in section, (
        "cloud-axis-smoke must port-forward the cds-frontend Service"
    )
    for path in ("api/ingest", "api/translate", "api/deduce", "api/solve"):
        assert path in section, f"cloud-axis-smoke missing BFF call to /{path}"


def test_cloud_axis_smoke_asserts_unsat_verdict() -> None:
    text = JUSTFILE_PATH.read_text(encoding="utf-8")
    section = _slice_recipe(text, "cloud-axis-smoke")
    assert "trace.get('sat') is False" in section, (
        "cloud-axis-smoke must assert UNSAT (trace.sat == False)"
    )
    assert "len(trace['muc']) >= 2" in section, (
        "cloud-axis-smoke must assert MUC has >=2 entries"
    )


def test_cloud_axis_smoke_recheck_is_optional() -> None:
    """Recheck assertion is opt-in via CDS_KIMINA_URL (per ADR-031 §
    'Why CDS_KIMINA_URL is opt-in')."""
    text = JUSTFILE_PATH.read_text(encoding="utf-8")
    section = _slice_recipe(text, "cloud-axis-smoke")
    assert "KIMINA_URL=\"${CDS_KIMINA_URL:-}\"" in section, (
        "cloud-axis-smoke must read CDS_KIMINA_URL from environment"
    )
    assert "if os.environ.get('KIMINA_URL'):" in section, (
        "cloud-axis-smoke must guard /api/recheck behind a non-empty CDS_KIMINA_URL"
    )
    assert "/api/recheck SKIPPED" in section, (
        "cloud-axis-smoke must announce when recheck is skipped"
    )


def test_cloud_axis_smoke_probes_prometheus() -> None:
    """The smoke must query Prometheus for `dapr_http_server_request_count`
    cardinality from inside the cluster (the metric proves the Dapr
    PodMonitor scrape is wired through ADR-030)."""
    text = JUSTFILE_PATH.read_text(encoding="utf-8")
    section = _slice_recipe(text, "cloud-axis-smoke")
    assert "count(dapr_http_server_request_count)" in section, (
        "cloud-axis-smoke must query Prometheus for the Dapr request-count metric"
    )
    assert "/api/v1/query" in section, (
        "cloud-axis-smoke must use the Prometheus HTTP query API"
    )
    assert "{{KPS_RELEASE}}-prometheus" in section, (
        "cloud-axis-smoke must hit the kube-prometheus-stack Prometheus Service "
        "DNS in the observability namespace"
    )


def test_cloud_axis_smoke_probes_otel_collector_logs() -> None:
    """The smoke must inspect OTel Collector logs for spans tagged with
    both cds-harness and cds-kernel (proves Dapr → OTLP → Collector
    propagation across the service-invocation hop)."""
    text = JUSTFILE_PATH.read_text(encoding="utf-8")
    section = _slice_recipe(text, "cloud-axis-smoke")
    assert "{{OTEL_COLLECTOR_RELEASE}}-opentelemetry-collector" in section, (
        "cloud-axis-smoke must address the OTel Collector deployment by chart "
        "release-name → service-name pattern"
    )
    assert "kubectl logs" not in section, (
        "cloud-axis-smoke uses the staged .bin/kubectl, not a bare kubectl"
    )
    assert 'logs \\' in section, (
        "cloud-axis-smoke must read collector logs (debug exporter dumps spans)"
    )
    assert 'grep -c "cds-harness"' in section
    assert 'grep -c "cds-kernel"' in section


def test_cloud_axis_smoke_observability_skip_flag() -> None:
    """Observability probes must be bypassable via CLOUD_AXIS_SKIP_OBS=1
    so a non-observability-equipped operator can still drive the BFF
    smoke (e.g., when cloud-observability-up is intentionally
    deferred)."""
    text = JUSTFILE_PATH.read_text(encoding="utf-8")
    section = _slice_recipe(text, "cloud-axis-smoke")
    assert "CLOUD_AXIS_SKIP_OBS:-0" in section, (
        "cloud-axis-smoke must honour CLOUD_AXIS_SKIP_OBS=1 as a bypass"
    )


def test_cloud_axis_smoke_cleans_up_port_forward() -> None:
    """A `trap cleanup EXIT INT TERM` must rewind the port-forward."""
    text = JUSTFILE_PATH.read_text(encoding="utf-8")
    section = _slice_recipe(text, "cloud-axis-smoke")
    assert "trap cleanup EXIT INT TERM" in section, (
        "cloud-axis-smoke must register an exit trap for port-forward cleanup"
    )
    assert "kill -TERM" in section
    assert "kill -KILL" in section


def test_cloud_tear_down_chains_three_stages() -> None:
    text = JUSTFILE_PATH.read_text(encoding="utf-8")
    section = _slice_recipe(text, "cloud-tear-down")
    for stage in (
        "just cloud-observability-down",
        "just cloud-down",
        "just kind-down",
    ):
        assert stage in section, f"cloud-tear-down missing stage: {stage}"


def test_cds_frontend_injects_dapr_http_ports() -> None:
    """In K8s, the BFF and its daprd sidecar share a Pod. Both
    `DAPR_HTTP_PORT_HARNESS` and `DAPR_HTTP_PORT_KERNEL` must point at
    the (single) sidecar port 3500 so service-invocation routes for
    both upstream apps land on the local daprd."""
    docs = _load_yaml_all(FRONTEND_PATH)
    deployment = next(doc for doc in docs if doc["kind"] == "Deployment")
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    env = {entry["name"]: entry["value"] for entry in container.get("env", [])}
    harness_port = env.get("DAPR_HTTP_PORT_HARNESS")
    assert harness_port == "3500", (
        f"DAPR_HTTP_PORT_HARNESS must be 3500 (in-pod sidecar); got {harness_port!r}"
    )
    kernel_port = env.get("DAPR_HTTP_PORT_KERNEL")
    assert kernel_port == "3500", (
        f"DAPR_HTTP_PORT_KERNEL must be 3500 (in-pod sidecar); got {kernel_port!r}"
    )


def test_k8s_readme_advertises_cloud_axis_smoke() -> None:
    text = README_PATH.read_text(encoding="utf-8")
    assert "cloud-axis-smoke" in text, "k8s/README.md missing cloud-axis-smoke row"
    assert "cloud-tear-down" in text, "k8s/README.md missing cloud-tear-down row"
    assert "Cloud axis CLOSED" in text, (
        "k8s/README.md banner must announce the cloud-axis closure"
    )


def test_plan_marks_task_11_4_done() -> None:
    text = PLAN_PATH.read_text(encoding="utf-8")
    # Match the row regardless of whether its inline label changed.
    pattern = re.compile(r"\|\s*11\.4\s*\|.+?\|\s*\*\*DONE\*\*", re.DOTALL)
    assert pattern.search(text), "Plan.md row 11.4 must be marked **DONE**"
    assert "FHIR axis closed" in text  # Phase 1 axis 10 banner is still present
    assert "cloud axis closed" in text.lower(), (
        "Plan.md must announce the cloud axis closure somewhere (header / banner)"
    )


def test_scratchpad_pointer_advances_past_11_4() -> None:
    text = SCRATCHPAD_PATH.read_text(encoding="utf-8")
    assert "Task 11.4" in text, "Memory_Scratchpad must mention Task 11.4"
    # The active task pointer block lives at the top under "Active task pointer".
    head = text.split("##", 1)[0] + text.split("## ", 2)[1]
    assert "Last completed:" in head
    assert (
        "Task 11.4" in head or "11.4" in head
    ), "Scratchpad active-pointer block must reference 11.4 as last completed"


def test_adr_031_present() -> None:
    text = ADR_PATH.read_text(encoding="utf-8")
    assert "ADR-031" in text, "Architecture_Decision_Log.md missing ADR-031 entry"
    # Sanity: ADR title mentions the close-out scope.
    assert re.search(
        r"^## ADR-031.+(close-out|cloud axis)", text, re.MULTILINE | re.IGNORECASE
    ), "ADR-031 title should reference the cloud axis close-out"


# -----------------------------------------------------------------------------
# Internal helpers
# -----------------------------------------------------------------------------


def _slice_recipe(justfile_text: str, recipe_name: str) -> str:
    """Return the body of a recipe between its `<name>:` declaration and the
    next blank-line-terminated section divider. Token-based matching is
    enough — the Justfile keeps each recipe in its own indented block.
    """
    lines = justfile_text.splitlines()
    start: int | None = None
    for idx, line in enumerate(lines):
        if line.startswith(f"{recipe_name}:"):
            start = idx
            break
    assert start is not None, f"recipe {recipe_name!r} not found in Justfile"
    end = len(lines)
    for idx in range(start + 1, len(lines)):
        line = lines[idx]
        # Section divider — recipes are followed by a blank line then a
        # comment header `# ===...` for the next section, OR by another
        # bare-identifier recipe declaration at column 0.
        divider = "# " + "=" * 77
        if line.startswith(divider) and idx > start + 5:
            end = idx
            break
        if line and not line.startswith((" ", "\t", "#")) and ":" in line and idx > start + 5:
            end = idx
            break
    return "\n".join(lines[start:end])
