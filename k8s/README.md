# Phase 1 Cloud — Kubernetes manifests + kind cluster bootstrap

> **Status:** Foundation only (Task 11.1, ADR-028). Container images
> + cluster bring-up smoke land at Task 11.2; observability stack
> (OpenTelemetry Collector / Prometheus / Grafana) lands at Task 11.3;
> end-to-end `contradictory-bound` smoke against the kind cluster
> closes the cloud axis at Task 11.4.

## Layout

| Path                                     | Purpose                                                                 |
| ---------------------------------------- | ----------------------------------------------------------------------- |
| `kind-cluster.yaml`                      | kind v0.31.0 cluster: 1 control-plane + 1 worker, kindest/node v1.35.0. |
| `namespaces.yaml`                        | The `cds` namespace (the `dapr-system` namespace is created by helm).   |
| `dapr-config.yaml`                       | `Configuration: cds-config` (mirror of `dapr/config.yaml`).             |
| `dapr-components/pubsub-inmemory.yaml`   | `cds-pubsub` (in-memory; namespaced to `cds`).                          |
| `dapr-components/state-store-inmemory.yaml` | `cds-statestore` (in-memory + actorStateStore=true).                  |
| `cds-harness.yaml`                       | Python harness Deployment + Service (8081, app-id `cds-harness`).       |
| `cds-kernel.yaml`                        | Rust kernel Deployment + Service (8082, app-id `cds-kernel`).           |
| `cds-frontend.yaml`                      | SvelteKit BFF Deployment + Service (3000, app-id `cds-frontend`).       |

## Bring-up (operator workflow)

```sh
just fetch-cloud         # stages kind + kubectl + helm under .bin/
just kind-up             # spins up the kind cluster
just dapr-helm-install   # installs Dapr 1.17 control plane via helm
kubectl apply -f k8s/namespaces.yaml
kubectl apply -f k8s/dapr-config.yaml
kubectl apply -f k8s/dapr-components/
# Container images + apply -f k8s/cds-*.yaml lands at Task 11.2.
```

Tear-down:

```sh
just kind-down           # destroys the kind cluster (helm install vanishes with it)
just cloud-clean         # alias for kind-down
```

## Versions (locked at decision time, ADR-028)

- **kind**: v0.31.0 (defaults to Kubernetes v1.35.0; kindest/node sha256-pinned).
- **kubectl**: v1.35.4 (matches kindest/node v1.35.0 minor; standard 1-minor skew permitted upstream).
- **helm**: v3.20.3 (parallel-stable v3 line; preserves Helm 3 chart compatibility for Dapr 1.17).
- **Dapr helm chart**: 1.17 (parity with the Phase 0 self-hosted lock; ADR-016 §3).

## Phase parity

The Phase 0 self-hosted recipes (`dapr-cluster-up`, `dapr-pipeline`,
`fhir-axis-smoke`) stay as the fast local-dev path. The cloud axis is
the *additional* deployment target — not a replacement for the
self-hosted path. Operators choose the path that fits their iteration
loop; the canonical `contradictory-bound` UNSAT fixture is the smoke
gate on both.
