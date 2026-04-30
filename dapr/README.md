# Dapr — Phase 0 polyglot orchestration

This directory holds the Dapr 1.17 component manifests and Configuration
that the CDS Phase 0 pipeline runs under. Slim self-hosted mode (no
Docker / Redis / Zipkin) — the daprd, placement, and scheduler binaries
are staged under `.bin/.dapr/.dapr/bin/` by `just fetch-dapr`.

## Layout

| Path                                       | Role                                                                                                  |
| ------------------------------------------ | ----------------------------------------------------------------------------------------------------- |
| `components/pubsub-inmemory.yaml`          | `pubsub.in-memory` v1 — ephemeral, no external broker. Phase 0 only.                                  |
| `components/state-store-inmemory.yaml`     | `state.in-memory` v1 with `actorStateStore=true` — doubles as the Workflow state store.               |
| `config.yaml`                              | Dapr Configuration: tracing on stdout, metrics on, mTLS off (single dev host).                        |

## Justfile recipes

| Recipe              | Behaviour                                                                                              |
| ------------------- | ------------------------------------------------------------------------------------------------------ |
| `just fetch-dapr`   | Idempotent slim init under `.bin/.dapr/`. No-op if already populated.                                  |
| `just dapr-init`    | Force re-init. Clears `.bin/.dapr/.dapr/` first.                                                       |
| `just dapr-status`  | Prints CLI version, runtime version (`daprd --version`), and `.bin/.dapr/.dapr/bin/` manifest.         |
| `just dapr-clean`   | Removes `.bin/.dapr/`. `just fetch-dapr` to repopulate.                                                |
| `just dapr-smoke`   | Spawns `daprd` ~3 s against the project components dir, asserts both components load and shutdown clean. |

## Sidecar invocation contract (Phase 0)

Each app launches under

```
dapr run \
  --runtime-path .bin/.dapr \
  --app-id <cds-harness | cds-kernel> \
  --resources-path dapr/components \
  --config dapr/config.yaml \
  --app-protocol http \
  -- <command>
```

The Python harness sidecar binds in Task 8.2; the Rust kernel sidecar in
Task 8.3; the end-to-end Workflow orchestrator lands in Task 8.4. See
`.agent/Architecture_Decision_Log.md` ADR-016 for the rationale and the
locked component selections.

## Component lifecycle

Both in-memory components are scoped to the lifetime of a single daprd
process. Phase 0 accepts that any sidecar restart drops in-flight
Workflow state — the design assumption is that one pipeline run is one
daprd lifecycle. Phase 1+ swaps the state store to a durable backend
(SQLite or Postgres) so Workflow versioning and replay become available.
