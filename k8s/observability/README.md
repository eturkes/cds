# Phase 1 Cloud Observability — OpenTelemetry Collector + kube-prometheus-stack

> **Status:** Task 11.3 (ADR-030). Lights up tracing (Dapr → OTLP →
> OpenTelemetry Collector) + metrics (Dapr sidecars → Prometheus →
> Grafana) on the Phase 1 kind cluster. End-to-end span propagation
> from cds-harness → cds-kernel through OTLP plus a working Grafana
> dashboard query is the live close-out gate at Task 11.4.

## Layout

| Path                                      | Purpose                                                                                      |
| ----------------------------------------- | -------------------------------------------------------------------------------------------- |
| `namespace.yaml`                          | `cds-observability` namespace (kept distinct from `cds` so lifecycles are independent).       |
| `otel-collector-values.yaml`              | helm values for the OpenTelemetry Collector chart (OTLP gRPC :4317, OTLP HTTP :4318).         |
| `kube-prometheus-stack-values.yaml`       | helm values for kube-prometheus-stack (Prometheus + Grafana + node-exporter + KSM).           |
| `dapr-podmonitor.yaml`                    | Two PodMonitors — Dapr sidecars in `cds`, Dapr control plane in `dapr-system`.                |
| `grafana-dapr-dashboard-cm.yaml`          | Grafana dashboard ConfigMap (auto-loaded by the chart's grafana sidecar via label discovery). |

## Bring-up (operator workflow)

Pre-requisites: `just kind-up` + `just dapr-helm-install` (Task 11.1)
+ `just cloud-up` (Task 11.2) so the cds-* sidecars are running and
emitting metrics + traces before observability comes online.

```sh
just cloud-observability-up      # helm install otel-collector + kube-prometheus-stack;
                                 # apply PodMonitors + dashboard ConfigMap
just cloud-observability-status  # kubectl get pods/svc -n cds-observability
just cloud-observability-smoke   # in-cluster /healthz / /-/healthy / /api/health probes
```

Tear-down:

```sh
just cloud-observability-down    # helm uninstall releases + kubectl delete namespace
```

## Versions (locked at decision time, ADR-030)

- **OpenTelemetry Collector helm chart**: 0.146.1 (2026-04 stable line).
- **kube-prometheus-stack**: 84.5.0 (2026-03-30 release).
- **Dapr OTLP endpoint**: `otel-collector-opentelemetry-collector.cds-observability.svc.cluster.local:4317`
  (gRPC; insecure intra-cluster; matches the helm chart's default
  release-name → service-name pattern).

## Grafana access

```sh
kubectl --context kind-cds -n cds-observability port-forward svc/kube-prometheus-stack-grafana 3001:80
# open http://localhost:3001
# admin / cds-admin (overridable via grafana.adminPassword in the values file)
```

## Phase parity

The Phase 0 self-hosted recipes (`dapr-cluster-up`, `dapr-pipeline`,
`fhir-axis-smoke`) keep `tracing.stdout: true` for fast log inspection;
the Phase 1 cloud Configuration redirects tracing to the OTLP
collector so spans land in Grafana / Tempo-friendly format. Both
paths share the canonical `contradictory-bound` UNSAT smoke fixture
(verified end-to-end against the cluster at Task 11.4).
