"""Foundation tests for the Phase 1 cloud scaffold (Task 11.1, ADR-028).

Validates:
- The `k8s/` directory carries the expected manifests (kind cluster
  config, namespace, Dapr config + components, three cds-* Deployments
  + Services).
- Every YAML file parses and every doc declares `apiVersion` + `kind` +
  `metadata.name` (kind cluster config uses `kind.x-k8s.io/v1alpha4`
  with a top-level `name` instead of `metadata.name` — handled below).
- The kind cluster config is well-formed (1 control-plane + 1 worker;
  kindest/node v1.35.0 sha256-pinned; ingress port mappings present).
- Dapr Configuration / Components mirror the Phase 0 self-hosted shape
  (mTLS off; in-memory pubsub + state store with actorStateStore=true).
- Each cds-* manifest pair (Deployment + Service) carries the expected
  Dapr sidecar annotations and matching app-id / app-port.
- Service / Deployment label selectors agree on the `app: <name>` key
  so traffic routes correctly when applied to a live cluster.

This is a pure offline test — no kind / kubectl / helm binaries are
needed. The end-to-end cluster smoke (Task 11.4) is the live gate;
this file's job is to keep the manifests from drifting into invalid
shape between sessions.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
K8S_DIR = REPO_ROOT / "k8s"
KIND_CLUSTER_PATH = K8S_DIR / "kind-cluster.yaml"
NAMESPACES_PATH = K8S_DIR / "namespaces.yaml"
DAPR_CONFIG_PATH = K8S_DIR / "dapr-config.yaml"
DAPR_COMPONENTS_DIR = K8S_DIR / "dapr-components"
PUBSUB_PATH = DAPR_COMPONENTS_DIR / "pubsub-inmemory.yaml"
STATESTORE_PATH = DAPR_COMPONENTS_DIR / "state-store-inmemory.yaml"
HARNESS_PATH = K8S_DIR / "cds-harness.yaml"
KERNEL_PATH = K8S_DIR / "cds-kernel.yaml"
FRONTEND_PATH = K8S_DIR / "cds-frontend.yaml"

CDS_NAMESPACE = "cds"
EXPECTED_KINDEST_NODE = (
    "kindest/node:v1.35.0@"
    "sha256:452d707d4862f52530247495d180205e029056831160e22870e37e3f6c1ac31f"
)
EXPECTED_DAPR_APPS = {
    "cds-harness": {"port": 8081, "path": HARNESS_PATH},
    "cds-kernel": {"port": 8082, "path": KERNEL_PATH},
    "cds-frontend": {"port": 3000, "path": FRONTEND_PATH},
}


def _load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _load_yaml_all(path: Path) -> list[dict]:
    """Load every document in a multi-document YAML file."""
    with path.open("r", encoding="utf-8") as fh:
        return [doc for doc in yaml.safe_load_all(fh) if doc is not None]


def test_k8s_directory_exists() -> None:
    assert K8S_DIR.is_dir(), f"missing {K8S_DIR}"
    for path in (
        KIND_CLUSTER_PATH,
        NAMESPACES_PATH,
        DAPR_CONFIG_PATH,
        PUBSUB_PATH,
        STATESTORE_PATH,
        HARNESS_PATH,
        KERNEL_PATH,
        FRONTEND_PATH,
    ):
        assert path.is_file(), f"missing {path}"


def test_kind_cluster_config_well_formed() -> None:
    doc = _load_yaml(KIND_CLUSTER_PATH)
    assert doc["apiVersion"] == "kind.x-k8s.io/v1alpha4"
    assert doc["kind"] == "Cluster"
    assert doc["name"] == "cds"
    nodes = doc["nodes"]
    assert len(nodes) == 2, f"expected 1 control-plane + 1 worker; got {len(nodes)}"
    roles = [n["role"] for n in nodes]
    assert sorted(roles) == ["control-plane", "worker"]
    for node in nodes:
        assert node["image"] == EXPECTED_KINDEST_NODE, (
            f"node image drift on role={node['role']}: {node['image']!r}"
        )
    control = next(n for n in nodes if n["role"] == "control-plane")
    port_pairs = {(m["containerPort"], m["hostPort"]) for m in control["extraPortMappings"]}
    assert port_pairs == {(80, 8090), (443, 8443)}, (
        f"ingress port mappings drift: {port_pairs}"
    )
    patches = control["kubeadmConfigPatches"]
    assert any("ingress-ready=true" in p for p in patches), (
        "control-plane node missing ingress-ready=true label patch"
    )


def test_namespaces_manifest_well_formed() -> None:
    docs = _load_yaml_all(NAMESPACES_PATH)
    assert len(docs) == 1, f"expected exactly 1 Namespace doc; got {len(docs)}"
    ns = docs[0]
    assert ns["apiVersion"] == "v1"
    assert ns["kind"] == "Namespace"
    assert ns["metadata"]["name"] == CDS_NAMESPACE
    labels = ns["metadata"].get("labels", {})
    assert labels.get("app.kubernetes.io/part-of") == "cds"


def test_dapr_config_well_formed() -> None:
    """Phase 1 cloud Configuration shape — tracing routed via OTLP to
    the OpenTelemetry Collector in `cds-observability` (Task 11.3,
    ADR-030); mTLS off + metric on retain Phase 0 self-hosted parity.
    """
    doc = _load_yaml(DAPR_CONFIG_PATH)
    assert doc["apiVersion"] == "dapr.io/v1alpha1"
    assert doc["kind"] == "Configuration"
    assert doc["metadata"]["name"] == "cds-config"
    assert doc["metadata"]["namespace"] == CDS_NAMESPACE
    spec = doc["spec"]
    assert spec["tracing"]["samplingRate"] == "1"
    otel = spec["tracing"]["otel"]
    assert otel["endpointAddress"] == (
        "otel-collector-opentelemetry-collector."
        "cds-observability.svc.cluster.local:4317"
    )
    assert otel["isSecure"] is False
    assert otel["protocol"] == "grpc"
    assert spec["metric"]["enabled"] is True
    assert spec["mtls"]["enabled"] is False


def test_dapr_pubsub_component_well_formed() -> None:
    doc = _load_yaml(PUBSUB_PATH)
    assert doc["apiVersion"] == "dapr.io/v1alpha1"
    assert doc["kind"] == "Component"
    assert doc["metadata"]["name"] == "cds-pubsub"
    assert doc["metadata"]["namespace"] == CDS_NAMESPACE
    assert doc["spec"]["type"] == "pubsub.in-memory"
    assert doc["spec"]["version"] == "v1"


def test_dapr_state_store_component_well_formed() -> None:
    doc = _load_yaml(STATESTORE_PATH)
    assert doc["apiVersion"] == "dapr.io/v1alpha1"
    assert doc["kind"] == "Component"
    assert doc["metadata"]["name"] == "cds-statestore"
    assert doc["metadata"]["namespace"] == CDS_NAMESPACE
    assert doc["spec"]["type"] == "state.in-memory"
    assert doc["spec"]["version"] == "v1"
    metadata_kv = {entry["name"]: entry["value"] for entry in doc["spec"]["metadata"]}
    assert metadata_kv["actorStateStore"] == "true", (
        "Workflow engine on Dapr 1.17 requires actorStateStore=true"
    )


def test_dapr_component_namespace_uniformity() -> None:
    """Every Dapr resource in k8s/ binds to the `cds` namespace."""
    paths = [DAPR_CONFIG_PATH, PUBSUB_PATH, STATESTORE_PATH]
    for path in paths:
        for doc in _load_yaml_all(path):
            assert doc["metadata"]["namespace"] == CDS_NAMESPACE, (
                f"{path} doc {doc['metadata']['name']} not in `cds` namespace"
            )


def test_cds_workload_manifests_carry_paired_deployment_and_service() -> None:
    """Each cds-* manifest declares exactly one Deployment + one Service."""
    for app, info in EXPECTED_DAPR_APPS.items():
        path: Path = info["path"]
        docs = _load_yaml_all(path)
        kinds = sorted(doc["kind"] for doc in docs)
        assert kinds == ["Deployment", "Service"], (
            f"{path} (app={app}) expected Deployment+Service; got {kinds}"
        )
        for doc in docs:
            assert doc["metadata"]["name"] == app
            assert doc["metadata"]["namespace"] == CDS_NAMESPACE
            labels = doc["metadata"].get("labels", {})
            assert labels.get("app") == app
            assert labels.get("app.kubernetes.io/part-of") == "cds"


def test_cds_workload_dapr_annotations_are_consistent() -> None:
    """Sidecar annotations match Phase 0 self-hosted lock (ADR-016 / ADR-017)."""
    for app, info in EXPECTED_DAPR_APPS.items():
        path: Path = info["path"]
        port: int = info["port"]
        deployment = next(
            doc for doc in _load_yaml_all(path) if doc["kind"] == "Deployment"
        )
        annotations = deployment["spec"]["template"]["metadata"]["annotations"]
        assert annotations["dapr.io/enabled"] == "true"
        assert annotations["dapr.io/app-id"] == app
        assert annotations["dapr.io/app-port"] == str(port)
        assert annotations["dapr.io/app-protocol"] == "http"
        assert annotations["dapr.io/config"] == "cds-config"


def test_cds_workload_service_targets_deployment() -> None:
    """Service `spec.selector` agrees with Deployment `spec.template.metadata.labels`."""
    for app, info in EXPECTED_DAPR_APPS.items():
        path: Path = info["path"]
        port: int = info["port"]
        docs = _load_yaml_all(path)
        deployment = next(doc for doc in docs if doc["kind"] == "Deployment")
        service = next(doc for doc in docs if doc["kind"] == "Service")
        deploy_labels = deployment["spec"]["template"]["metadata"]["labels"]
        service_selector = service["spec"]["selector"]
        for key, value in service_selector.items():
            assert deploy_labels.get(key) == value, (
                f"{app}: Service selector {key}={value!r} not matched by Deployment "
                f"template label {deploy_labels.get(key)!r}"
            )
        service_ports = service["spec"]["ports"]
        assert len(service_ports) == 1, f"{app}: expected 1 service port"
        assert service_ports[0]["port"] == port
        container = deployment["spec"]["template"]["spec"]["containers"][0]
        container_ports = {p["containerPort"] for p in container["ports"]}
        assert port in container_ports, (
            f"{app}: container ports {container_ports} missing app-port {port}"
        )


def test_cds_workload_resource_floors_present() -> None:
    """Every cds-* container declares both requests + limits (production hygiene)."""
    for app, info in EXPECTED_DAPR_APPS.items():
        path: Path = info["path"]
        deployment = next(
            doc for doc in _load_yaml_all(path) if doc["kind"] == "Deployment"
        )
        container = deployment["spec"]["template"]["spec"]["containers"][0]
        resources = container.get("resources", {})
        for kind in ("requests", "limits"):
            assert kind in resources, f"{app}: container missing resources.{kind}"
            for key in ("cpu", "memory"):
                assert key in resources[kind], (
                    f"{app}: container resources.{kind} missing {key}"
                )


def test_cds_workload_image_tags_match_app_ids() -> None:
    """Image tags follow the `<app-id>:dev` convention (Task 11.2 builds them)."""
    for app, info in EXPECTED_DAPR_APPS.items():
        path: Path = info["path"]
        deployment = next(
            doc for doc in _load_yaml_all(path) if doc["kind"] == "Deployment"
        )
        container = deployment["spec"]["template"]["spec"]["containers"][0]
        assert container["image"] == f"{app}:dev", (
            f"{app}: image tag drift {container['image']!r}"
        )
        assert container["imagePullPolicy"] == "IfNotPresent", (
            f"{app}: imagePullPolicy must be IfNotPresent so kind-loaded images resolve"
        )


def test_cds_app_id_uniqueness() -> None:
    """No two Deployments share a `dapr.io/app-id` annotation."""
    seen: list[str] = []
    for info in EXPECTED_DAPR_APPS.values():
        deployment = next(
            doc for doc in _load_yaml_all(info["path"]) if doc["kind"] == "Deployment"
        )
        seen.append(deployment["spec"]["template"]["metadata"]["annotations"]["dapr.io/app-id"])
    assert len(seen) == len(set(seen)), f"duplicate dapr.io/app-id values: {seen}"


def test_cds_app_port_uniqueness() -> None:
    """No two cds-* services bind the same containerPort (avoids local-dev clashes)."""
    seen: list[int] = [info["port"] for info in EXPECTED_DAPR_APPS.values()]
    assert len(seen) == len(set(seen)), f"duplicate containerPort values: {seen}"
