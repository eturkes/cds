# Phase 1 Cloud — Kubernetes manifests + kind cluster bootstrap

> **Status:** Foundation (Task 11.1, ADR-028) + service deployment
> (Task 11.2, ADR-029). Observability stack (OpenTelemetry Collector
> / Prometheus / Grafana) lands at Task 11.3; end-to-end
> `contradictory-bound` smoke against the kind cluster closes the
> cloud axis at Task 11.4.

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

The matching Dockerfiles live under `docker/` (Task 11.2, ADR-029):
`docker/cds-{harness,kernel,frontend}.Dockerfile`. The repo-root
`.dockerignore` trims the build context so each image stays lean.

## Bring-up (operator workflow)

```sh
just fetch-cloud         # stages kind + kubectl + helm under .bin/
just fetch-bins          # stages .bin/{z3,cvc5} for the cds-kernel image
just kind-up             # spins up the kind cluster
just dapr-helm-install   # installs Dapr 1.17 control plane via helm
just cloud-build         # builds cds-{harness,kernel,frontend}:dev images
just cloud-load          # loads them into the kind cluster
just cloud-up            # applies namespace + config + components + workloads;
                         # waits for rollouts (5m timeout per Deployment)
just cloud-smoke         # in-cluster /healthz round-trip across the three apps
```

Status / inspection:

```sh
just cloud-status        # kubectl get pods/svc -n cds -o wide
just kind-status         # cluster + nodes + cross-namespace pod inventory
```

Tear-down:

```sh
just cloud-down          # deletes workloads + components + config + namespace
                         # (cluster preserved)
just kind-down           # destroys the kind cluster (helm install vanishes with it)
just cloud-clean         # alias for kind-down
```

## Container runtime

The `cloud-build` recipe defaults to `docker`. Override with
`DOCKER=podman` if podman is preferred — the build / load surface is
identical. Live builds require the host docker/podman daemon to be
running; the recipe gates on `command -v $DOCKER` and exits cleanly
with a loud notice if missing.

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
