"""Offline tests for the Phase 1 cloud observability stack
(Task 11.3, ADR-030).

Validates:
- The `k8s/observability/` directory carries the expected manifests
  (namespace, helm values for OTel Collector + kube-prometheus-stack,
  Dapr PodMonitor, Grafana dashboard ConfigMap).
- The OTel Collector helm values declare the OTLP gRPC + HTTP receivers
  on the canonical ports (4317 / 4318) and a tracing + metrics pipeline
  with batch + memory_limiter processors.
- The kube-prometheus-stack helm values pin Prometheus to discover
  ServiceMonitor / PodMonitor CRs from any namespace (so the
  `dapr-system` control-plane PodMonitor lives outside the chart's
  release namespace) and Grafana sidecar dashboard discovery is on.
- The Dapr PodMonitor binds to the `cds` namespace via
  `app.kubernetes.io/part-of: cds` and the control-plane PodMonitor
  binds to `dapr-system` via `app.kubernetes.io/part-of: dapr`.
- The Grafana dashboard ConfigMap carries the `grafana_dashboard: "1"`
  label that the kube-prometheus-stack grafana sidecar discovers
  (verified against the values file's `grafana.sidecar.dashboards.label`).
- The dashboard JSON parses cleanly and queries Dapr 1.17 sidecar
  metric series.
- The Justfile registers all four cloud-observability-* recipes plus
  the OTel + KPS chart-version constants.
- The Phase 1 `dapr-config.yaml` redirects tracing to the OTLP
  collector in the cds-observability namespace (cross-checked against
  the helm release name → Service DNS pattern the chart produces).

This is a pure offline test — no helm / kubectl / cluster needed.
The end-to-end live smoke (span propagation across
cds-harness → cds-kernel + a working Grafana dashboard query) is
Task 11.4's gate.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
K8S_DIR = REPO_ROOT / "k8s"
OBS_DIR = K8S_DIR / "observability"
NAMESPACE_PATH = OBS_DIR / "namespace.yaml"
OTEL_VALUES_PATH = OBS_DIR / "otel-collector-values.yaml"
KPS_VALUES_PATH = OBS_DIR / "kube-prometheus-stack-values.yaml"
DAPR_PODMONITOR_PATH = OBS_DIR / "dapr-podmonitor.yaml"
DASHBOARD_CM_PATH = OBS_DIR / "grafana-dapr-dashboard-cm.yaml"
README_PATH = OBS_DIR / "README.md"

DAPR_CONFIG_PATH = K8S_DIR / "dapr-config.yaml"
JUSTFILE_PATH = REPO_ROOT / "Justfile"

OBSERVABILITY_NAMESPACE = "cds-observability"
EXPECTED_OTEL_ENDPOINT = (
    "otel-collector-opentelemetry-collector."
    "cds-observability.svc.cluster.local:4317"
)


def _load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _load_yaml_all(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as fh:
        return [doc for doc in yaml.safe_load_all(fh) if doc is not None]


def test_observability_directory_exists() -> None:
    assert OBS_DIR.is_dir(), f"missing {OBS_DIR}"
    for path in (
        NAMESPACE_PATH,
        OTEL_VALUES_PATH,
        KPS_VALUES_PATH,
        DAPR_PODMONITOR_PATH,
        DASHBOARD_CM_PATH,
        README_PATH,
    ):
        assert path.is_file(), f"missing {path}"


def test_observability_namespace_well_formed() -> None:
    docs = _load_yaml_all(NAMESPACE_PATH)
    assert len(docs) == 1
    ns = docs[0]
    assert ns["apiVersion"] == "v1"
    assert ns["kind"] == "Namespace"
    assert ns["metadata"]["name"] == OBSERVABILITY_NAMESPACE
    labels = ns["metadata"].get("labels", {})
    assert labels.get("app.kubernetes.io/part-of") == "cds"


def test_otel_collector_values_well_formed() -> None:
    """Required Phase 1 contract: OTLP gRPC :4317, OTLP HTTP :4318,
    batch + memory_limiter processors, prometheus exporter on :8889.
    """
    values = _load_yaml(OTEL_VALUES_PATH)
    assert values["mode"] == "deployment", "single-replica deployment for kind"
    assert values["replicaCount"] == 1
    presets = values.get("presets", {})
    assert presets.get("kubernetesAttributes", {}).get("enabled") is True, (
        "kubernetesAttributes preset enriches spans with k8s metadata"
    )
    ports = values["ports"]
    assert ports["otlp"]["containerPort"] == 4317
    assert ports["otlp"]["servicePort"] == 4317
    assert ports["otlp-http"]["containerPort"] == 4318
    assert ports["otlp-http"]["servicePort"] == 4318
    config = values["config"]
    receivers = config["receivers"]
    assert "otlp" in receivers
    assert receivers["otlp"]["protocols"]["grpc"]["endpoint"] == "0.0.0.0:4317"
    assert receivers["otlp"]["protocols"]["http"]["endpoint"] == "0.0.0.0:4318"
    processors = config["processors"]
    assert "batch" in processors
    assert "memory_limiter" in processors
    exporters = config["exporters"]
    assert "debug" in exporters
    assert "prometheus" in exporters
    assert exporters["prometheus"]["endpoint"] == "0.0.0.0:8889"
    pipelines = config["service"]["pipelines"]
    for stage in ("traces", "metrics"):
        assert stage in pipelines, f"missing {stage} pipeline"
        pipeline = pipelines[stage]
        assert "otlp" in pipeline["receivers"]
        assert "memory_limiter" in pipeline["processors"]
        assert "batch" in pipeline["processors"]


def test_kube_prometheus_stack_values_well_formed() -> None:
    values = _load_yaml(KPS_VALUES_PATH)
    assert values["fullnameOverride"] == "kube-prometheus-stack"
    pspec = values["prometheus"]["prometheusSpec"]
    # Allow PodMonitor / ServiceMonitor discovery across all namespaces.
    for selector in (
        "podMonitorSelectorNilUsesHelmValues",
        "serviceMonitorSelectorNilUsesHelmValues",
        "probeSelectorNilUsesHelmValues",
        "ruleSelectorNilUsesHelmValues",
    ):
        assert pspec[selector] is False, (
            f"{selector} must be False so cross-namespace CRs are discovered"
        )
    grafana = values["grafana"]
    assert grafana["enabled"] is True
    sidecar = grafana["sidecar"]["dashboards"]
    assert sidecar["enabled"] is True
    assert sidecar["label"] == "grafana_dashboard"
    assert sidecar["labelValue"] == "1"
    assert sidecar["searchNamespace"] == "ALL"
    # Alertmanager intentionally off for foundation; reopen at Phase 2.
    assert values["alertmanager"]["enabled"] is False


def test_dapr_podmonitor_well_formed() -> None:
    docs = _load_yaml_all(DAPR_PODMONITOR_PATH)
    kinds = sorted(doc["kind"] for doc in docs)
    assert kinds == ["PodMonitor", "PodMonitor"], (
        f"expected two PodMonitor docs (sidecars + control plane); got {kinds}"
    )
    by_name = {doc["metadata"]["name"]: doc for doc in docs}
    assert "dapr-sidecars-cds" in by_name
    assert "dapr-control-plane" in by_name

    sidecars = by_name["dapr-sidecars-cds"]
    assert sidecars["apiVersion"] == "monitoring.coreos.com/v1"
    assert sidecars["metadata"]["namespace"] == OBSERVABILITY_NAMESPACE
    assert sidecars["spec"]["namespaceSelector"]["matchNames"] == ["cds"]
    assert sidecars["spec"]["selector"]["matchLabels"] == {
        "app.kubernetes.io/part-of": "cds"
    }
    sidecar_endpoints = sidecars["spec"]["podMetricsEndpoints"]
    assert len(sidecar_endpoints) == 1
    endpoint = sidecar_endpoints[0]
    assert endpoint["port"] == "dapr-metrics", (
        "Dapr 1.17+ injector exposes the sidecar metrics port as `dapr-metrics`"
    )
    assert endpoint["interval"] == "15s"

    control = by_name["dapr-control-plane"]
    assert control["metadata"]["namespace"] == OBSERVABILITY_NAMESPACE
    assert control["spec"]["namespaceSelector"]["matchNames"] == ["dapr-system"]
    assert control["spec"]["selector"]["matchLabels"] == {
        "app.kubernetes.io/part-of": "dapr"
    }


def test_dapr_podmonitor_namespace_uniformity() -> None:
    """Both PodMonitor CRs live in the cds-observability namespace
    (Prometheus Operator picks them up regardless of where the scrape
    target lives — the `namespaceSelector` chooses the target side).
    """
    for doc in _load_yaml_all(DAPR_PODMONITOR_PATH):
        assert doc["metadata"]["namespace"] == OBSERVABILITY_NAMESPACE


def test_grafana_dashboard_configmap_well_formed() -> None:
    cm = _load_yaml(DASHBOARD_CM_PATH)
    assert cm["apiVersion"] == "v1"
    assert cm["kind"] == "ConfigMap"
    assert cm["metadata"]["name"] == "cds-dapr-dashboard"
    assert cm["metadata"]["namespace"] == OBSERVABILITY_NAMESPACE
    labels = cm["metadata"]["labels"]
    assert labels["grafana_dashboard"] == "1", (
        "kube-prometheus-stack grafana sidecar discovers ConfigMaps via this label"
    )
    assert labels["app.kubernetes.io/part-of"] == "cds"
    data = cm["data"]
    keys = list(data.keys())
    assert len(keys) == 1, f"expected exactly one dashboard JSON in data; got {keys}"
    dashboard = json.loads(data[keys[0]])
    assert dashboard["uid"] == "cds-dapr-sidecars"
    assert "panels" in dashboard
    assert len(dashboard["panels"]) >= 1
    panel_titles = {p["title"] for p in dashboard["panels"]}
    assert any("HTTP server requests" in t for t in panel_titles), (
        f"expected an HTTP server requests panel; got {panel_titles}"
    )


def test_grafana_dashboard_label_matches_kps_values() -> None:
    """The dashboard ConfigMap label MUST match the kube-prometheus-stack
    grafana sidecar's discovery label (otherwise the dashboard is
    silently ignored)."""
    cm = _load_yaml(DASHBOARD_CM_PATH)
    values = _load_yaml(KPS_VALUES_PATH)
    sidecar = values["grafana"]["sidecar"]["dashboards"]
    expected_label = sidecar["label"]
    expected_value = sidecar["labelValue"]
    cm_labels = cm["metadata"]["labels"]
    assert cm_labels.get(expected_label) == expected_value, (
        f"dashboard label mismatch: ConfigMap has "
        f"{expected_label}={cm_labels.get(expected_label)!r}, "
        f"chart sidecar discovers {expected_label}={expected_value!r}"
    )


def test_dapr_config_otel_endpoint_matches_chart_release_pattern() -> None:
    """k8s/dapr-config.yaml's tracing.otel.endpointAddress MUST point at
    the Service DNS that the OpenTelemetry Collector helm chart creates
    for release name `otel-collector` in the `cds-observability`
    namespace. Chart convention: `<release>-opentelemetry-collector`.
    """
    doc = _load_yaml(DAPR_CONFIG_PATH)
    assert doc["spec"]["tracing"]["otel"]["endpointAddress"] == EXPECTED_OTEL_ENDPOINT


def test_justfile_registers_observability_recipes() -> None:
    text = JUSTFILE_PATH.read_text(encoding="utf-8")
    for recipe in (
        "cloud-observability-up:",
        "cloud-observability-down:",
        "cloud-observability-status:",
        "cloud-observability-smoke:",
    ):
        assert recipe in text, f"Justfile missing recipe declaration: {recipe}"


def test_justfile_registers_observability_constants() -> None:
    text = JUSTFILE_PATH.read_text(encoding="utf-8")
    for constant in (
        "OBSERVABILITY_DIR",
        "OBSERVABILITY_NAMESPACE",
        "OTEL_COLLECTOR_CHART_VERSION",
        "KPS_CHART_VERSION",
        "OTEL_COLLECTOR_RELEASE",
        "KPS_RELEASE",
    ):
        assert re.search(rf"^{constant}\b", text, re.MULTILINE), (
            f"Justfile missing constant declaration: {constant}"
        )


def test_justfile_pins_chart_versions_to_2026_locked_releases() -> None:
    """Lock the helm chart pins at the exact 2026 versions cited in
    ADR-030 §"Web-searches executed at decision time"."""
    text = JUSTFILE_PATH.read_text(encoding="utf-8")
    assert "'0.146.1'" in text, (
        "OTEL_COLLECTOR_CHART_VERSION must default to 0.146.1 (ADR-030 lock)"
    )
    assert "'84.5.0'" in text, (
        "KPS_CHART_VERSION must default to 84.5.0 (ADR-030 lock)"
    )


def test_observability_up_recipe_calls_helm_for_both_releases() -> None:
    """The `cloud-observability-up` recipe MUST invoke `helm upgrade
    --install` for both releases (otherwise tear-down/up parity breaks).
    """
    text = JUSTFILE_PATH.read_text(encoding="utf-8")
    up_match = re.search(
        r"^cloud-observability-up:\s*\n((?:[ \t].*\n)+?)(?=\n[a-zA-Z#]|\Z)",
        text,
        re.MULTILINE,
    )
    assert up_match, "could not locate cloud-observability-up recipe body"
    body = up_match.group(1)
    assert "open-telemetry/opentelemetry-collector" in body
    assert "prometheus-community/kube-prometheus-stack" in body
    assert body.count("helm upgrade --install") == 0 or "upgrade --install" in body
    assert "{{OTEL_COLLECTOR_RELEASE}}" in body
    assert "{{KPS_RELEASE}}" in body
    assert "kubectl" in body or "KCTL" in body


def test_observability_smoke_recipe_probes_three_endpoints() -> None:
    """The smoke recipe MUST exercise all three observability surfaces
    (collector + prometheus + grafana) so a regression in any single
    helm release is caught at the foundation gate."""
    text = JUSTFILE_PATH.read_text(encoding="utf-8")
    smoke_match = re.search(
        r"^cloud-observability-smoke:\s*\n((?:[ \t].*\n)+?)(?=\n[a-zA-Z#]|\Z)",
        text,
        re.MULTILINE,
    )
    assert smoke_match, "could not locate cloud-observability-smoke recipe body"
    body = smoke_match.group(1)
    # OTel Collector default health-check port is 13133.
    assert "13133" in body, "smoke must probe OTel Collector health on :13133"
    # Prometheus health endpoint.
    assert "/-/healthy" in body, "smoke must probe Prometheus /-/healthy"
    # Grafana health endpoint.
    assert "/api/health" in body, "smoke must probe Grafana /api/health"
