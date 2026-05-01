# Memory Scratchpad

> Ephemeral working memory between sessions. Append at top; prune aggressively. Authoritative state lives in `Plan.md` + `Architecture_Decision_Log.md`.

---

## Active task pointer

- **Last completed:** Task 8.4a — Dapr cluster bring-up + production SIGTERM-first warden (ADR-021 §2). Promoted `nix = { ..., features = ["signal"] }` from kernel `[dev-dependencies]` to `[dependencies]` (single entry now serves both the production warden + the dapr-CLI cleanup helper in `tests/common.rs`). Refactored `crate::solver::warden::run_with_input` to a two-stage shutdown — `pin!(child.wait_with_output())`; on wall-clock timeout send `SIGTERM` via `nix::sys::signal::kill(Pid::from_raw(...), Signal::SIGTERM)`, wait up to a new `SIGTERM_GRACE` const (500 ms — Phase 0 default per ADR-021 §2), fall through to `kill_on_drop`'s `SIGKILL` by letting the pinned future drop at end-of-scope (no explicit `drop(collect)` — clippy::drop_non_drop forbids it on a `Pin<&mut Future>`). `WardenError::Timeout { bin, timeout }` shape preserved (call sites in `solver::z3` / `solver::cvc5` / `service::handlers` / `service::errors` untouched). Added two new warden tests: `timeout_sigterm_first_when_child_traps_term` (`bash -c 'trap "exit 0" TERM; while :; do sleep 1; done'` exits within grace; assert `Timeout` + elapsed ≤ wall_clock + grace + slack) and `timeout_sigkill_fallback_when_child_ignores_term` (`bash -c 'trap "" TERM; ...'` ignores TERM; assert `Timeout` + elapsed ∈ `[wall_clock + grace, wall_clock + grace + 2s]`). Added Justfile recipes `placement-up`, `placement-down`, `scheduler-up`, `scheduler-down`, `dapr-cluster-up` (placement-up + scheduler-up), `dapr-cluster-down` (reverse-order teardown), `dapr-cluster-status`. Each `*-up` recipe `nohup`-spawns the slim binary in background (PID → `target/dapr-<name>.pid`, log → `target/dapr-<name>.log`), idempotent (skips if pid-file PID is alive), liveness-probes via `kill -0` after a short settle window. Each `*-down` recipe is SIGTERM → 3-second grace polled in 100 ms ticks → SIGKILL. Pinned bind ports avoid the 8080/9090 healthz/metrics collision when both binaries run side-by-side: placement gRPC :50005 / healthz :50007 / metrics :50008; scheduler gRPC :50006 / healthz :50009 / metrics :50010. Scheduler embedded etcd writes under `target/dapr-scheduler-etcd/` (overrides upstream `./data` default that would otherwise collide with this repo's genuine telemetry dir). Per ADR-021 §5 the readiness gate `tests/common::wait_until_ready` floor stays at `/v1.0/healthz/outbound` so the existing five daprd-driven integration tests stay green both cluster-up and cluster-down (a developer running `just rs-service-{smoke,pipeline-smoke}` without bringing the cluster up first still gets a green run); rationale documented in the helper's doc-comment + the call-site comments. **8.4b** will additionally pre-flight `/v1.0/healthz` after starting the cluster. **SIGTERM-first deferral closed** — ADR-014 §9 → ADR-015 §8 → ADR-016 §7 → ADR-018 §6 → ADR-019 §11 → ADR-020 §6 is now ratified. Gate: `cargo test --workspace` → **153 pass** (151 baseline + 2 new warden cases); `cargo clippy --workspace --all-targets -- -D warnings` clean; `cargo fmt --all -- --check` clean; `uv run pytest` 95/95; `uv run ruff check .` clean; `just env-verify` exit 0; `just dapr-cluster-up` + `dapr-cluster-status` print PIDs (placement healthz 200; scheduler healthz 200) and `dapr-cluster-down` reclaims both children; `just rs-service-pipeline-smoke` + `just rs-service-smoke` both green against a cluster-up sidecar.
- **Next up:** Task 8.4b — End-to-end Dapr Workflow + close-out of Task 8 (ADR-021 §3). New `cds_harness.workflow` package (`__init__.py` + `pipeline.py` + `activities.py` + `__main__.py`); five `@activity` callables (`ingest`, `translate`, `deduce`, `solve`, `recheck`), each a thin `httpx`-over-daprd wrapper; introduce Dapr Python SDK (ADR-017 §5 reversed — `dapr>=1.17` + `dapr-ext-workflow>=1.17` in `[project.dependencies]`) for `WorkflowRuntime` + `@workflow` / `@activity` decorators + replay semantics + activity-id-tagged tracing; aggregated in-band JSON envelope `{ payload, ir, matrix, verdict, trace, recheck }` (Phase 0 small payloads + replay determinism + JSON-over-TCP discipline preferred over state-store handles per ADR-021 §7); per-stage `tracing` spans correlated through Workflow activity-id; `just dapr-pipeline` orchestrator (`dapr-cluster-up` → `py-service-dapr` → `rs-service-dapr` → `python -m cds_harness.workflow run-pipeline` → assert three flags → reverse teardown); end-to-end pytest smoke `python/tests/test_dapr_pipeline.py` (gated on full bin set + `CDS_KIMINA_URL`). 8.4b's pipeline test should additionally pre-flight `/v1.0/healthz` after starting the cluster (per the floor decision in 8.4a). Final close-out gate: `just dapr-pipeline` end-to-end against `data/guidelines/contradictory-bound.txt` returns `verdict ∧ trace.sat=false ∧ recheck.ok=true`; manual run on `data/guidelines/hypoxemia-trigger.txt` returns `verdict ∧ trace.sat=true ∧ recheck.ok=true`. **This closes Task 8.**

> **Task 8 was split** into 8.1–8.4 on 2026-04-30 (ADR-016) because a monolithic Dapr-orchestration task repeatedly exhausted a single context window. **Task 8.3 was further split** into 8.3a / 8.3b on 2026-04-30 (ADR-018) because the kernel service binds three subprocess pipelines (`deduce`, `solve`, `recheck`) behind one axum app and the foundation + endpoint plumbing each warrant their own session. **Task 8.3b was further split** into 8.3b1 / 8.3b2 on 2026-05-01 (ADR-019) because the original 8.3b scope (three handlers + their `IntoResponse` impls + comprehensive unit tests + `AppState` wiring + a Dapr-driven cargo integration test driving all three endpoints through daprd) again exceeded a single context window. **Task 8.3b2 was further split** into 8.3b2a / 8.3b2b on 2026-05-01 (ADR-020) because the original 8.3b2 scope (`AppState` introduction + env-driven option resolution + handler refactor onto `axum::extract::State` + shared smoke helpers + three daprd-driven cargo integration tests) again exceeded a single context window — and the external-dependency gate of solve/recheck (`.bin/z3`, `.bin/cvc5`, `CDS_KIMINA_URL`) cleanly separates from the dependency-free `/v1/deduce` smoke + the foundation refactor. **Task 8.4 was further split** into 8.4a / 8.4b on 2026-05-01 (ADR-021) because the original 8.4 scope (placement+scheduler bring-up + production SIGTERM-first warden escalation + readiness gate flip + Python `cds_harness.workflow` package + Dapr Python SDK introduction + aggregated envelope + per-stage tracing + `just dapr-pipeline` + end-to-end pytest smoke) again exceeded a single context window — and the Rust-foundation vs. Python-composition boundary cleanly separates the cluster bring-up + warden refactor from the Workflow harness composition. Sub-task progression is strict: `8.1 < 8.2 < 8.3a < 8.3b1 < 8.3b2a < 8.3b2b < 8.4a < 8.4b < 9`.

## Session 2026-05-01 — Task 8.4a close-out

Closed the Rust-foundation half of Task 8.4 per ADR-021 §2 + §5 — the
six-times-deferred SIGTERM-first warden escalation (014 §9 → 015 §8 →
016 §7 → 018 §6 → 019 §11 → 020 §6) and the new
placement+scheduler bring-up recipes that 8.4b's Workflow harness
needs to schedule activities. No Python touchpoints; no kernel
endpoint changes; no schema changes. The Rust workspace + Justfile
round-trip cleanly against both cluster-up and cluster-down sidecar
states.

**Code additions (`crates/kernel/src/solver/warden.rs`):**

| Item                                        | Role                                                                                                                                                                                     |
| ------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `pub const SIGTERM_GRACE: Duration`         | New: 500 ms grace window between `SIGTERM` and the `kill_on_drop` `SIGKILL` fallback. ADR-021 §2 tunable-in-source — preserves the call-surface (no grace param) so all existing solver / handler call sites keep their signatures. |
| `run_with_input` — two-stage shutdown      | Refactor: capture `child.id()` before stdin write; `pin!(child.wait_with_output())` so we can keep the future after `tokio::time::timeout` expires; on first-stage timeout send `SIGTERM` via `nix::sys::signal::kill(Pid::from_raw(pid_i32), Signal::SIGTERM)` (ESRCH/EPERM ignored — child may have already exited racing with the timeout); second `tokio::time::timeout(SIGTERM_GRACE, collect.as_mut())` waits for graceful exit; either branch returns `WardenError::Timeout` (the wall-clock budget was exceeded — only the kill mechanism differs). The pinned future drops at end-of-scope, which drops its inner `Child`, which delivers `SIGKILL` via `kill_on_drop` on the SIGTERM-ignored path. No explicit `drop(collect)` — clippy::drop_non_drop forbids dropping a `Pin<&mut Future>`. |
| `nix` runtime dependency                   | Promotion: `crates/kernel/Cargo.toml` moves `nix = { version = "0.31", default-features = false, features = ["signal"] }` from `[dev-dependencies]` to `[dependencies]`. Single entry now serves both the production warden + the dapr-CLI cleanup helper in `tests/common.rs` (ADR-018 §6 narrow auth, now superseded by ADR-021 §4 broader auth for the production path). |
| Module doc-comment                         | Refresh: items 1–3 of the warden invariants now reference ADR-004 + ADR-021 §2 jointly. Item 2 explicitly documents the two-stage `SIGTERM → SIGTERM_GRACE → SIGKILL` shape. Item 1 (`kill_on_drop`) and item 3 (no signal handlers in worker tasks) carry through unchanged.                                                          |

**Test additions (`crates/kernel/src/solver/warden.rs::tests`):**

| Test                                               | Coverage                                                                                                                                                                |
| -------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `timeout_sigterm_first_when_child_traps_term`     | `/bin/bash -c 'trap "exit 0" TERM; while :; do sleep 1; done'` — child exits cleanly on SIGTERM. wall_clock=150 ms, grace=500 ms. Asserts `WardenError::Timeout` (budget exceeded) + elapsed ∈ `[wall_clock, wall_clock + SIGTERM_GRACE + 500 ms slack]`. Validates the SIGTERM-first stage. |
| `timeout_sigkill_fallback_when_child_ignores_term` | `/bin/bash -c 'trap "" TERM; while :; do sleep 1; done'` — child masks TERM. wall_clock=150 ms, grace=500 ms. Asserts `WardenError::Timeout` + elapsed ∈ `[wall_clock + SIGTERM_GRACE, wall_clock + SIGTERM_GRACE + 2s]`. Validates the `kill_on_drop` SIGKILL fallback. |

Both tests are hermetic on any Linux dev host (require `/bin/bash`).

**Justfile additions (cluster bring-up block, after `dapr-smoke`):**

| Recipe / variable                                 | Role                                                                                                                                                                                       |
| ------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `DAPR_PLACEMENT_BIN` / `DAPR_SCHEDULER_BIN`       | Resolve to `.bin/.dapr/.dapr/bin/{placement,scheduler}` (slim staging from `fetch-dapr`). |
| `DAPR_CLUSTER_DIR`                                | `target/` — pid-files + log files live alongside cargo build output so `cargo clean` reclaims them. |
| Pinned port vars                                   | `DAPR_PLACEMENT_PORT=50005` / `DAPR_PLACEMENT_HZ=50007` / `DAPR_PLACEMENT_MET=50008`; `DAPR_SCHEDULER_PORT=50006` / `DAPR_SCHEDULER_HZ=50009` / `DAPR_SCHEDULER_MET=50010`. The healthz/metrics defaults of 8080/9090 collide between the two binaries — explicit pins avoid that. All `env_var_or_default` so a developer can override per-invocation. |
| `placement-up` / `scheduler-up`                    | `nohup`-spawn the binary in background, `--listen-address 127.0.0.1` to confine to localhost, `--healthz-listen-address 127.0.0.1` likewise, `--log-level info`. Pid file + log file under `target/`. Idempotent: if pid-file PID is alive, print "already up" and exit 0. After spawn, sleep brief settle window (placement 0.4 s; scheduler 1.0 s — etcd quorum boot is slower) and `kill -0` probe the PID; if dead, print log tail + exit 1. Scheduler additionally takes `--etcd-data-dir target/dapr-scheduler-etcd/` to override upstream `./data` default that would otherwise stomp this repo's genuine telemetry dir. |
| `placement-down` / `scheduler-down`                | If pid-file absent or stale → no-op + cleanup. Else SIGTERM via `kill -TERM`; poll `kill -0` in 100 ms ticks for 3 s (placement) / 5 s (scheduler); on grace expiry SIGKILL via `kill -KILL`; remove pid-file. Print `✓ <name> down (pid=<pid>)` on success.                                                                       |
| `dapr-cluster-up`                                  | Aggregator dependency: `placement-up scheduler-up`. Idempotent transitively.                                                                                                                                                                  |
| `dapr-cluster-down`                                | Aggregator dependency: `scheduler-down placement-down` (reverse order).                                                                                                                                                                       |
| `dapr-cluster-status`                              | Inline `print_one` bash function called twice (placement + scheduler). Printout per child: `up` (with pid + grpc + healthz + log path) or `STALE` (pid-file present but PID gone) or `down` (no pid-file). Useful operationally + for 8.4b's Workflow smoke pre-flight. |

**Readiness gate floor — kept at `/v1.0/healthz/outbound` (ADR-021 §5).**
The existing five daprd-driven integration tests
(`tests/service_smoke.rs::dapr_sidecar_drives_*` x3 +
`tests/service_pipeline_smoke.rs::dapr_sidecar_drives_*` x2) all
target `/v1.0/healthz/outbound` (204) per ADR-017 §4 / ADR-018 §5
because Phase 0 placement was down. ADR-021 §5 made the flip to
`/v1.0/healthz` (full readiness, requires placement) **optional** in
8.4a. Decision this session: **keep `outbound` as the floor.**
Rationale:

1. The existing tests pass green both cluster-up (verified this
   session: 3/3 service_smoke + 2/2 service_pipeline_smoke against a
   bring-up sidecar) and cluster-down (verified historically across
   8.3a / 8.3b1 / 8.3b2a / 8.3b2b). Flipping to `/v1.0/healthz` would
   make them require a cluster, regressing the developer ergonomics
   of `just rs-service-{smoke,pipeline-smoke}`.
2. 8.4b's Workflow pipeline test will pre-flight `/v1.0/healthz`
   after starting the cluster — it's the only test that *needs*
   placement to be up (Workflow can't schedule activities otherwise),
   so the additional probe lives there.
3. The doc-comment on `tests/common::wait_until_ready` now carries
   the rationale + the 8.4a decision so a future session reading the
   helper doesn't have to grep ADRs to understand "why outbound and
   not healthz?"

**Subprocess hygiene — production path now matches the test path.**
Pre-8.4a, `tests/common::sigterm_then_kill` was the only SIGTERM-first
shape in the repo (narrow auth, dapr-CLI only). 8.4a brings the
production warden into the same discipline (`SIGTERM` first, grace,
then `SIGKILL` via `kill_on_drop`). The `WardenError` API is unchanged
so consumers (`solver::z3`, `solver::cvc5`, `service::handlers`,
`service::errors`) need no edits. `tests/common::sigterm_then_kill`
stays as-is because it kills *the dapr CLI itself* (which orchestrates
its own grandchildren's termination) and not a single solver child.

**Why 8.4a and not earlier?** Per ADR-021 §4: Workflow's
retry-against-long-running-proof failure mode is the operational
pressure that finally tips the trade. SIGKILL-only on a 2-clause
contradictory-bound matrix (10s of ms) is fine; SIGKILL-only on a
multi-second proof under Workflow retries leaks partial state. The
two-stage shape gives cvc5 a chance to flush its Alethe stream
on `SIGTERM`.

**Final regression gate (this session, post-cluster-down):**

- `cargo test --workspace` → **153 pass** (151 baseline + 2 new warden cases).
- `cargo clippy --workspace --all-targets -- -D warnings` → clean.
- `cargo fmt --all -- --check` → clean.
- `uv run pytest` → 95 pass.
- `uv run ruff check .` → clean.
- `just env-verify` → exit 0 (the `.bin/ empty` notice is a
  pre-existing SIGPIPE quirk in the recipe under `pipefail`; the
  recipe itself exits 0 because `fail=0` is the only signal).
- `just dapr-cluster-up` + `dapr-cluster-status` print both PIDs +
  ports; placement healthz 200; scheduler healthz 200.
- `just rs-service-smoke` → 3/3 against cluster-up sidecar.
- `just rs-service-pipeline-smoke` → 2/2 against cluster-up sidecar
  (recheck skips loudly on missing `CDS_KIMINA_URL`, by design).
- `just dapr-cluster-down` → both children reclaimed cleanly.

8.4b's gate is the end-to-end pipeline smoke + the Task 8 close-out.

## Session 2026-05-01 — Task 8.4 plan restructure (planning-only)

Restructure-only session. The 8.4 scope inherited from ADR-016 §6 +
the Memory_Scratchpad open-notes blocks (placement+scheduler
bring-up + production SIGTERM-first warden escalation + readiness
gate flip + Python `cds_harness.workflow` package + Dapr Python SDK
introduction + aggregated cross-stage envelope + per-stage tracing
+ `just dapr-pipeline` recipe + end-to-end pytest smoke) was
diagnosed as context-window-overflowing under the same pattern that
already forced Task 8 → 8.1–8.4 (ADR-016), Task 8.3 → 8.3a + 8.3b
(ADR-018), Task 8.3b → 8.3b1 + 8.3b2 (ADR-019), and Task 8.3b2 →
8.3b2a + 8.3b2b (ADR-020). 8.4 split this session along the
natural Rust-foundation vs. Python-composition boundary into:

- **8.4a** — Dapr cluster bring-up + production SIGTERM-first
  warden + readiness gate flip. Owns `just placement-up` /
  `just scheduler-up` / `just dapr-cluster-up` + symmetric `*-down`
  recipes (background-spawn the slim-staged `placement` /
  `scheduler` binaries with pid-files under `target/`, SIGTERM-then
  -grace-then-SIGKILL teardown); two-stage SIGTERM → grace →
  SIGKILL escalation in `crate::solver::warden::run_with_input`
  (promote `nix` from kernel `[dev-dependencies]` to
  `[dependencies]`, default grace 500 ms, `kill_on_drop(true)` stays
  on every spawn so cancellation still SIGKILLs; the two-stage
  shape only fires on the timeout path); two new warden unit tests
  (`timeout_sigterm_first_when_child_traps_term` —
  `bash -c 'trap "exit 0" TERM; while :; do sleep 1; done'` exits
  on SIGTERM before grace expires; assert
  `WardenError::Timeout` + elapsed ∈ `[wall_clock, wall_clock +
  grace]`; `timeout_sigkill_fallback_when_child_ignores_term` —
  `bash -c 'trap "" TERM; while :; do sleep 1; done'` no-ops
  SIGTERM; assert `WardenError::Timeout` + elapsed ∈
  `[wall_clock + grace, wall_clock + grace + margin]`); optional
  readiness probe flip in `tests/common::wait_until_ready` from
  `/v1.0/healthz/outbound` → `/v1.0/healthz` if all five existing
  daprd-driven integration tests stay green against a cluster-up
  sidecar (else keep outbound and let 8.4b's pipeline test
  pre-flight `/v1.0/healthz` after starting the cluster). The
  `WardenError` enum shape stays identical — the two-stage
  escalation is an implementation detail; callers
  (`solver::z3`, `solver::cvc5`, `service::handlers`,
  `service::errors`) are untouched.
- **8.4b** — End-to-end Dapr Workflow + close-out of Task 8.
  Owns the new `cds_harness.workflow` package
  (`__init__.py` + `pipeline.py` + `activities.py` + `__main__.py`);
  five `@activity` callables (`ingest`, `translate`, `deduce`,
  `solve`, `recheck`), each a thin `httpx`-over-daprd wrapper
  POSTing `application/json` bodies to
  `http://127.0.0.1:<DAPR_HTTP_PORT>/v1.0/invoke/<app-id>/method/<path>`;
  Dapr Python SDK introduction (ADR-017 §5 reversed — `dapr>=1.17`
  + `dapr-ext-workflow>=1.17` in `[project.dependencies]`) for
  `WorkflowRuntime` + `@workflow` / `@activity` decorators +
  activity-id-tagged tracing (service-invocation calls inside
  activities stay on plain `httpx` per ADR-017 §5 narrow scope —
  one HTTP POST does not warrant typed bindings); aggregated
  in-band JSON envelope `{ payload, ir, matrix, verdict, trace,
  recheck }` (Phase 0 small payloads + replay determinism + JSON-
  over-TCP discipline preferred over state-store handles per
  ADR-021 §7); per-stage `tracing` spans correlated through
  Workflow activity-id (matches kernel-side
  `#[tracing::instrument(skip(req), fields(stage = "..."))]` from
  ADR-019 §6); `just dapr-pipeline` orchestrator
  (`dapr-cluster-up` → `py-service-dapr` → `rs-service-dapr` →
  `python -m cds_harness.workflow run-pipeline` → assert
  three flags → reverse teardown); end-to-end pytest smoke
  `python/tests/test_dapr_pipeline.py` (gated on full bin set
  + `CDS_KIMINA_URL`; same SIGTERM-first cleanup discipline as
  8.4a's warden refactor codifies). Final close-out gate:
  `just dapr-pipeline` end-to-end against
  `data/guidelines/contradictory-bound.txt` returns
  `verdict ∧ trace.sat=false ∧ recheck.ok=true`; manual run on
  `data/guidelines/hypoxemia-trigger.txt` returns
  `verdict ∧ trace.sat=true ∧ recheck.ok=true`. **This closes
  Task 8.**

ADR-021 captures the rationale, the Rust-foundation vs.
Python-composition boundary, the per-sub-task contracts (cluster
bring-up + warden refactor for 8.4a; Workflow harness + close-out
for 8.4b), the per-sub-task gates, and the alternatives rejected
(single 8.4 session; three-way split; defer warden to Phase 1; ship
Workflow before warden refactor; state-store handles instead of
in-band JSON; skip Dapr Python SDK; forgo per-stage tracing; skip
`just dapr-pipeline` recipe). The ordering note in Plan §8 is now
`8.1 < 8.2 < 8.3a < 8.3b1 < 8.3b2a < 8.3b2b < 8.4a < 8.4b < 9`.
PHASE marker remains `0` on `lib.rs`. Decide what `PHASE = 1`
means in 8.4b (probably: end-to-end pipeline runs under Dapr
Workflow against a canonical guideline).

**SIGTERM-first warden escalation is no longer deferred** — 8.4a
closes the deferral that has rolled forward through six prior ADRs
(014 §9 → 015 §8 → 016 §7 → 018 §6 → 019 §11 → 020 §6). The
two-stage shape (SIGTERM + grace + SIGKILL) gives the solver a
chance to flush partial proof-state before being killed, which
matters operationally once Workflow's retry-against-long-running-
proof failure mode is live in 8.4b.

No code, no dependencies, no test-suite changes this session.
Final gate (regression-only — verify no drift):

- `cargo test --workspace` → **151 pass** (unchanged from 8.3b2b close-out).
- `cargo clippy --workspace --all-targets -- -D warnings` → clean.
- `cargo fmt --all -- --check` → clean.
- `uv run pytest` → 95 pass.
- `uv run ruff check .` → clean.
- `just env-verify` → ✓ (uv 0.11.8, cargo 1.95.0, rustc 1.95.0,
  bun 1.3.13, just 1.50.0, git 2.47.3, curl 8.14.1; `.bin/`
  populated with `dapr`, `daprd`, `placement`, `scheduler`,
  `dashboard`, `z3`, `cvc5` — full set staged for 8.4a +
  8.4b).

## Session 2026-05-01 — Task 8.3b2b close-out

Final close-out of Task 8.3b. Shipped the two externally-gated daprd
smokes for `/v1/solve` and `/v1/recheck`, lifted into a new
`tests/service_pipeline_smoke.rs` per ADR-020 §3 (the foundation
`/healthz` + `/v1/deduce` smokes shipped in 8.3a / 8.3b2a stay
co-located in `tests/service_smoke.rs`; this file owns the
dependency-gated close-out). All six Phase 0 endpoints — kernel
`/healthz` + `/v1/{deduce,solve,recheck}` and harness `/healthz` +
`/v1/{ingest,translate}` — now round-trip through their respective
daprd sidecars under cargo integration tests.

**Module additions (`crates/kernel/tests/`):**

| File                                  | Role                                                                                                                                                              |
| ------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `tests/service_pipeline_smoke.rs`     | New: `mod common;` + two `#[tokio::test]`s. Test 1 — `dapr_sidecar_drives_solve_through_service_invocation` (gated on `.bin/z3` + `.bin/cvc5`, app-id `cds-kernel-solve-smoke`); Test 2 — `dapr_sidecar_drives_recheck_through_service_invocation` (gated on `.bin/z3` + `.bin/cvc5` **and** `CDS_KIMINA_URL`, app-id `cds-kernel-recheck-smoke`). Loud `eprintln!` SKIPs when bins / URL absent — same shape as `tests/solver_smoke.rs` / `tests/lean_smoke.rs`. Per-request `options.{timeout_ms, z3_path, cvc5_path}` pin absolute `.bin/` paths so daprd's `$PATH` does not leak into the gate (also serves as on-the-wire validation of 8.3b2a's per-request override semantics — ADR-020 §5 replace-the-floor). |
| `Justfile` (recipe `rs-service-pipeline-smoke`) | New: `CDS_KIMINA_URL={{CDS_KIMINA_URL}} cargo test --package cds-kernel --test service_pipeline_smoke -- --nocapture --test-threads=1`. Mirrors `rs-service-smoke` discipline; comment block updated on `rs-service-smoke` to scope it to "Task 8.3a + 8.3b2a" (foundation + deduce smoke). |

**Test contract — solve smoke:**

POSTs the canonical contradictory matrix (same shape as
`tests/solver_smoke.rs`) — two assertions
`x ≥ 100` (label `clause_000`, provenance
`atom:contradictory-bound:0-4`) and `x ≤ 50` (label `clause_001`,
provenance `atom:contradictory-bound:15-19`) — to
`/v1.0/invoke/cds-kernel-solve-smoke/method/v1/solve` with
`options.{timeout_ms: 30_000, z3_path: <abs>/.bin/z3, cvc5_path:
<abs>/.bin/cvc5}`. Asserts:

- HTTP 200,
- `trace.sat == false`,
- `trace.muc` contains both `atom:contradictory-bound:0-4` and
  `atom:contradictory-bound:15-19` (constraint C4 — MUC ↔
  `Atom.source_span` projection survives the daprd hop),
- `trace.alethe_proof` references both clause labels in `(assume
  clause_000` / `(assume clause_001` substrings (the same surface
  probe used by `tests/solver_smoke.rs`).

End-to-end runtime: ~1.08s (slim daprd boot + Z3/cvc5 round-trip on a
2-clause matrix is fast; the bulk is daprd's app-port liveness probe
window).

**Test contract — recheck smoke:**

Chains the trace forward by first invoking `/v1/solve` against the
same sidecar (re-using the contradictory matrix), then POSTs the
resulting `FormalVerificationTrace` to
`/v1.0/invoke/cds-kernel-recheck-smoke/method/v1/recheck` with
`options.{kimina_url: <CDS_KIMINA_URL>, timeout_ms: 120_000,
custom_id: cds-recheck-smoke}`. Asserts:

- HTTP 200 from both legs,
- `recheck.ok == true`,
- `recheck.custom_id == "cds-recheck-smoke"` (round-trip),
- four Phase 0 structural probes on `recheck.lean_proof_text`:
  `starts_paren`, `has_assume`, `has_rule`, `byte_len > 0` — same
  probe set as `tests/lean_smoke.rs::alethe_proof_round_trips_through_kimina`.

**Helpers (file-local) keeping both test bodies under
`clippy::too_many_lines`:**

| Helper                              | Purpose                                                                                                                  |
| ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `bin(name) -> Option<PathBuf>`      | `<repo>/.bin/<name>` if it exists, else `None`. Mirrors `tests/{solver,lean}_smoke.rs::bin`; resolves through `common::repo_root`. |
| `kimina_url() -> Option<String>`    | `std::env::var("CDS_KIMINA_URL").ok().filter(non-empty)`. Same gate shape as `tests/lean_smoke.rs`.                       |
| `contradictory_matrix() -> SmtConstraintMatrix` | Builds the canonical 2-assertion matrix (`x ≥ 100` ∧ `x ≤ 50`) with stable provenance spans for MUC projection. |
| `assert_expected_solve_trace(bytes) -> Result<FormalVerificationTrace, String>` | Decodes `trace`, asserts `sat == false`, MUC contains both expected provenance labels, Alethe proof contains both `(assume clause_*` substrings. Returns the decoded trace so the recheck test can chain it forward. |
| `assert_expected_recheck_outcome(bytes, custom_id)` | Decodes `recheck`, asserts `ok == true`, `custom_id` round-trip, four Phase 0 probes. |
| `await_dapr_ready(client, ports, deadline)` | Hits `/v1.0/invoke/.../method/healthz` until 200 (kernel readiness behind daprd, not just app port). |
| `invoke_solve_smoke(client, ports, smoke_app_id, z3, cvc5) -> FormalVerificationTrace` | One-shot: build envelope, POST, decode + assert, return trace. |
| `invoke_recheck_smoke(client, ports, smoke_app_id, trace, kimina_url, custom_id)` | One-shot: build envelope from chained trace, POST, decode + assert. |

**Subprocess hygiene unchanged.** SIGTERM-first cleanup of the dapr CLI
child via `common::sigterm_then_kill(&mut child, Duration::from_secs(5))`
(ADR-018 §6 narrow auth — the same shape used by 8.3a + 8.3b2a).
Production SIGTERM-first warden escalation for the workspace solver /
Lean wardens **remains deferred to Task 8.4** (rolled forward
ADR-014 §9 → ADR-015 §8 → ADR-016 §7 → ADR-018 §6 → ADR-019 §11 →
ADR-020 §6).

**Tests (Rust workspace, all green — 151 pass total):**

| Suite                                              | Count | Delta vs 8.3b2a |
| -------------------------------------------------- | ----- | -------------- |
| Existing schema + canonical + deduce + solver + lean baseline | 116 | unchanged. |
| `service::config` unit                              | 5     | unchanged.     |
| `service::errors` unit                              | 9     | unchanged.     |
| `service::app` unit                                 | 6     | unchanged.     |
| `service::handlers` unit                            | 13    | unchanged.     |
| `service::state` unit                               | 9     | unchanged.     |
| `bin::cds_kernel_service` unit                      | 3     | unchanged.     |
| `tests/service_smoke.rs` integration                | 3     | unchanged (healthz standalone + healthz daprd + deduce daprd). |
| `tests/service_pipeline_smoke.rs` integration       | 2     | new (solve daprd + recheck daprd). |
| `tests/{deduce_smoke, golden_roundtrip, lean_smoke, solver_smoke}` integration | 15 | unchanged. |

> Total: 116 + 5 + 9 + 6 + 13 + 9 + 3 + 3 + 2 + 15 = 151 (cargo runner
> reports the same 151 split across 9 binaries; the per-binary
> breakdown above sums by category for future-session clarity).

**File-split rationale (ADR-020 §3 deferred decision).** The optional
file split was exercised: `tests/service_smoke.rs` was already at 391
lines at end-of-8.3b2a, and adding two more daprd-driven test bodies
(~150 lines combined even after helper extraction) would push it past
the comfort threshold for a single integration-test file. Splitting
along the dependency-gate boundary keeps each file's gate predicate
crisp: `service_smoke.rs` is dependency-free (only `.bin/dapr` + slim
runtime), `service_pipeline_smoke.rs` adds `.bin/z3` + `.bin/cvc5` +
optional `CDS_KIMINA_URL`. Pairs cleanly with two distinct Justfile
recipes — operators who only have daprd installed can run
`rs-service-smoke`; operators who have additionally fetched the
solvers + Kimina can run `rs-service-pipeline-smoke`.

**Lint fixes during the session (3 issues, all pre-commit):**

- `clippy::doc_markdown` (×2) — `OnionL` in module-level + item-level
  doc comments needed backticks. Fixed: `` `OnionL` ``.
- `clippy::too_many_lines` (130/100) on the recheck test body —
  extracted `await_dapr_ready`, `invoke_solve_smoke`,
  `invoke_recheck_smoke` helpers; threaded
  `assert_expected_solve_trace` to return the decoded
  `FormalVerificationTrace` so the recheck test can chain it forward
  without re-parsing. Both test bodies now ~30 lines each plus the
  shared dapr setup/teardown scaffolding.
- `rustfmt` flagged a 4-line `let bytes = resp\n    .bytes()\n    .await\n    .map_err(...)?` chain — auto-fixed by `cargo fmt --all` to a one-liner.

**Final regression gate (all green):**

- `cargo test --workspace` → **151 pass** (+2 vs 8.3b2a's 149 — both new
  integration tests in `service_pipeline_smoke.rs`).
- `cargo clippy --workspace --all-targets -- -D warnings` → clean.
- `cargo fmt --all -- --check` → clean.
- `uv run pytest` → 95 pass (Python tree untouched).
- `uv run ruff check .` → clean.
- `just rs-service-pipeline-smoke` → 2/2 (with `CDS_KIMINA_URL`
  exported; without it, recheck loudly SKIPs and solve still passes).
- `just rs-service-smoke` → 3/3 (foundation gate held — healthz
  standalone + healthz daprd + deduce daprd).
- `just env-verify` → ✓ (uv 0.11.8, cargo 1.95.0, rustc 1.95.0,
  bun 1.3.13, just 1.50.0, git 2.47.3, curl 8.14.1; `.bin/` populated
  with `dapr`, `daprd`, `z3`, `cvc5` for the solve smoke;
  `CDS_KIMINA_URL` exported for the recheck smoke).

**Dependencies added:** none. The new test file reuses
`reqwest` / `serde_json` / `tokio` already wired in 8.3a + 8.3b2a;
`tests/common.rs` provides the dapr-bring-up helpers via `mod common;`.

**Decisions captured.** No new ADR opened — every decision
(file-split, helper-extraction shape, gate-predicate set, app-id
naming) fits inside ADR-020's existing contract (§3 deferred-decision
authorization for the file split, §5 replace-the-floor for
per-request overrides, §6 deferred SIGTERM-first warden escalation).

**Task 8.3b is now closed.** All sub-tasks (8.3a → 8.3b1 → 8.3b2a →
8.3b2b) are DONE; the kernel service is feature-complete for Phase 0
under daprd and ready to be composed into the end-to-end Dapr Workflow
(Task 8.4).

**Next session (Task 8.4 — End-to-end Dapr Workflow).** Compose the
six now-validated daprd endpoints under a Dapr Workflow against a
canonical guideline (`ingest → translate → deduce → solve →
recheck`). Bring up placement + scheduler. Per-stage tracing
(harness + kernel `tracing` spans correlate via Workflow activity
ID). Flag round-trips end-to-end (`Verdict` flag + `trace.sat` +
`recheck.ok` flow back to the workflow caller). **Production
SIGTERM-first warden escalation lands here** — replace the current
`solver::warden` / `lean::warden` SIGKILL-on-timeout shape with
SIGTERM-first + grace-window + SIGKILL fallback (rolled forward
ADR-014 §9 → ADR-015 §8 → ADR-016 §7 → ADR-018 §6 → ADR-019 §11 →
ADR-020 §6 — five rolls; 8.4 closes the deferral).

## Session 2026-05-01 — Task 8.3b2a close-out

Shipped the Phase 0 Rust kernel `KernelServiceState` foundation + the
dependency-free `/v1/deduce` daprd smoke. The router is now stateful;
the three pipeline handlers extract their options floor from
`axum::extract::State<KernelServiceState>` while `/healthz` stays
stateless by simply not extracting `State<_>`. ADR-020 §2 codified the
contract; this session implemented it as designed.

**Module additions / edits (`crates/kernel/src/service/`):**

| File          | Role                                                                                                                                                 |
| ------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| `state.rs`    | New: `KernelServiceState { verify_options, lean_options }`; `from_env()` (panics on `VarError::NotUnicode` per ADR-018 §1 / ADR-020 §2 fail-loud-at-boot discipline); pure `from_lookup<F: Fn(&str) -> Option<String>>` helper enables closure-injection unit tests with **zero env mutation** (cleaner than the two `serial_test` / sub-process options ADR-020 §4 listed); private helpers `lookup_string`, `lookup_path`, `lookup_duration`; latter panics on non-numeric / negative ms. |
| `mod.rs`      | Added `pub mod state;` + re-exports of `KernelServiceState` and the 5 env constants (`Z3_PATH_ENV`, `CVC5_PATH_ENV`, `SOLVER_TIMEOUT_MS_ENV`, `KIMINA_URL_ENV`, `LEAN_TIMEOUT_MS_ENV`).                                                                          |
| `app.rs`      | `build_router` now takes `state: KernelServiceState` and ends with `.with_state(state)`; removed the (now-redundant) `#[must_use]` since `Router` already carries it.                                                                                              |
| `handlers.rs` | Three handlers gain `State(state): State<KernelServiceState>`; `SolveOptionsWire::into_verify_options` / `RecheckOptionsWire::into_lean_options` now take a `floor:` arg so per-request fields independently override env defaults (ADR-020 §5 replace-the-floor). |
| `bin/cds_kernel_service.rs` | `serve()` calls `KernelServiceState::from_env()` and passes it to `build_router`; the boot `tracing::info!` line now reports `z3_path` / `cvc5_path` / `solver_timeout_ms` / `kimina_url` / `lean_timeout_ms` so an operator typo + a fresh sidecar boot together surface the resolved floors.            |

**Test additions / lifts:**

| File                                  | Role                                                                                                                                                              |
| ------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `tests/common/mod.rs`                 | New (directory form so cargo doesn't compile it as its own test binary): `pick_free_port`, `wait_until_ready`, `repo_root`, `dapr_paths`, `DaprPorts { app, http, grpc, metrics }` with `allocate()`, `build_dapr_command`, `sigterm_then_kill`. Top-level `#![allow(dead_code)]` because cargo's per-crate dead-code analysis can't see cross-test-file usage. |
| `tests/service_smoke.rs`              | Rewritten to `mod common;` and import shared helpers; new third test `dapr_sidecar_drives_deduce_through_service_invocation` drives the deduce endpoint via daprd (app-id `cds-kernel-deduce-smoke`); assertion logic extracted into `assert_expected_deduce_verdict` to keep the test under `clippy::too_many_lines`. |
| `service::state` unit tests           | 9 new: defaults-when-unset, default-equals-empty-lookup, z3 + cvc5 path overrides, kimina_url override, solver/lean timeout parsing, empty-or-whitespace-treated-as-unset, panic on non-numeric solver timeout, panic on negative lean timeout. |
| `service::handlers` unit tests        | 2 new partial-override cases: solve `timeout_ms`-only with non-default floor preserves z3/cvc5; recheck `kimina_url`-only with non-default floor preserves timeout/custom_id/extra_headers. |

**Closure-injection design note.** ADR-020 §4 listed two options for
isolating env-touching tests (`serial_test` dep or sub-`std::process::Command`).
Neither was needed: the pure `from_lookup<F: Fn(&str) -> Option<String>>(f)`
helper takes the env oracle as an argument; `from_env()` is a
one-liner that delegates with the obvious closure
(`from_lookup(|key| std::env::var(key).ok())`). Tests pass
hand-built `HashMap`-style closures and never touch process env. The
constraint pinned by ADR-020 §4 (don't mutate process env in tests)
is satisfied by construction. No new ADR was opened — this is a
micro-decision that fits inside the existing ADR-020 contract.

**Deduce smoke shape.** App-id `cds-kernel-deduce-smoke` (distinct
from the existing `cds-kernel-smoke` healthz sidecar so both can
co-exist). 3-sample `ClinicalTelemetryPayload` spans the canonical
vital allowlist; sample 1 has `heart_rate_bpm = 30` (below the default
`Phase0Thresholds.heart_rate_bpm.low = 50`), so
`breach_summary.bradycardia == [1]` is the smoke's primary assertion;
the other 5 vitals stay in-band so other breach lists are deliberately
empty. SIGTERM-first cleanup of the `dapr` CLI child via
`sigterm_then_kill(&mut child, Duration::from_secs(5))` (ADR-018 §6
narrow auth, unchanged from 8.3a). No `.bin/z3` / `.bin/cvc5` /
Kimina dep — the deduce path is pure Rust + ascent (ADR-013).

**Tests (Rust workspace, all green — 149 pass total):**

| Suite                                              | Count | Delta vs 8.3b1 |
| -------------------------------------------------- | ----- | -------------- |
| Existing schema + canonical + deduce + solver + lean baseline | 116 | unchanged. |
| `service::config` unit                              | 5     | unchanged.     |
| `service::errors` unit                              | 9     | unchanged.     |
| `service::app` unit                                 | 6     | unchanged shape; bodies updated to pass `KernelServiceState::default()` to `build_router`. |
| `service::handlers` unit                            | 13    | +2 (solve partial-override, recheck partial-override). |
| `service::state` unit                               | 9     | new module.    |
| `bin::cds_kernel_service` unit                      | 3     | unchanged.     |
| `tests/service_smoke.rs` integration                | 3     | +1 (`dapr_sidecar_drives_deduce_through_service_invocation`). |
| `tests/{deduce_smoke, golden_roundtrip, lean_smoke, solver_smoke}` integration | 15 | unchanged. |

> Total: 116 + 5 + 9 + 6 + 13 + 9 + 3 + 3 + 15 = 149 (the cargo runner
> reports the same 149 split across 8 binaries; the per-binary
> breakdown above sums by category for future-session clarity).

**Final regression gate (all green):**

- `cargo test --workspace` → **149 pass** (+12 vs 8.3b1's 137).
- `cargo clippy --workspace --all-targets -- -D warnings` → clean
  (initial run flagged `double_must_use` on `build_router` and
  `manual_string_new` in the state tests + `too_many_lines` on the
  new deduce smoke; all three fixed in-session).
- `cargo fmt --all -- --check` → clean.
- `uv run pytest` → 95 pass (Python tree untouched).
- `uv run ruff check .` → clean.
- `just rs-service-smoke` → 3/3.
- `just env-verify` → ✓ (uv 0.11.8, cargo 1.95.0, rustc 1.95.0,
  bun 1.3.13, just 1.50.0, git 2.47.3, curl 8.14.1; `.bin/` empty
  as expected — solve/recheck deps land in 8.3b2b, not here).

**Next session (Task 8.3b2b — final 8.3b close-out).** Add the two
externally-gated daprd smokes: `/v1/solve` (gated on `.bin/z3` +
`.bin/cvc5` with loud SKIP — same pattern as `tests/solver_smoke.rs`)
and `/v1/recheck` (gated on `CDS_KIMINA_URL` with loud SKIP — same
pattern as `tests/lean_smoke.rs`); chain the trace from solve →
recheck. Optional: split into `tests/service_pipeline_smoke.rs` if
`service_smoke.rs` keeps growing; pair with
`just rs-service-pipeline-smoke`. Final close-out gate confirms all
six Phase 0 endpoints (kernel `/healthz` + `/v1/{deduce,solve,recheck}`;
harness `/healthz` + `/v1/{ingest,translate}`) round-trip through
daprd.

## Session 2026-05-01 — Task 8.3b2 plan restructure (planning-only)

Restructure-only session. The 8.3b2 scope inherited from ADR-019 §10 +
the open-notes block (env-driven `KernelServiceState` resolution +
handler refactor onto `axum::extract::State` + shared smoke helpers
in `tests/common.rs` + three daprd-driven cargo integration tests
hitting `/v1/deduce`, `/v1/solve`, `/v1/recheck` via
`/v1.0/invoke/cds-kernel/method/v1/...`) was diagnosed as
context-window-overflowing under the same pattern that already forced
Task 8 → 8.1–8.4 (ADR-016), Task 8.3 → 8.3a + 8.3b (ADR-018), and
Task 8.3b → 8.3b1 + 8.3b2 (ADR-019). 8.3b2 split this session along
the natural dependency boundary into:

- **8.3b2a** — foundation refactor + dependency-free deduce smoke.
  Owns the `KernelServiceState { verify_options, lean_options }`
  introduction and its env-driven `from_env()` constructor reading
  `CDS_Z3_PATH` / `CDS_CVC5_PATH` / `CDS_KIMINA_URL` /
  `CDS_SOLVER_TIMEOUT_MS` / `CDS_LEAN_TIMEOUT_MS`; the three handlers'
  refactor onto `axum::extract::State<KernelServiceState>` (per-request
  `options` still override env defaults — env defines the floor);
  `build_router()` signature change to `Router<()>` after
  `.with_state(...)`; `/healthz` stays stateless via `Router::merge`
  or equivalent; the lifting of `pick_free_port` /
  `wait_until_ready` / SIGTERM-cleanup helpers from the existing
  `tests/service_smoke.rs` into a shared `tests/common.rs` module;
  and **one** daprd-driven cargo integration test for `/v1/deduce`
  using a synthetic telemetry payload spanning the canonical-vital
  allowlist (no external solver / Kimina deps). `just rs-service-smoke`
  grows by one case (still `--test-threads=1`).
- **8.3b2b** — solve + recheck smokes (close-out). Owns the
  `/v1/solve` Dapr smoke driving `data/guidelines/contradictory-bound.recorded.json`
  through `/v1.0/invoke/cds-kernel/method/v1/solve` (gated on
  `.bin/z3` + `.bin/cvc5` presence with loud SKIP — same pattern as
  `tests/solver_smoke.rs`); the `/v1/recheck` Dapr smoke chaining
  the resulting `FormalVerificationTrace` forward through
  `/v1.0/invoke/cds-kernel/method/v1/recheck` (gated on
  `CDS_KIMINA_URL` with loud SKIP — same pattern as `tests/lean_smoke.rs`);
  optional split into `tests/service_pipeline_smoke.rs` if
  `service_smoke.rs` grew long during 8.3b2a, paired with a
  `just rs-service-pipeline-smoke` recipe; final close-out gate
  confirming all six Phase 0 endpoints (kernel `/healthz` +
  `/v1/{deduce,solve,recheck}`; harness `/healthz` + `/v1/{ingest,translate}`)
  round-trip through daprd.

ADR-020 captures the rationale, the dependency-boundary split, the
foundation/close-out delineation, and the per-sub-task gates. The
ordering note in Plan §8 is now
`8.1 < 8.2 < 8.3a < 8.3b1 < 8.3b2a < 8.3b2b < 8.4 < 9`. PHASE marker
remains `0` on `lib.rs`. SIGTERM-first warden escalation **remains
deferred** to Task 8.4 (ADR-014 §9 → ADR-015 §8 → ADR-016 §7 →
ADR-018 §6 → ADR-019 §11 → now ADR-020 §6).

No code, no dependencies, no test-suite changes this session. Final
gate (regression-only — verify no drift):

- `cargo test --workspace` → **137 pass** (unchanged from 8.3b1 close-out).
- `cargo clippy --workspace --all-targets -- -D warnings` → clean.
- `cargo fmt --all -- --check` → clean.
- `uv run pytest` → 95 pass.
- `uv run ruff check .` → clean.
- `just env-verify` → ✓ (uv 0.11.8, cargo 1.95.0, rustc 1.95.0,
  bun 1.3.13, just 1.50.0, git 2.47.3, curl 8.14.1; `.bin/` empty —
  expected: `just fetch-bins` is run at solve-test time in 8.3b2b,
  not during 8.3b2a since deduce has no external solver dep).

## Session 2026-05-01 — Task 8.3b1 close-out

Shipped the Phase 0 kernel pipeline handlers + their `IntoResponse`
impls. The axum router built by `cds_kernel::service::build_router`
now serves `POST /v1/deduce`, `POST /v1/solve`, `POST /v1/recheck`
alongside the `/healthz` route from 8.3a. Each handler is stateless:
the request body carries optional knobs that lower onto
`solver::VerifyOptions` / `lean::LeanOptions` with `::default()` as the
fallback. ADR-019 codifies the 8.3b → 8.3b1 + 8.3b2 split rationale
and the 8.3b1 contract.

**Module additions (`crates/kernel/src/service/`):**

| File          | Role                                                                                                                                                |
| ------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| `handlers.rs` | New module: three handler `async fn`s + `DeduceRequest` / `SolveRequest` / `RecheckRequest` envelopes + `SolveOptionsWire` / `RecheckOptionsWire` lowerings + `LeanRecheckWire` / `LeanMessageWire` / `LeanSeverityWire` (snake-case wire mirror of `LeanRecheck`). |
| `errors.rs`   | Extended: `IntoResponse` impls for `DeduceError`, `SolverError`, `LeanError` — every variant lifts to HTTP 422 with stable `error` kind tags (`non_canonical_vital`, `non_finite_reading`, `domain_error`, `warden`, `solver_unparseable_output`, `z3_error`, `cvc5_error`, `solver_unknown_verdict`, `solver_disagreement`, `lean_no_proof`, `lean_transport`, `lean_server_error`, `lean_decode_failed`). |
| `app.rs`      | `build_router()` mounts the three new `POST` routes alongside `GET /healthz`; the existing `TraceLayer` covers them all. New unit test asserts `GET` against any pipeline path returns 405. |
| `mod.rs`      | Re-exports `handlers::*` (paths, request envelopes, wire-DTOs).                                                                                     |

**Endpoint contract (constraint C6 — JSON-over-TCP):**

| Method | Path           | Request body                                            | Response body                                            | Error envelope (HTTP 422)                       |
| ------ | -------------- | ------------------------------------------------------- | -------------------------------------------------------- | ----------------------------------------------- |
| GET    | `/healthz`     | —                                                       | `{status, kernel_id, phase, schema_version}` (8.3a)      | —                                               |
| POST   | `/v1/deduce`   | `{payload, rules?}`                                     | `Verdict`                                                | `{error: <DeduceError kind>, detail}`           |
| POST   | `/v1/solve`    | `{matrix, options?: {timeout_ms, z3_path, cvc5_path}}`  | `FormalVerificationTrace`                                | `{error: <SolverError kind>, detail}`           |
| POST   | `/v1/recheck`  | `{trace, options?: {kimina_url, timeout_ms, custom_id, extra_headers}}` | `LeanRecheckWire` (snake-case `severity`)         | `{error: <LeanError kind>, detail}`             |

Each request envelope is `#[serde(deny_unknown_fields)]` so
silently-typo'd keys fail at extraction time (axum's `Json<T>` rejection
returns HTTP 422 by default). `Option<…OptionsWire>` is itself
`#[serde(default)]` so callers may omit `options` entirely.

**Subprocess hygiene (ADR-004):** the warden's
`Command::kill_on_drop(true)` contract survives the HTTP path because
each handler awaits `solver::verify` / `lean::recheck` directly. axum
handler-future cancellation drops the in-flight `Child` handles, which
kills any running Z3 / cvc5 / Lean child. SIGTERM-first escalation for
the warden's children remains deferred to Task 8.4 (rolled forward
ADR-014 §9 → ADR-015 §8 → ADR-016 §7 → ADR-018 §6 → ADR-019 §5).

**Per-stage tracing.** Each handler is annotated with
`#[tracing::instrument(skip(req), fields(stage = "<deduce|solve|recheck>"))]`
so the Workflow harness (Task 8.4) can correlate stage events without
parsing free-form messages. The router-level `TraceLayer` from 8.3a
remains the per-HTTP-request span source.

**Tests (Rust workspace, all green — 137 pass total):**

| Suite                                              | Count | Coverage                                                                                                                                                                                             |
| -------------------------------------------------- | ----- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Existing schema + canonical + deduce + solver + lean + service::config + bin::cds_kernel_service | 88 | unchanged from 8.3a baseline (was 93 incl. service::*) — the breakdown shifts because new tests are added and existing service::* tests re-classify. |
| `service::config` unit                              | 5     | unchanged (parse_port_raw paths).                                                                                                                                                                    |
| `service::errors` unit                              | 9     | error_body serde + 422 lift + explicit-status helper (3 prior); new: `deduce_error_kinds_are_stable`, `deduce_error_into_response_lifts_to_422_envelope`, `solver_error_kinds_cover_every_variant`, `solver_error_into_response_carries_warden_detail`, `lean_error_kinds_cover_every_variant`, `lean_error_into_response_lifts_no_proof_to_422`. |
| `service::app` unit                                 | 6     | unchanged 5 (healthz invariants + JSON shape + 404 + APP_ID pin); new: `pipeline_routes_reject_get` asserts 405 on GET to `/v1/{deduce,solve,recheck}`.                                              |
| `service::handlers` unit                            | 11    | `DeduceRequest` round-trip + `deny_unknown_fields`; `SolveOptionsWire`/`RecheckOptionsWire` lower-to-options identity; defaults match `VerifyOptions::default` / `LeanOptions::default`; `SolveRequest` accepts missing options + rejects unknown options field; `RecheckRequest` accepts minimal envelope; `LeanRecheckWire` serializes severity as snake-case; `LeanSeverityWire` round-trip per variant; `LeanMessageWire` lift verbatim.|
| `service::handlers::runtime_tests` integration      | 4     | `tower::oneshot` end-to-end: deduce happy path returns typed `Verdict`; deduce non-canonical vital → 422 + `non_canonical_vital`; solve missing-z3 → 422 + `warden` (warden::Spawn surfaced); recheck sat-trace → 422 + `lean_no_proof`; recheck unbound-URL → 422 + `lean_transport` (port 1 connect refused). |
| `bin::cds_kernel_service` unit                      | 3     | unchanged (parse_argv help + unknown + no-args).                                                                                                                                                     |
| `tests/service_smoke.rs` integration                | 2     | unchanged: standalone axum + gated dapr sidecar `/healthz` smoke (8.3a foundation gate held).                                                                                                        |
| `tests/{deduce_smoke, golden_roundtrip, lean_smoke, solver_smoke}` integration | 15 | unchanged.                                                                                                                                                                                          |

> The non-finite-reading runtime test was deliberately *not* shipped
> because `serde_json` strict-parses NaN/±∞ and refuses to round-trip
> them; the variant remains covered by
> `service::errors::tests::deduce_error_kinds_are_stable` (kind tag
> stability) and the deduce-module unit
> `nan_reading_is_rejected_at_boundary` (boundary check). 8.3b2 will
> not revisit it — every payload that crosses the wire is finite by
> construction.

Final gate (all green):

- `cargo test --workspace` → **137 pass** (117 unit + 3 bin + 2 service_smoke + 5 deduce_smoke + 5 golden_roundtrip + 1 lean_smoke + 4 solver_smoke).
- `cargo clippy --workspace --all-targets -- -D warnings` → clean.
- `cargo fmt --all -- --check` → clean.
- `uv run pytest` → 95 pass (no Python regressions).
- `uv run ruff check .` → clean.
- `just rs-service-smoke` → 2/2 with `--nocapture`; clean teardown (no daprd / cds-kernel-service orphans).

**Dependencies added:** none. axum 0.8 / tower 0.5 / tower-http 0.6
were already wired in 8.3a; the handlers and IntoResponse impls reuse
them. No new `[dev-dependencies]`.

**Decisions captured in ADR-019** — Phase 0 Rust kernel pipeline
handlers contract: split-rationale (8.3b1 isolates handlers + error
envelope + unit tests; 8.3b2 owns the daprd-driven integration test +
`AppState`); request envelopes use `deny_unknown_fields`; option
overrides use `timeout_ms` (u64) for unambiguous wire shape; response
shapes are unwrapped (`Verdict` / `FormalVerificationTrace` /
`LeanRecheckWire`) per the open notes from 8.3a; `LeanRecheckWire` is
a wire-only DTO so `cds_kernel::lean::LeanRecheck` does not grow a
`Serialize` derive (avoids cross-cutting snake-case rename gymnastics
on a public internal type); SIGTERM-first warden escalation **remains
deferred to Task 8.4**; `AppState` introduction **deferred to 8.3b2**
because 8.3b1's handlers are stateless.

## Open notes for Task 8.3b2a — Rust kernel `AppState` + `/v1/deduce` Dapr smoke

- **Scope (foundation + dependency-free pipeline smoke).** Three work
  items, in this order:
  1. **`KernelServiceState`.** New `cds_kernel::service::state` module
     (or fold into `app.rs` if the type stays small). Shape:
     `KernelServiceState { verify_options: VerifyOptions, lean_options:
     LeanOptions }`. Constructor `KernelServiceState::from_env()`
     reads:
     - `CDS_Z3_PATH` → `VerifyOptions::z3_path` (default: bare `z3`
       discovered from `$PATH` / `.bin/`).
     - `CDS_CVC5_PATH` → `VerifyOptions::cvc5_path` (default: bare
       `cvc5`).
     - `CDS_SOLVER_TIMEOUT_MS` → `VerifyOptions::timeout` via
       `Duration::from_millis` (default: existing 30 s baseline).
     - `CDS_KIMINA_URL` → `LeanOptions::kimina_url` (default:
       `http://127.0.0.1:8000`).
     - `CDS_LEAN_TIMEOUT_MS` → `LeanOptions::timeout` (default:
       existing 60 s baseline).
     Invalid env values (non-utf8, non-numeric, overflowing u64) **fail
     boot** with a loud panic — not silently fallback. Mirrors the
     `service::config::parse_port_raw` discipline.
  2. **Handler refactor onto `axum::extract::State`.** Three handlers
     gain `State(state): State<KernelServiceState>` as a leading
     extractor argument. The merge rule: per-request `options` (from
     the JSON envelope) **wins**; missing fields fall back to
     `state.verify_options` / `state.lean_options`; missing both falls
     to `VerifyOptions::default()` / `LeanOptions::default()` (which
     is now what `from_env()` returns when no env vars are set).
     `/healthz` stays stateless — wire it via `Router::merge` of a
     stateless sub-router or split into `healthz_router()` +
     `pipeline_router()` if cleaner. `build_router(state:
     KernelServiceState)` returns `Router<()>` after the
     `.with_state(...)` propagation. The `bin/cds_kernel_service.rs`
     entrypoint constructs the state via `KernelServiceState::from_env()`
     before `axum::serve(...)`.
  3. **Shared smoke helpers in `tests/common.rs`.** Lift
     `pick_free_port`, `wait_until_ready`, and the SIGTERM-cleanup
     teardown from the existing `tests/service_smoke.rs` into a
     module-shared `tests/common.rs` (the standard cargo idiom is a
     `mod common;` declaration in each integration test file with
     a `#[allow(dead_code)]` attr on items not used in every suite).
     This is the lift the 8.3b1 open-notes block forecasted ("lift
     them to a shared `tests/common.rs` module if a second integration
     test grows") — 8.3b2a is exactly that growth point.
  4. **`/v1/deduce` Dapr smoke.** New cargo integration test in
     `tests/service_smoke.rs` (extend, do not split — keep
     `service_pipeline_smoke.rs` for 8.3b2b). Shape:
     - Spawn `cds-kernel-service` under daprd (`dapr run --app-id
       cds-kernel-deduce-smoke ...`) on a `pick_free_port`-allocated
       app port + Dapr HTTP port.
     - Wait for `/v1.0/healthz/outbound` ready (Phase 0 readiness
       gate, ADR-018 §5; placement is still deferred to 8.4).
     - POST a synthetic `{payload: ClinicalTelemetryPayload}` JSON
       envelope to `/v1.0/invoke/cds-kernel-deduce-smoke/method/v1/deduce`.
       Payload spans the canonical-vital allowlist (e.g., `heart_rate
       = 30 bpm` → out-of-band; `systolic_bp = 80 mmHg` → in-band).
     - Assert `200 OK`, response body decodes as `Verdict`, and
       `breach_summary` is non-empty for the out-of-band reading.
     - Tear down with SIGTERM-first cleanup (ADR-018 §6 narrow auth
       still applies — only the dapr CLI, not the kernel binary).
- **Justfile.** Extend `rs-service-smoke` to keep running the whole
  `tests/service_smoke.rs` suite — no recipe rename. The new test
  joins the existing two foundation cases for a 3-test gate.
  `--test-threads=1` discipline carried unchanged. Do **not** introduce
  `rs-service-pipeline-smoke` here — that recipe lands in 8.3b2b if
  and only if the file is split.
- **Unit tests for state resolution.** New `service::state::tests` (or
  `service::app::tests` if folded). Coverage:
  - `from_env_returns_defaults_when_unset` — happy path with all env
    vars unset.
  - `from_env_picks_up_z3_and_cvc5_overrides` — sets `CDS_Z3_PATH=/x`,
    `CDS_CVC5_PATH=/y`, asserts the resolved options.
  - `from_env_picks_up_kimina_url_override` — sets
    `CDS_KIMINA_URL=http://example:1234`.
  - `from_env_parses_timeout_ms` — sets `CDS_SOLVER_TIMEOUT_MS=500`,
    asserts `Duration::from_millis(500)`.
  - `from_env_panics_on_non_numeric_timeout` — sets
    `CDS_SOLVER_TIMEOUT_MS=abc`, expects panic via
    `std::panic::catch_unwind` or `#[should_panic]`. Use
    `serial_test::serial` or process-level isolation if the env mutation
    races other tests.
  Note the env-mutation hazard: cargo test parallelism + global env
  is footgunny. Either mark the state-resolution tests
  `#[serial_test::serial]` (add `serial_test = "3"` as a dev-dep) or
  run them via a sub-`std::process::Command` so they own their own
  environment. Pick whichever has the shorter dep delta — `serial_test`
  is widely adopted; the sub-process route is dep-free but more
  verbose.
- **Per-request override semantics.** Document explicitly in the
  handler-side comments: per-request `options.timeout_ms`, when
  present, **replaces** the env-resolved timeout; it does not add or
  cap. Same for `z3_path` / `cvc5_path` / `kimina_url`. This matches
  the 8.3b1 contract where `Option<…OptionsWire>` already had
  per-field replace semantics; we're now just changing the floor from
  `::default()` to `state.…`.
- **Final gate.** `cargo test --workspace` green (target: ~137 + 5
  state unit + 1 deduce-Dapr smoke = ~143 pass); clippy clean; fmt
  clean; pytest 95/95 untouched; `just rs-service-smoke` runs three
  cases (existing standalone + existing healthz-Dapr + new
  deduce-Dapr); `just env-verify` clean.
- **Out of scope (8.3b2b).** `/v1/solve` Dapr smoke (gated on
  `.bin/z3` + `.bin/cvc5`); `/v1/recheck` Dapr smoke (gated on
  `CDS_KIMINA_URL`); optional `tests/service_pipeline_smoke.rs` split;
  `just rs-service-pipeline-smoke` recipe; final 6-endpoint
  round-trip close-out.
- **SIGTERM-first warden escalation** is **still deferred** to Task
  8.4 (ADR-014 §9 → ADR-015 §8 → ADR-016 §7 → ADR-018 §6 →
  ADR-019 §11 → ADR-020 §6).
- **PHASE marker** still `0` on `lib.rs`. Decide what `PHASE = 1`
  means in 8.4 (probably: end-to-end pipeline runs under Dapr).

## Open notes for Task 8.3b2b — Rust kernel `/v1/solve` + `/v1/recheck` Dapr smokes (close-out)

- **Scope (gated pipeline smokes — close-out of 8.3b).** Two daprd-
  driven cargo integration tests, both gated on external dependency
  presence with loud SKIP notices when absent (mirror the existing
  `tests/lean_smoke.rs` / `tests/solver_smoke.rs` skip pattern).
  Sequence:
  1. **`/v1/solve` Dapr smoke.** Drive
     `data/guidelines/contradictory-bound.recorded.json` (an
     `SmtConstraintMatrix` whose Z3+cvc5 verdict is `unsat` with the
     Alethe proof) through
     `/v1.0/invoke/cds-kernel-solve-smoke/method/v1/solve`. Assert
     `200 OK`, decode response as `FormalVerificationTrace`, assert
     `verdict == Unsat` and `proof` is present. Gated on `.bin/z3` +
     `.bin/cvc5` presence — print `SKIP: solve smoke requires .bin/z3
     + .bin/cvc5 (run \`just fetch-z3\` / \`just fetch-cvc5\`)` when
     either binary is missing and return early without failing the
     suite.
  2. **`/v1/recheck` Dapr smoke.** Reuse the
     `FormalVerificationTrace` produced in step 1 (or re-load
     `contradictory-bound.recorded.json` and re-derive the trace if
     8.3b2b chooses to keep the two tests independent — the
     simpler-and-greppable choice). POST `{trace}` to
     `/v1.0/invoke/cds-kernel-recheck-smoke/method/v1/recheck`.
     Assert `200 OK`, decode response as `LeanRecheckWire`, assert
     `severity` is `Info` and the recheck succeeded. Gated on
     `CDS_KIMINA_URL` env presence — print `SKIP: recheck smoke
     requires CDS_KIMINA_URL pointing to a running Kimina daemon
     (ADR-015)` when unset and return early.
- **Test-file decision (defer to 8.3b2b at session-time).** If
  8.3b2a left `tests/service_smoke.rs` long enough to feel
  unmanageable (>~500 lines or >~7 tests), split solve+recheck out
  into `tests/service_pipeline_smoke.rs` and add
  `just rs-service-pipeline-smoke` (`cargo test --test
  service_pipeline_smoke -- --test-threads=1 --nocapture`). If
  `service_smoke.rs` is still tractable, keep all five tests there
  and just extend the existing `rs-service-smoke` recipe. The
  fixture files (`pick_free_port`, `wait_until_ready`,
  SIGTERM-cleanup) are already in `tests/common.rs` after 8.3b2a, so
  either split is cheap.
- **Service-invocation app-IDs.** Use distinct app-IDs per test
  (`cds-kernel-solve-smoke`, `cds-kernel-recheck-smoke`) so daprd
  doesn't conflate the sidecars on a host that already has another
  smoke running. Same discipline as
  `cds-kernel-deduce-smoke` (8.3b2a) and
  `cds-kernel-smoke` (8.3a foundation).
- **Per-request `options` overrides — pin the binaries.** Both
  smokes set `options.z3_path = ".bin/z3"` and
  `options.cvc5_path = ".bin/cvc5"` (absolute paths via
  `cargo_workspace_root().join(".bin/z3")`) so the test does **not**
  rely on `$PATH` resolution inside daprd's environment. Same for
  `options.kimina_url` if a non-default Kimina endpoint is exercised.
  This proves the 8.3b2a `KernelServiceState` env-resolution path
  works as a default but is correctly overridable by per-request
  `options`.
- **Final close-out gate.** `cargo test --workspace` green (target:
  8.3b2a's ~143 pass + 2 new gated smokes when binaries+Kimina are
  present, otherwise ~143 pass + 2 SKIPs); clippy clean; fmt clean;
  pytest 95/95 untouched; `just rs-service-smoke` (or
  `just rs-service-pipeline-smoke`) covers all three pipeline
  Dapr cases; `just dapr-smoke` (Task 8.1 gate) still passes;
  manual end-to-end check: all six Phase 0 endpoints (kernel
  `/healthz` + `/v1/{deduce,solve,recheck}`; harness `/healthz` +
  `/v1/{ingest,translate}`) round-trip through their respective
  daprd sidecars. **This is the close-out of 8.3b**; 8.4 then
  composes them via Workflow.
- **SIGTERM-first warden escalation comes due in 8.4** (ADR-014 §9 →
  ADR-015 §8 → ADR-016 §7 → ADR-018 §6 → ADR-019 §11 → ADR-020 §6 —
  still deferred until then). 8.3b2b does **not** unblock that
  decision — it only proves the kernel HTTP boundary preserves
  per-request subprocess hygiene.

## Open notes for Task 8.4a — Dapr cluster bring-up + production SIGTERM-first warden

- **Scope (Rust foundation, three work items):**
  1. **Dapr cluster Justfile recipes.** Three new recipes, two
     symmetric teardowns:
     - `placement-up` — `nohup .bin/.dapr/.dapr/bin/placement
       --port 50005 > target/dapr-placement.log 2>&1 & echo $! >
       target/dapr-placement.pid`. Idempotent skip if pid-file
       points at a live PID. Pins `:50005` (Dapr-1.17 default).
     - `scheduler-up` — symmetric to `placement-up`. `:50006`
       default. Pid-file `target/dapr-scheduler.pid`. Log
       `target/dapr-scheduler.log`.
     - `dapr-cluster-up` — composes both; idempotent.
     - `placement-down` / `scheduler-down` — read pid-file, send
       SIGTERM, wait up to 5s, send SIGKILL on grace expiry. Same
       shape as `tests/common::sigterm_then_kill` but lifted to
       a small bash function in the Justfile.
     - `dapr-cluster-down` — composes both teardowns.
     - `dapr-cluster-status` — prints both PIDs (or `not running`),
       log paths, bound ports.
     Pid-files live under `target/` so `cargo clean` reclaims
     them; the recipes do not touch git tracked state. Use
     `setsid` on Linux so `Ctrl-C` in the launching shell does
     not bleed into the background processes (each gets its own
     process group).
  2. **Production SIGTERM-first warden refactor.** `crate::solver::
     warden::run_with_input` currently uses
     `tokio::time::timeout(wall_clock, child.wait_with_output())`
     and on expiry drops the future, which drops the child handle,
     which `kill_on_drop(true)` SIGKILLs (warden.rs:104-115). The
     new shape:
     ```
     match timeout(wall_clock, collect).await {
         Ok(Ok(out)) => Ok(...),
         Ok(Err(source)) => Err(WardenError::Io { ... }),
         Err(_elapsed) => {
             // SIGTERM first
             if let Some(pid) = child.id() {
                 let _ = nix::sys::signal::kill(
                     nix::unistd::Pid::from_raw(pid as i32),
                     nix::sys::signal::Signal::SIGTERM,
                 );
             }
             // Grace window
             match timeout(grace, child.wait_with_output()).await {
                 Ok(Ok(out)) => Ok(...), // child exited on TERM
                 _ => {
                     // Fall through to kill_on_drop SIGKILL
                     Err(WardenError::Timeout { bin, timeout: wall_clock })
                 }
             }
         }
     }
     ```
     Note: the wall_clock budget is still considered exceeded if
     the child *exits* during the grace window — the budget was
     real, only the kill mechanism changed. The decision: if the
     child exits within grace with a non-zero status, return
     `WardenError::Timeout` (not `Ok(...)` with the partial
     output) — operators want to know the deadline was missed.
     Grace defaults to `Duration::from_millis(500)`. Add a
     `pub const DEFAULT_TIMEOUT_GRACE: Duration =
     Duration::from_millis(500);` constant adjacent to the existing
     warden types.
  3. **`nix` promotion.** `nix` is currently in
     `crates/kernel/Cargo.toml` `[dev-dependencies]` (added in
     8.3a per ADR-018 §6 narrow auth). 8.4a moves it to
     `[dependencies]` with the same feature set
     (`default-features = false, features = ["signal"]`). Also
     promote at the workspace level if the workspace `Cargo.toml`
     declares it (check before promoting). The narrow auth
     justification for SIGTERM in `tests/common.rs` extends
     naturally to production warden via ADR-021 §4 ratification.
- **Warden tests grow by two cases.** Append after the existing
  three tests in `crates/kernel/src/solver/warden.rs::tests`:
  - `timeout_sigterm_first_when_child_traps_term`:
    `bash -c 'trap "exit 0" TERM; while :; do sleep 1; done'`.
    `wall_clock = 100ms`, `grace = 200ms`. Assert
    `WardenError::Timeout { timeout: 100ms }` and elapsed
    `Duration` ∈ `[100ms, 100ms + 200ms + 50ms-margin]`. Skip
    when `/bin/bash` is unavailable (extremely portable on
    Linux dev hosts).
  - `timeout_sigkill_fallback_when_child_ignores_term`:
    `bash -c 'trap "" TERM; while :; do sleep 1; done'`.
    `wall_clock = 100ms`, `grace = 200ms`. Assert
    `WardenError::Timeout` and elapsed `Duration` ∈
    `[100ms + 200ms, 100ms + 200ms + 200ms-margin]` (some slack
    for tokio scheduling + SIGKILL delivery).
  Use `tokio::time::Instant::now()` to measure elapsed; do not
  rely on the warden returning timing data (the public API does
  not expose it).
- **Optional readiness probe flip.** `tests/common::wait_until_ready`
  currently probes `/v1.0/healthz/outbound`. Once 8.4a's
  `dapr-cluster-up` is callable, run all five existing daprd-driven
  integration tests against `/v1.0/healthz` with the cluster up.
  If they stay green, flip the helper. If they fail (e.g., timing
  flakes between sidecar boot + placement registration), keep
  outbound and document the asymmetry in
  `tests/common.rs::wait_until_ready` doc-comment so 8.4b's
  pipeline test pre-flights the full healthz separately. The
  decision is session-time empirical, not pre-committed in this
  ADR.
- **`WardenError` shape preserved.** No new variant. The
  two-stage escalation is internal. Callers
  (`solver::z3`, `solver::cvc5`, `service::handlers`,
  `service::errors::solver_error_kind`) all continue to consume
  the same enum — no downstream churn.
- **Gate (8.4a target):**
  - `cargo test --workspace` → 153 pass (151 baseline + 2 new
    warden cases).
  - `cargo clippy --workspace --all-targets -- -D warnings` →
    clean.
  - `cargo fmt --all -- --check` → clean.
  - `uv run pytest` → 95 pass (Python untouched).
  - `uv run ruff check .` → clean.
  - `just dapr-cluster-up` followed by `just dapr-cluster-status`
    prints both PIDs + log paths + bound ports.
  - `just dapr-cluster-down` reclaims both children (verified by
    `pgrep -f placement` / `pgrep -f scheduler` returning empty).
  - `just rs-service-pipeline-smoke` still 2/2 (warden refactor
    must not regress the existing solver/lean integration tests
    when binaries are present).
  - `just env-verify` → ✓.
- **Out of scope (8.4b):** Python `cds_harness.workflow` package;
  Dapr Python SDK introduction; aggregated envelope; `@activity`
  callables; `just dapr-pipeline`; end-to-end pytest smoke. All
  land in 8.4b once 8.4a's cluster + warden foundation is in
  place.
- **PHASE marker** still `0` on `lib.rs`. 8.4b decides what
  `PHASE = 1` means (probably: end-to-end pipeline runs under
  Dapr Workflow against a canonical guideline).

## Open notes for Task 8.4b — End-to-end Dapr Workflow + close-out

- **Scope (Python composition + close-out, four work items):**
  1. **`cds_harness.workflow` package** under
     `python/cds_harness/`:
     - `__init__.py` — public re-exports (`run_pipeline`,
       `pipeline_workflow`, the five activity callables).
     - `pipeline.py` — `@workflow` decorated `pipeline_workflow`
       function. Five `yield ctx.call_activity(...)` calls that
       chain `ingest → translate → deduce → solve → recheck`.
       Returns the aggregated envelope (see §3).
     - `activities.py` — five `@activity` callables. Each is a
       thin `httpx`-over-daprd wrapper:
       ```python
       @activity(name="cds.ingest")
       async def ingest_activity(ctx, request: dict) -> dict:
           url = f"http://127.0.0.1:{DAPR_HTTP_PORT}/v1.0/invoke/cds-harness/method/v1/ingest"
           async with httpx.AsyncClient() as client:
               resp = await client.post(url, json=request, timeout=30)
               resp.raise_for_status()  # 422 → activity exception → workflow retry
               return resp.json()
       ```
       Same shape for the other four activities. The kernel-side
       app-id is `cds-kernel`; the deduce/solve/recheck paths
       are `/v1/deduce`, `/v1/solve`, `/v1/recheck` respectively.
     - `__main__.py` — argparse + `dapr.workflow.WorkflowRuntime`
       setup. CLI subcommand `run-pipeline --payload <path>
       --guideline <path>` that:
       a. Loads the payload + guideline from disk (re-using the
       existing `cds_harness.ingest.load_*` + `cds_harness.translate`
       helpers).
       b. Schedules a workflow instance via the SDK.
       c. Polls until terminal (`COMPLETED` / `FAILED`).
       d. Prints the aggregated envelope as pretty JSON.
       e. Exits 0 on `COMPLETED`, non-zero on `FAILED` (with
       envelope still printed so an operator sees the trace).
  2. **Dapr Python SDK introduction (ADR-017 §5 reversal,
     scoped).** Add to `[project.dependencies]` in `pyproject.toml`:
     - `dapr>=1.17` (resolved against Dapr 1.17.0 server / runtime
       — pin major.minor; let patch float).
     - `dapr-ext-workflow>=1.17` (Workflow extension package).
     The SDK owns `WorkflowRuntime`, `@workflow`, `@activity`,
     replay-deterministic activity scheduling, and activity-id
     correlation tagging for tracing. Service-invocation calls
     inside activities **stay on plain `httpx`** — one HTTP POST
     does not warrant typed bindings, and ADR-017 §5's argument
     remains valid at that boundary.
  3. **Aggregated envelope** (in-band JSON; see ADR-021 §3 + §7
     for rationale):
     ```json
     {
       "payload":  { /* ClinicalTelemetryPayload */ },
       "ir":       { /* OnionLIRTree */ },
       "matrix":   { /* SmtConstraintMatrix */ },
       "verdict":  { /* Verdict */ },
       "trace":    { /* FormalVerificationTrace */ },
       "recheck":  { /* LeanRecheckWire (snake_case severity) */ }
     }
     ```
     Each stage's output is keyed by stage name; the workflow
     accumulates the dict across activity invocations. Reasons
     for in-band over state-store handles: Phase 0 small payloads,
     replay determinism, JSON-over-TCP discipline (constraint C6),
     direct inspectability for `tee`/`jq` debugging.
  4. **`just dapr-pipeline` recipe.** Top-level orchestrator:
     ```
     dapr-pipeline:
         #!/usr/bin/env bash
         set -euo pipefail
         just dapr-cluster-up                          # 8.4a
         just py-service-dapr &                        # background
         echo $! > target/dapr-py-service.pid
         just rs-service-dapr &                        # background
         echo $! > target/dapr-rs-service.pid
         # wait for both /v1.0/healthz to return 204 against the
         # daprd HTTP ports (read from per-app sidecar logs); fail
         # the recipe if either stays unready after 30s
         python -m cds_harness.workflow run-pipeline \
             --payload data/sample/icu-monitor-01.json \
             --guideline data/guidelines/contradictory-bound.txt \
             > target/dapr-pipeline-output.json
         # assert three flags:
         jq -e '.verdict.breach_summary | length > 0' \
             target/dapr-pipeline-output.json
         jq -e '.trace.sat == false' target/dapr-pipeline-output.json
         jq -e '.recheck.ok == true' target/dapr-pipeline-output.json
         # teardown reverse order
         kill -TERM $(cat target/dapr-rs-service.pid) || true
         kill -TERM $(cat target/dapr-py-service.pid) || true
         just dapr-cluster-down
     ```
     The pid-tracking shape matches 8.4a's cluster recipes.
- **End-to-end pytest smoke.** New
  `python/tests/test_dapr_pipeline.py`. Single
  `@pytest.mark.skipif`-gated test (gates: `.bin/dapr` + slim
  daprd + `.bin/.dapr/.dapr/bin/placement` +
  `.bin/.dapr/.dapr/bin/scheduler` + `.bin/z3` + `.bin/cvc5` +
  `CDS_KIMINA_URL`). Spawns the cluster + both sidecars in
  fixtures (yield-style fixtures with SIGTERM-first cleanup);
  drives the canonical pipeline through `WorkflowRuntime`;
  asserts the same three flags as the Justfile recipe; tears
  everything down via the SIGTERM-first cleanup discipline that
  8.4a's warden refactor codifies. Pytest is the CI-friendly
  shape; the Justfile recipe is the developer-friendly shape;
  both ship.
- **Per-stage tracing.** Every activity gets
  `with tracer.start_as_current_span(f"workflow.{stage}"):`-style
  span instrumentation (use OpenTelemetry Python SDK; the
  harness already imports it transitively via uvicorn). The
  Dapr Workflow SDK auto-correlates spans by activity-id; the
  kernel side already emits matching span structure via
  `#[tracing::instrument(skip(req), fields(stage = "..."))]`
  (ADR-019 §6), so the trace tree is end-to-end across the
  Python harness ↔ Rust kernel boundary.
- **Readiness gate after 8.4a.** If 8.4a flipped
  `tests/common::wait_until_ready` from `/v1.0/healthz/outbound`
  to `/v1.0/healthz`, the pytest fixtures here use the same
  full-healthz probe. If 8.4a kept outbound, the pipeline test
  pre-flights `/v1.0/healthz` separately after `dapr-cluster-up`
  succeeds (the helper still works against either probe; only
  the floor changes).
- **Gate (8.4b — close-out of Task 8):**
  - `uv run pytest` → 96 pass (95 baseline + 1 new end-to-end
    smoke when full bin set + `CDS_KIMINA_URL` present, else
    95 + 1 SKIP).
  - `uv run ruff check .` → clean.
  - `cargo test --workspace` → 153 pass (unchanged from 8.4a).
  - `cargo clippy --workspace --all-targets -- -D warnings` →
    clean.
  - `cargo fmt --all -- --check` → clean.
  - `just dapr-pipeline` end-to-end against
    `data/guidelines/contradictory-bound.txt` returns
    `verdict.breach_summary != [] ∧ trace.sat = false ∧
    recheck.ok = true`.
  - Manual run: `just GUIDELINE_PATH=data/guidelines/hypoxemia-trigger.txt
    dapr-pipeline` returns `verdict.breach_summary != [] ∧
    trace.sat = true ∧ recheck.ok = true` (consistent guideline,
    sat trace, recheck still passes).
  - `just env-verify` → ✓.
  - **Six Phase 0 endpoints round-trip end-to-end via Workflow:**
    kernel `/healthz` + `/v1/{deduce, solve, recheck}`; harness
    `/healthz` + `/v1/{ingest, translate}`. **This closes Task 8.**
- **PHASE marker.** `lib.rs::PHASE = 0` flips to `PHASE = 1` in
  this session — Phase 1 is "end-to-end pipeline runs under Dapr
  Workflow against a canonical guideline" per ADR-021 §1.
- **Dapr Python SDK constraint check.** Verify Dapr 1.17 server +
  SDK 1.17.x compatibility via `web-search "Dapr Python SDK 1.17
  WorkflowRuntime 2026"` per Plan §10 #4 before pinning. The
  SDK's WorkflowRuntime API has stabilized between 1.13 and 1.17;
  but worth a single confirmation search at session-time.

## Session 2026-04-30 — Task 8.3a close-out

Shipped the Phase 0 Rust kernel service foundation. A new
`cds_kernel::service` module binds an axum router behind a thin
`cds-kernel-service` binary, runnable both standalone (`cargo run --bin
cds-kernel-service` / `just rs-service`) and under a Dapr sidecar
(`just rs-service-dapr`). Service-invocation works against the Phase 0
slim runtime even with placement/scheduler down — `/v1.0/invoke/cds-kernel/
method/healthz` routes through daprd without touching the actor
subsystem. ADR-018 codifies the kernel-side service contract.

**Module layout (`crates/kernel/src/service/`):**

| File         | Role                                                                                                                          |
| ------------ | ----------------------------------------------------------------------------------------------------------------------------- |
| `mod.rs`     | Public re-exports (`build_router`, `KernelHealthz`, `ErrorBody`, `error_response`, host/port helpers, all constants).         |
| `app.rs`     | `build_router()` factory; `KernelHealthz` (owns its strings so polyglot decoders round-trip cleanly); `tower_http::trace::TraceLayer` wired. |
| `config.rs`  | `resolve_host` / `resolve_port` from `CDS_KERNEL_HOST` / `CDS_KERNEL_PORT`; `parse_port_raw` is the pure helper unit-tested in isolation. |
| `errors.rs`  | `ErrorBody { error, detail }` + `IntoResponse` lifting to HTTP 422 — same wire shape as the Python harness service (ADR-017 §2). |

**Binary (`crates/kernel/src/bin/cds_kernel_service.rs`):** registered
as `[[bin]] cds-kernel-service`. Multi-thread tokio runtime,
`axum::serve(...).with_graceful_shutdown(...)` listening on Ctrl-C +
Unix SIGTERM; `--help` / `-h` only — every other knob comes from the
environment so the Justfile / Dapr CLI is the single source of
configuration truth. `tracing_subscriber::fmt().try_init()` so a stray
re-init (test or sidecar combo) does not panic.

**Endpoint contract (constraint C6 — JSON-over-TCP):**

| Method | Path        | Request body | Response body                                      |
| ------ | ----------- | ------------ | -------------------------------------------------- |
| GET    | `/healthz`  | —            | `{status, kernel_id, phase, schema_version}`       |

`/v1/deduce`, `/v1/solve`, `/v1/recheck` are forward-declared in module
docs but are out of scope for 8.3a; they land in 8.3b.

**Justfile additions:**

| Recipe              | Behaviour                                                                                                                                                           |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `rs-service`        | Builds + runs the kernel HTTP service standalone (no Dapr). Honours `CDS_KERNEL_HOST` / `CDS_KERNEL_PORT`.                                                          |
| `rs-service-dapr`   | Pre-builds, then runs the binary under `dapr run --app-id cds-kernel …`. Service-invocation through the Dapr HTTP port routes to `:CDS_KERNEL_PORT/...`.            |
| `rs-service-smoke`  | **Task 8.3a foundation gate.** Runs the cargo integration test (`tests/service_smoke.rs`) — standalone HTTP + gated dapr sidecar, single-thread to avoid port races.|

**Tests (Rust workspace, all green):**

| Suite                                      | Count | Coverage                                                                                                                                                                                                          |
| ------------------------------------------ | ----- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Existing schema + canonical + deduce + solver + lean | 80    | unchanged from Task 7.                                                                                                                                                                                            |
| `service::config` unit                     | 5     | `parse_port_raw`: empty/whitespace → default; valid u16 happy paths; garbage rejected with `PortParse`; zero / overflow rejected with `PortOutOfRange`; negative rejected as `PortParse`.                          |
| `service::errors` unit                     | 3     | `ErrorBody` serde round-trip pin (`{"error":"…","detail":"…"}` exact JSON shape); `IntoResponse` lifts to HTTP 422; `error_response` honours explicit status (e.g., 500).                                          |
| `service::app` unit                        | 5     | `SERVICE_APP_ID` pinned to `"cds-kernel"`; healthz invariants (status / kernel_id / phase / schema_version); JSON serialization is byte-stable in field order; router serves `/healthz` via tower `oneshot`; unknown route → 404. |
| `bin::cds_kernel_service` unit             | 3     | `parse_argv` with no args is fine; `--help` / `-h` recognised as `HelpRequested`; unknown flag rejected as `UnknownArgument`.                                                                                      |
| `tests/service_smoke.rs` integration       | 2     | **Foundation gate:** standalone axum binds + serves `/healthz`; gated dapr sidecar drives the same path through `/v1.0/invoke/cds-kernel-smoke/method/healthz` with SIGTERM-first cleanup so daprd + the kernel binary don't orphan to PID 1. |

Final gate (all green):

- `cargo test --workspace` → **113 pass** (93 unit + 3 bin + 2 service_smoke + 5 deduce_smoke + 5 golden_roundtrip + 1 lean_smoke + 4 solver_smoke).
- `cargo clippy --workspace --all-targets -- -D warnings` → clean.
- `cargo fmt --all -- --check` → clean.
- `uv run pytest` → 95 pass (no Python regressions).
- `uv run ruff check .` → clean.
- `just rs-service-smoke` → 2/2 with `--nocapture`; clean teardown (no daprd / cds-kernel-service orphans).
- `just dapr-smoke` → ✓ (Task 8.1 gate held).
- Manual `just rs-service-dapr` (verified out-of-band) → daprd loads `cds-pubsub` + `cds-statestore`; `curl http://127.0.0.1:<dapr-http>/v1.0/invoke/cds-kernel/method/healthz` returns `{"status":"ok","kernel_id":"cds-kernel","phase":0,"schema_version":"0.1.0"}`.

**Dependencies added:**

- `axum = "0.8"` (workspace + kernel) with `default-features = false`,
  features `["http1", "json", "tokio", "macros"]`. Resolved 0.8.9.
- `tower = "0.5"` (workspace + kernel) with `default-features = false`,
  features `["util"]` for `ServiceExt::oneshot` in unit tests.
- `tower-http = "0.6"` (workspace + kernel) with `default-features = false`,
  features `["trace"]` for the per-request `TraceLayer`.
- `nix = "0.31"` (kernel `[dev-dependencies]` only) with
  `default-features = false`, features `["signal"]` — used **only** by
  the integration test for SIGTERM-first cleanup of the dapr CLI's
  grandchildren. Does not enter the production binary.

**Decisions captured in ADR-018** — Phase 0 Rust kernel service
foundation contract: axum 0.8 with minimal feature set; default port
8082 (harness holds 8081); same `/v1.0/healthz/outbound` readiness
probe as ADR-017 (placement still deferred to 8.4); `ErrorBody { error,
detail }` envelope mirrors the Python `_error_handler` shape; `[[bin]]
cds-kernel-service` is the entrypoint; SIGTERM-first cleanup in the
integration test is **narrowly authorized** for the dapr CLI process —
the kernel solver warden's own SIGTERM-first escalation (ADR-014 §9)
**remains deferred to Task 8.4**.

## Open notes for Task 8.3b — Rust kernel pipeline endpoints

- **Scope:** wire the existing kernel modules into the axum router.
  Three handlers, each lifting domain errors to `ErrorBody` (HTTP 422):
  - `POST /v1/deduce` — request `{payload: ClinicalTelemetryPayload, rules?: Phase0Thresholds}`; response `Verdict` from `cds_kernel::deduce::evaluate(&payload, &rules.unwrap_or_default())`. Default `Phase0Thresholds::default()` if absent.
  - `POST /v1/solve` — request `{matrix: SmtConstraintMatrix, options?: VerifyOptions-shaped knobs}`; response `FormalVerificationTrace` from `cds_kernel::solver::verify(&matrix, &opts).await`. The warden + Z3/cvc5 binaries (.bin/) are required at runtime; surface a `WardenError::Spawn` as 422 with `{error: "warden", detail}`.
  - `POST /v1/recheck` — request `{trace: FormalVerificationTrace, options?: LeanOptions-shaped knobs}`; response `LeanRecheck` from `cds_kernel::lean::recheck(&trace, &opts).await`. `kimina_url` defaults from `LeanOptions::default()` (127.0.0.1:8000) but should also accept an env override (e.g., `CDS_KIMINA_URL`).
- **Discriminated request envelopes.** The Python harness uses
  `Field(discriminator="format")` on `/v1/ingest`. None of the kernel
  endpoints have alternative request shapes today; if 8.3b adds one
  (e.g., `{matrix: …}` vs `{matrix_path: "…"}` to load from disk),
  use serde's `#[serde(tag = "...")]` discriminator pattern.
- **`AppState`.** 8.3a deliberately ships no shared state. 8.3b should
  introduce a `KernelServiceState { verify_options: VerifyOptions,
  lean_options: LeanOptions }` *only if* the env-driven overrides
  benefit from one-shot resolution at boot rather than per-request
  parsing. The healthz handler should remain stateless.
- **Dapr smoke gate.** Extend `tests/service_smoke.rs` (or split into
  `service_pipeline_smoke.rs`) with one happy-path sidecar test per
  endpoint, mirroring the harness side's
  `test_dapr_sidecar_drives_ingest_and_translate`. Use the canonical
  fixtures already on disk:
  `data/guidelines/contradictory-bound.{txt,recorded.json}` (unsat —
  drives `/v1/solve`); the solver test then hands the trace to
  `/v1/recheck` (gated by `CDS_KIMINA_URL`). For `/v1/deduce`, drive
  one of the existing telemetry payloads and assert a non-empty
  `breach_summary`.
- **Per-stage tracing.** The `TraceLayer` already emits a span per
  request. 8.3b should annotate each handler with a
  `#[tracing::instrument(skip(payload), fields(stage = "deduce"))]`
  attribute so the Workflow harness (Task 8.4) can correlate stage
  events without parsing free-form messages.
- **PHASE marker.** Still `0` on `lib.rs`. ADR-013 / Task 5 / Task 6
  / Task 7 / Task 8.1 / Task 8.2 each carried this forward unchanged.
  Decide what `PHASE = 1` means in 8.4 (probably: end-to-end
  pipeline runs under Dapr).
- **SIGTERM-first warden escalation** is **still deferred** to 8.4
  (ADR-018 §6 narrowly authorizes SIGTERM only for the integration
  test's dapr CLI cleanup; production kernel-spawned solver children
  remain SIGKILL-on-drop).
- **Free-port allocator.** `service_smoke.rs` already has
  `pick_free_port`; 8.3b can lift it into a shared `tests/common.rs`
  module if more than one suite needs it.

## Open notes for Task 8.4 — End-to-end Dapr Workflow

- **Scope:** Python Dapr Workflow that chains
  `ingest → translate → deduce → solve → recheck`. Each stage is a
  Workflow `activity` that calls the appropriate sidecar via
  service-invocation. The Workflow output is the aggregated envelope:
  `{ payload, ir, matrix, verdict, trace, lean_recheck }`.
- **Placement + scheduler bring-up.** Slim init *stages* the binaries
  but doesn't start them. 8.4 owns `just placement-up` /
  `just scheduler-up` (background processes via tokio
  `Command::kill_on_drop(true)` per ADR-004), or rolls them into a
  single `just dapr-pipeline` recipe that brings everything up,
  drives the pipeline, then tears down. Once placement is up the
  readiness gate flips from `/v1.0/healthz/outbound` (Phase 0 8.2 / 8.3
  shape) to `/v1.0/healthz`.
- **SIGTERM-first warden escalation comes due here** (ADR-014 §9 →
  ADR-015 §8 → ADR-016 §7 → ADR-018 §6 — still deferred). Decide
  whether to amend ADR-014 to enable two-stage escalation for
  kernel-spawned solver children, or accept Phase 0 SIGKILL-only and
  amend ADR-014 to make that the permanent stance.
- **Tracing.** Each stage emits a `tracing` span + a Dapr Workflow
  event. Final aggregated trace rides on the Workflow output.
- **Decide:** in-band JSON envelope vs. Dapr state-store handle for
  the cross-stage payload. JSON envelope is simplest; state-store
  handles cleaner if payloads grow.
- **Gate:** `just dapr-pipeline` runs end-to-end against a canonical
  guideline; verification flag round-trips.

## Session 2026-04-30 — Task 8.2 close-out

Shipped the Phase 0 Python harness service. A new `cds_harness.service`
package binds the existing ingest + translate machinery behind a thin
FastAPI app, runnable both standalone (`uv run python -m
cds_harness.service`) and under a Dapr sidecar (`dapr run --app-id
cds-harness …`). Service-invocation works against the Phase 0 slim
runtime even with placement/scheduler down — `/v1.0/invoke/cds-harness/
method/...` routes through daprd without touching the actor subsystem.

**Module layout (`python/cds_harness/service/`):**

| File          | Role                                                                                                                          |
| ------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `__init__.py` | Public re-exports (constants + `create_app` + `resolve_host` / `resolve_port`).                                               |
| `__main__.py` | argparse + uvicorn entrypoint; honours `CDS_HARNESS_HOST` / `CDS_HARNESS_PORT`; `--host` / `--port` overrides.                |
| `app.py`      | `create_app()` factory; `_StrictModel` request envelopes (discriminated `format` for ingest); `_InlineAdapter` → translator.  |

**Endpoint contracts (constraint C6 — JSON-over-TCP):**

| Method | Path             | Request body                                                                                          | Response body                                                                       |
| ------ | ---------------- | ----------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| GET    | `/healthz`       | —                                                                                                     | `{status, harness_id, phase, schema_version}`                                       |
| POST   | `/v1/ingest`     | `{format: "json", envelope: {...ClinicalTelemetryPayload}}` ∨ `{format: "csv", csv_text, meta, file_label?}` | `{payload: {...ClinicalTelemetryPayload}}`                                          |
| POST   | `/v1/translate`  | `{doc_id, text, root: OnionLNode, logic?, smt_check?}`                                                | `{tree: OnionLIRTree, matrix: SmtConstraintMatrix, smt_check: "sat"\|"unsat"\|"unknown"\|null}` |

`IngestError` and `TranslateError` lift to HTTP 422 with
`{error, detail}`; pydantic validation errors trigger FastAPI's default
422.

**Helpers added to support inline JSON-over-TCP ingestion** (no
behaviour change to file-based loaders):

- `cds_harness.ingest.json_loader.load_json_envelope(raw)` — validate +
  canonicalize a parsed dict envelope.
- `cds_harness.ingest.csv_loader.load_csv_text(csv_text, meta, *, file_label)` —
  in-memory variant of `load_csv`. Existing `load_csv(path)` now
  delegates to the text variant after reading the CSV bytes.

**Console scripts (`[project.scripts]` added):**

- `cds-ingest`          → `cds_harness.ingest.cli:main`
- `cds-translate`       → `cds_harness.translate.cli:main`
- `cds-harness-service` → `cds_harness.service.__main__:main`

**Justfile additions:**

| Recipe              | Behaviour                                                                                                                                                              |
| ------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `py-service`        | Run the FastAPI app standalone (no Dapr). Honours `CDS_HARNESS_HOST` / `CDS_HARNESS_PORT`.                                                                             |
| `py-service-dapr`   | Run the app under `dapr run --app-id cds-harness …`. Service-invocation through the Dapr HTTP port routes to `:CDS_HARNESS_PORT/v1/...`.                               |

**Tests (Python suite, all green):**

| Suite                                          | Count | Coverage                                                                                                                                                                 |
| ---------------------------------------------- | ----- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Existing (smoke + schema + ingest + translate + Dapr foundation) | 79    | unchanged — no regressions.                                                                                                                                              |
| `python/tests/test_service.py` (new)           | 16    | `/healthz` shape + constants pin; `_InlineAdapter` structural-protocol conformance; `resolve_port` defaults / garbage / overrides; `/v1/ingest` JSON + CSV happy paths; ingest 422 paths (invalid envelope, missing `source`, unknown format); `/v1/translate` happy + smt_check sat/unsat + doc_id mismatch + invalid root; **end-to-end** sidecar smoke (gated): `dapr run` → uvicorn → ingest + translate via `/v1.0/invoke/cds-harness/method/v1/...`. |

Final gate (all green):

- `uv run pytest` → **95 pass** (79 prior + 16 new).
- `uv run ruff check .` → clean.
- `cargo test --workspace` → 95 pass (no Rust changes — sanity).
- `cargo clippy --workspace --all-targets -- -D warnings` → clean.
- `cargo fmt --all -- --check` → clean.
- `just dapr-smoke` → ✓ both components loaded; workflow engine started; clean shutdown (Task 8.1 gate held).
- `cds-harness-service --help` / `cds-ingest --help` / `cds-translate --help` → all 0 exit.

**Dependencies added:**

- `fastapi>=0.115` (resolved 0.136.1) — ASGI framework.
- `uvicorn[standard]>=0.32` (resolved 0.46.0) — ASGI server (uvloop +
  httptools + websockets + watchfiles + python-dotenv).
- `httpx>=0.28` (resolved 0.28.1) — async HTTP client (used by the
  sidecar smoke + by future Dapr SDK Phase-1 swap; FastAPI's TestClient
  already pulls it transitively).
- Deprecated `[tool.uv] dev-dependencies` migrated to top-level
  `[dependency-groups] dev = [...]` per the carry-forward note from
  Task 8 — `uv run` no longer surfaces the deprecation warning.

**Decisions captured in ADR-017** — the Phase 0 Python harness service
contract: JSON-over-TCP only (no Dapr SDK in Phase 0 — `httpx`
sufficient); FastAPI + uvicorn (over Flask/Quart) for ASGI + automatic
OpenAPI; `/v1.0/invoke/cds-harness/method/v1/...` is the Dapr
service-invocation route; `/v1.0/healthz/outbound` (not `/v1.0/healthz`)
is the sidecar-readiness probe in Phase 0 because placement/scheduler
are deferred to Task 8.4 (ADR-016 §6); the discriminated `format` field
on `/v1/ingest` keeps the wire schema explicit; `_InlineAdapter` is a
structural `AutoformalAdapter` so the file-system roundtrip via
`RecordedAdapter` becomes optional at the service boundary.

## Open notes for Task 8.3 — Rust kernel Dapr service

- **Scope:** thin `axum` (or `hyper`) JSON-over-TCP service in
  `crates/kernel/src/bin/cds_kernel_service.rs` exposing
  `POST /v1/deduce` (`ClinicalTelemetryPayload` → `Verdict`),
  `POST /v1/solve` (`SmtConstraintMatrix` → `FormalVerificationTrace`),
  `POST /v1/recheck` (`FormalVerificationTrace` → `LeanRecheck`).
- The warden + Z3/cvc5 + Lean clients already exist; the binary just
  binds them behind HTTP routes.
- `dapr run --app-id cds-kernel --app-port <N> -- cargo run --bin
  cds_kernel_service` boots the sidecar. Smoke = cargo integration test
  driving all three endpoints through daprd's
  `:3500/v1.0/invoke/cds-kernel/method/v1/...`. Mirror the readiness
  gate from 8.2 — probe the kernel's `/healthz` first, then daprd's
  `/v1.0/healthz/outbound` (placement still down in Phase 0).
- `lib.rs::PHASE = 0`. Decide what `PHASE = 1` means in 8.3 / 8.4
  (probably: end-to-end pipeline runs under Dapr).
- Carry the same JSON-over-TCP discipline: discriminated request
  envelopes; `serde(deny_unknown_fields)`; lifted error → HTTP 422
  with `{error, detail}`.
- Register a `cds-kernel-service` cargo `[[bin]]` so `dapr run -- cds_kernel_service`
  works without an explicit `cargo run …` wrapper.
- A `tower-http::trace::TraceLayer` plus the existing `tracing`
  spans gives per-stage trace continuity for Task 8.4's Workflow.

## Open notes for Task 8.4 — End-to-end Dapr Workflow

- **Scope:** Python Dapr Workflow that chains
  `ingest → translate → deduce → solve → recheck`. Each stage is a
  Workflow `activity` that calls the appropriate sidecar via
  service-invocation. The Workflow output is the aggregated envelope:
  `{ payload, ir, matrix, verdict, trace, lean_recheck }`.
- **Placement + scheduler bring-up.** Slim init *stages* the binaries
  but doesn't start them. 8.4 owns `just placement-up` /
  `just scheduler-up` (background processes via tokio
  `Command::kill_on_drop(true)` per ADR-004), or rolls them into a
  single `just dapr-pipeline` recipe that brings everything up,
  drives the pipeline, then tears down. Once placement is up the
  readiness gate flips from `/v1.0/healthz/outbound` (Phase 0 8.2/8.3
  shape) to `/v1.0/healthz`.
- **SIGTERM-first warden escalation comes due here** (ADR-014 §9 →
  ADR-015 §8 → ADR-016 §7 → still deferred from 8.2).
- **Tracing.** Each stage emits a `tracing` span + a Dapr Workflow
  event. Final aggregated trace rides on the Workflow output.
- **Decide:** in-band JSON envelope vs. Dapr state-store handle for
  the cross-stage payload. JSON envelope is simplest; state-store
  handles cleaner if payloads grow.
- **Gate:** `just dapr-pipeline` runs end-to-end against a canonical
  guideline; verification flag round-trips.

## Session 2026-04-30 — Task 8.1 close-out

Shipped the Phase 0 Dapr foundation. Slim self-hosted Dapr 1.17 was
already staged under `.bin/.dapr/.dapr/` from a prior session; this
session pinned and codified the install path, authored the locked
component selections, and locked the smoke gate. `dapr/components/`
materialises both Phase 0 components; `dapr/config.yaml` materialises
the Phase 0 Configuration; the Justfile gains a `Dapr` block; pytest
gains a foundation suite.

**Module layout (`dapr/`):**

| File                                       | Role                                                                                                      |
| ------------------------------------------ | --------------------------------------------------------------------------------------------------------- |
| `components/pubsub-inmemory.yaml`          | `pubsub.in-memory` v1 — ephemeral broker, named `cds-pubsub`. Phase 0 only.                               |
| `components/state-store-inmemory.yaml`     | `state.in-memory` v1 named `cds-statestore`, `actorStateStore=true` (Workflow requirement on Dapr 1.17).  |
| `config.yaml`                              | Configuration `cds-config` — tracing on stdout (sample 1.0), metrics on, mTLS off (single dev host).      |
| `README.md`                                | Phase 0 layout + Justfile recipe map + sidecar invocation contract.                                       |

**Justfile additions:**

| Recipe              | Behaviour                                                                                                                                                            |
| ------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `fetch-dapr`        | Idempotent slim install. Fetches `dapr` CLI v`{{DAPR_VERSION}}` (default `1.17.0`) to `.bin/dapr` if missing; runs `dapr init -s --runtime-path .bin/.dapr` if `.bin/.dapr/.dapr/bin/daprd` missing. |
| `dapr-init`         | Wipes `.bin/.dapr/` then re-runs `fetch-dapr`. Forces re-init.                                                                                                       |
| `dapr-status`       | Prints CLI version, daprd version, slim binary inventory, components dir contents, config path.                                                                      |
| `dapr-clean`        | Removes `.bin/.dapr/` and `.bin/dapr`. Source / manifests untouched.                                                                                                 |
| `dapr-smoke`        | **Foundation gate.** Runs `dapr run --app-id cds-dapr-foundation-smoke … -- sleep 2`; greps the captured log for the five required markers (see ADR-016 §9).         |
| `bootstrap`         | Now also depends on `fetch-dapr` so a fresh checkout has Dapr ready end-to-end.                                                                                      |

**Tests (Python suite):**

| Suite                                                      | Count | Coverage                                                                                                                                                                                                                                  |
| ---------------------------------------------------------- | ----- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Existing schema + ingest + translate + smoke               | 71    | (unchanged — no regressions).                                                                                                                                                                                                             |
| `python/tests/test_dapr_foundation.py` (new)               | 8     | components dir inventory; pubsub manifest schema; state-store manifest schema (incl. `actorStateStore=true` assertion); Configuration schema; component-name uniqueness; CLI version pin (`1.17.x`); daprd version pin; **end-to-end** `dapr run` smoke. |

Final gate (all green):

- `uv run pytest` → **79 pass** (71 prior + 8 new).
- `uv run ruff check .` → clean.
- `cargo test --workspace` → 95 pass (no Rust changes — sanity).
- `cargo clippy --workspace --all-targets -- -D warnings` → clean.
- `cargo fmt --all -- --check` → clean.
- `just dapr-smoke` → ✓ both components loaded; workflow engine started; clean shutdown.
- `just dapr-status` → CLI 1.17.0 / daprd 1.17.0 / slim binary inventory + project components dir listed.

**Dependencies added:**

- `pyyaml>=6.0` (dev + uv dev-dependencies). Already present transitively
  through `dapr` Python SDK install but pinned explicitly so the
  foundation tests stay reproducible.

**Decisions captured in ADR-016** — Phase 0 Dapr foundation contract:
slim self-hosted mode locked (no Docker / Redis / Zipkin); in-memory
pub/sub + state store (with `actorStateStore=true`) for Phase 0 with
Phase 1+ swap to durable backends; mTLS off on single dev host;
`tracing.samplingRate=1` + stdout exporter; sidecar invocation contract
(`dapr run --runtime-path .bin/.dapr --resources-path dapr/components
--config dapr/config.yaml …`); placement + scheduler bring-up
**deferred to Task 8.4** (the streamed `:50005` / `:50006` connection
warnings during 8.1's smoke are expected); SIGTERM-first warden
escalation rolls forward from ADR-014 §9 → ADR-015 §8 → ADR-016 §7
to Task 8.4.

## Session 2026-04-30 — Task 7 close-out

Shipped the Lean 4 interop layer under `crates/kernel/src/lean/`. Public
entrypoint `cds_kernel::lean::recheck(trace, opts) -> LeanRecheck` posts
a self-contained Lean snippet (defining the Alethe proof as a
`String` + four `#eval` `PROBE` lines) to a running Kimina headless
server via `POST /verify`, then parses the returned info messages back
into `LeanRecheck { ok, custom_id, env_id, elapsed_ms, messages, probes }`.

**Module layout (`crates/kernel/src/lean/`):**

| File         | Role                                                                                                  |
| ------------ | ----------------------------------------------------------------------------------------------------- |
| `mod.rs`     | `LeanOptions`, `LeanError`, `LeanRecheck`, `LeanMessage`, `LeanSeverity`, `recheck` entrypoint.       |
| `client.rs`  | `reqwest` POST `/verify`; permissive response decoder for results-array / top-level-array / single.   |
| `snippet.rs` | `render(alethe_proof) -> String` Lean-source generator + Lean-string escaper.                          |

**Tests (Rust workspace, all green):**

| Suite                                  | Count | Coverage                                                                                                               |
| -------------------------------------- | ----- | ---------------------------------------------------------------------------------------------------------------------- |
| Existing schema + canonical + deduce + solver | 70 | (unchanged from Task 6).                                                                                              |
| `lean::snippet` unit                   | 6     | escape ASCII / quotes+backslash / `\n\t\r` / UTF-8 BMP; render embeds proof + four probes; render is import-free; empty-proof edge case. |
| `lean::client` unit                    | 11    | endpoint builder; results-array / top-level-array / pick-by-custom-id envelopes; lean-error vetoes ok; missing-probe vetoes ok; invalid JSON; empty results array; severity aliases (`Info`/`warn`/`ERROR`/`level`/`text`); strip lean-eval quotes; `probes_satisfied` requires all four + positive `byte_len`. |
| `lean` (top-level) unit                | 4     | default options sanity; `recheck` rejects sat / unsat-without-proof; `recheck` surfaces `Transport` for unbound port. |
| `tests/lean_smoke.rs` integration      | 1     | **Gate (opt-in):** end-to-end `solver::verify(contradictory) → lean::recheck` against `$CDS_KIMINA_URL`; prints loud skip notice when env var absent.|

Final gate (all green):
- `cargo test --workspace` → **95 pass** (80 unit + 5 deduce_smoke + 5 golden_roundtrip + 1 lean_smoke + 4 solver_smoke).
- `cargo clippy --workspace --all-targets -- -D warnings` → clean.
- `cargo fmt --all -- --check` → clean.
- `uv run pytest` → 71 pass (no Python regressions).
- `uv run ruff check .` → clean.
- `just rs-lean` (new recipe) → 1/1 pass with `--nocapture` (skip notice when `CDS_KIMINA_URL` unset).

**Dependencies added:**
- `reqwest = { version = "0.13", default-features = false, features = ["json", "rustls", "webpki-roots"] }`
  (workspace + kernel crate). `rustls` (the 2026 feature name; 0.13's
  `rustls-tls` was renamed to `rustls`) avoids OpenSSL system deps;
  `webpki-roots` ships built-in roots so no platform CA store is
  needed.

**Plan amendment:** `.agent/Plan.md §6` "Theorem subprocesses" line
updated from "Kimina headless JSON-RPC" to "Kimina headless REST
(POST /verify)" — Plan said JSON-RPC, Kimina ships REST. Constraint
**C6** (JSON-over-TCP/IP and/or MCP) is satisfied because REST is
JSON-over-TCP. ADR-015 captures the rationale and the plan-vs-reality
clarification.

**Decisions captured in ADR-015** — Phase 0 Lean / Kimina contract:
operator-owned daemon lifecycle (kernel does not spawn Kimina);
`reqwest` + `rustls` + `webpki-roots`; permissive response decoder for
upstream Kimina / Lean-REPL field-name churn; *structural* re-check
via four `#eval` `PROBE` lines (foundational re-check via `lean-smt`
deferred to Phase 1); `FormalVerificationTrace` schema unchanged
(Task 2 wire format preserved); ADR-014 §9 SIGTERM-first deferral
rolls forward to Task 8 (Dapr sidecar lifecycle).

## Open notes for Task 8

- **Dapr orchestration topology.** Phase 0 services to bind into the
  workflow: (a) Python harness (ingest + translate stages); (b) Rust
  kernel (deduce + solver); (c) Lean re-check via Kimina (operator-
  managed daemon, *not* a sidecar). Pub/sub vs. service-invocation
  for the Rust↔Python boundary is the first decision — pub/sub fits
  the streaming-telemetry model; service invocation fits the
  one-payload-one-trace model. Web-search `"State of the art Dapr
  workflow polyglot 2026"` per Plan §10 #4 before pinning.
- **Per-stage trace plumbing.** Each stage emits a `tracing` span +
  a Dapr workflow event. The final aggregated `FormalVerificationTrace`
  + `LeanRecheck` envelope rides on the workflow output. Decide:
  in-band JSON envelope vs. Dapr state-store handle?
- **Kimina sidecar = operator-managed daemon, not a Dapr sidecar.**
  Per ADR-015 the kernel does not spawn Kimina. Task 8 may add a
  `just kimina-up` recipe (background `python -m server`) so a fresh
  developer can run the full pipeline without external setup; the
  recipe must `kill_on_drop` the process group on `just kimina-down`.
- **ADR-014 §9 / ADR-015 §8 SIGTERM-first deferral comes due here.**
  Task 8 is the place to either (a) add `nix` for safe `SIGTERM`
  delivery to kernel-spawned solver children and amend ADR-014 to
  enable the two-stage escalation, or (b) accept Phase 0 SIGKILL-only
  and amend ADR-014 to make that the permanent Phase 0+ stance.
- **`cds-ingest` / `cds-translate` console scripts** would simplify
  Dapr build-time wiring (sidecars typically launch one binary
  per service). Wire `[project.scripts]` when convenient.
- **`tool.uv.dev-dependencies` deprecation warning** still surfaces
  on every `uv run`. Migrate to `dependency-groups.dev` while
  scaffolding the Dapr Compose/manifest files.
- **PHASE marker in `lib.rs` is still `0`.** ADR-013 noted it bumps
  to `1` "when the SMT layer lands" — Task 6 landed it but the
  marker stayed at `0` per Memory_Scratchpad's Task 6 close-out.
  Decide what `PHASE = 1` means in Task 8 (probably: end-to-end
  pipeline runs under Dapr).

## Session 2026-04-30 — Task 6 close-out

Shipped the Rust solver layer under `crates/kernel/src/solver/`. Public
entrypoint `cds_kernel::solver::verify(matrix, opts) ->
FormalVerificationTrace` drives the warden + Z3 + cvc5 pipeline:
Z3 returns `sat | unsat | unknown` plus the unsat-core label list;
on `unsat`, cvc5 re-checks and emits an Alethe proof; the unsat-core
labels are projected through `LabelledAssertion::provenance` into
`atom:<doc>:<start>-<end>` source-spans (constraint **C4**).

**Module layout (`crates/kernel/src/solver/`):**

| File         | Role                                                                                          |
| ------------ | --------------------------------------------------------------------------------------------- |
| `warden.rs`  | tokio `Command::kill_on_drop(true)` + wall-clock `tokio::time::timeout`. ADR-004 honoured.    |
| `script.rs`  | `SmtConstraintMatrix` → SMT-LIBv2 with named assertions. `RenderMode::{UnsatCore, Proof}`.    |
| `z3.rs`      | `z3 -smt2 -in` driver. Parses `sat`/`unsat`/`unknown` + `(label …)` core list.                |
| `cvc5.rs`    | `cvc5 --lang=smt2 --dump-proofs --proof-format-mode=alethe …` driver; captures Alethe text.   |
| `mod.rs`     | `verify`, `VerifyOptions`, `SolverError`, `project_muc` helper.                               |

**Tests (Rust workspace, all green):**

| Suite                                  | Count | Coverage                                                                                |
| -------------------------------------- | ----- | --------------------------------------------------------------------------------------- |
| Existing schema + canonical + deduce   | 38    | (unchanged from Task 5).                                                                |
| `solver::script` unit                  | 3     | UnsatCore mode adds option + `get-unsat-core`; Proof mode bare; disabled assertions skipped. |
| `solver::warden` unit                  | 3     | `/bin/cat` echo; `/bin/sleep` timeout → `WardenError::Timeout`; missing binary → `Spawn`.|
| `solver::z3` unit                      | 6     | sat / unsat+core / unknown / `(error …)` / whitespace tolerant label list / empty list. |
| `solver::cvc5` unit                    | 4     | unsat+Alethe; sat-no-proof; `(error …)`; leading blank lines.                            |
| `solver::*` (top-level) unit           | 4     | `project_muc`: provenance lift, fallback to label, unknown label passthrough, sort+dedup.|
| `tests/solver_smoke.rs` integration    | 4     | **Gate:** consistent → sat-empty-MUC; contradictory → unsat + 2 source-span MUC + Alethe with `(assume clause_*` references; missing-provenance fallback; missing-binary → Warden::Spawn. |
| Existing `tests/deduce_smoke.rs`       | 5     | (unchanged from Task 5).                                                                |
| Existing `tests/golden_roundtrip.rs`   | 5     | (unchanged from Task 2).                                                                |

Final gate (all green):
- `cargo test --workspace` → **72 pass** (58 unit + 5 deduce_smoke + 5 golden_roundtrip + 4 solver_smoke).
- `cargo clippy --workspace --all-targets -- -D warnings` → clean.
- `cargo fmt --all -- --check` → clean.
- `uv run pytest` → 71 pass (no Python regressions).
- `uv run ruff check .` → clean.
- `just rs-solver` (new recipe) → 4/4 pass with `--nocapture`.

**Dependencies added:** none (`tokio` and `thiserror` already in the
kernel deps; warden uses only `tokio::process` + `tokio::time::timeout`).

**Materialized artifact:** `proofs/contradictory-bound.alethe.proof`
captures the cvc5 Alethe S-expression for the canonical Phase 0
contradiction so the gate's "Contradictory guideline → MUC → Alethe
`.proof` artifact" is reproducible by `git diff` against future runs.
`proofs/README.md` documents the regeneration command.

**Decisions captured in ADR-014** — the Phase 0 SMT/cvc5 contract:
Z3 owns the unsat-core path, cvc5 owns the Alethe proof; both are
spawned via the warden with `kill_on_drop(true)` + a wall-clock
timeout; cvc5 flags pinned per the cvc5 1.3 documentation
(`--simplification=none --dag-thresh=0
--proof-granularity=theory-rewrite`); SIGTERM-first escalation
deferred to Task 7 (Lean / Kimina) where shutdown grace materially
differs.

## Open notes for Task 7

- Lean 4 / Kimina headless server should consume the
  `FormalVerificationTrace.alethe_proof` payload that lands in
  `crates/kernel/src/solver/mod.rs::verify`. The string is a verbatim
  cvc5 Alethe S-expression. Carcara is the canonical 2026 re-checker
  for Alethe proofs but is *not* the Lean target — Kimina's JSON-RPC
  is. Confirm Kimina's payload schema before pinning the bridge.
- The warden is solver-agnostic. Lean (Kimina) reuses
  `solver::warden::run_with_input` directly. Task 7 should land a
  thin `cds_kernel::lean::run` driver next to `solver::z3` /
  `solver::cvc5` and *not* duplicate spawn / timeout plumbing.
- ADR-014 deferred SIGTERM-first escalation. Task 7 is when this
  comes due — Lean / Kimina is long-running and benefits from a
  graceful-shutdown grace window. Either add `nix` for safe
  `kill(SIGTERM)` delivery or accept SIGKILL-only and amend ADR-014.
- Discovery convention: `.bin/lean` lands via `just fetch-lean`
  (already wired); the `Justfile` PATH-prefixes `.bin/`. Default
  `VerifyOptions::lean_path = PathBuf::from("lean")` will then
  resolve correctly under `just`.
- The Phase 0 marker (`PHASE = 0`) in `lib.rs` is unchanged. ADR-013
  pre-noted that it bumps to 1 "when the SMT layer lands" — Task 6
  has landed it but the marker is still read by tests as a phase
  boundary, not an SMT-readiness gate. Leave as-is until Task 8/9
  decides what `PHASE = 1` means.

## Session 2026-04-30 — Task 5 close-out

Shipped the in-process Phase 0 deductive evaluator under
`crates/kernel/src/deduce/`. Public entrypoint
`cds_kernel::deduce::evaluate(payload, &Phase0Thresholds) -> Verdict`
streams a `ClinicalTelemetryPayload` through (a) a 2n×2n DBM-encoded
Octagon abstract domain over the canonical-vital namespace and (b) an
`ascent` Datalog program that promotes pre-discriminated threshold
breaches into named clinical conditions and roll-up alarms.

**Module layout (`crates/kernel/src/`):**

| File                 | Role                                                                                       |
| -------------------- | ------------------------------------------------------------------------------------------ |
| `canonical.rs`       | Rust mirror of `cds_harness.ingest.canonical.CANONICAL_VITALS`; lex-sorted; index helpers. |
| `deduce/mod.rs`      | `evaluate` + `Verdict` + `BreachSummary` + `DeduceError`; evaluator wires Octagon ↔ ascent.|
| `deduce/octagon.rs`  | `Octagon` (DBM, single-variable bounds Phase 0), `VitalInterval`, `DomainError`, join/meet.|
| `deduce/datalog.rs`  | `ascent::ascent! { ... }` → `ClinicalDeductionProgram`; 11 input + 11 derived relations.   |
| `deduce/rules.rs`    | `Phase0Thresholds` + `ThresholdBand`; clinically-illustrative defaults; `band(name)` LUT.  |

**Tests (Rust workspace, all green):**

| Suite                                | Count | Coverage                                                                                |
| ------------------------------------ | ----- | --------------------------------------------------------------------------------------- |
| Existing Task 2 schema unit tests    | 9     | Schema round-trip + variant-discriminator pin (unchanged).                              |
| Kernel + canonical unit tests        | 6     | `KERNEL_ID`, phase marker, canonical lex order + membership + index.                    |
| `octagon` unit tests                 | 9     | `top`, point/interval observe, sequential meet, join hull, top-absorption, errors, snapshot ordering, JSON. |
| `datalog` unit tests                 | 5     | Empty run, single breach → named condition, co-occurrence → compound_alarm, marker-distinct breaches do **not** co-fire, idempotent re-run. |
| `rules` unit tests                   | 4     | Strict breach predicate, default coverage, unknown-vital lookup, JSON round-trip.       |
| `deduce` evaluator unit tests        | 3     | Empty payload, non-canonical vital rejection, NaN rejection.                            |
| `tests/deduce_smoke.rs` integration  | 5     | **Gate:** hull tightness on benign stream; compound_alarm on tachy+desaturation; cross-marker co-fire negative; hypotension+tachy compound_alarm; golden payload evaluates cleanly. |
| `tests/golden_roundtrip.rs`          | 5     | Cross-language wire-format pin (unchanged).                                             |

Final gate (all green):
- `cargo test --workspace` → **48 pass** (38 unit + 5 deduce_smoke + 5 golden_roundtrip).
- `cargo clippy --workspace --all-targets -- -D warnings` → clean (deny `clippy::all`, warn `pedantic`).
- `cargo fmt --all -- --check` → clean.
- `uv run pytest` → 71 pass (no Python regressions).
- `uv run ruff check .` → clean.
- `just rs-deduce` (new recipe) → 5/5 pass with `--nocapture`.

**Dependencies added:**
- `ascent = { version = "0.8", default-features = false }` (workspace +
  kernel crate). Default features intentionally disabled to keep the
  kernel single-threaded for now (no `dashmap`/`rayon` pull-in); the
  evaluator is sync and `Send + Sync` by construction.

**Decisions captured in ADR-013** — the Nemo → `ascent` substitution
(Nemo has no Rust library crate; the CLI/Python bindings are the only
entry points and require subprocess hygiene that lands with the
warden in Task 6) plus Phase 0 octagon scope (single-variable bounds
only; relational `+x +y ≤ c` and Floyd-Warshall closure deferred).

## Open notes for Task 6

- SMT integration begins here. The existing `SmtConstraintMatrix`
  schema (Task 2) plus the Phase 0 emitter contract (ADR-012) are the
  inputs; cvc5's Alethe proofs and Z3's MUC enumeration via MARCO are
  the outputs. The Verdict struct has no MUC/Alethe fields yet —
  populate them or build a parallel `Formal_Verification_Trace`
  emitter that consumes both the `Verdict` and the SMT solver.
- **Subprocess warden lands here.** Per ADR-004 every Z3/cvc5 child
  must be owned by the warden, with `.kill_on_drop(true)` (tokio) and
  a hard wall-clock timeout. The Rust kernel introduces this; the
  Python harness's in-process `z3-solver` binding (Task 4) keeps
  parity by routing through a thin Rust IPC seam (revisit at the
  ADR-012 §6 boundary).
- The `.bin/z3` and `.bin/cvc5` binaries are staged by `just fetch-bins`
  but `.bin/` is currently empty on this dev box. Run `just fetch-bins`
  before exercising the solver path; the warden must locate binaries
  via `$PATH` (already PATH-prefixed by the Justfile recipe export).
- MUC ↔ source-span projection: the OnionL `Atom.source_span` and the
  `LabelledAssertion.provenance` (`atom:<doc>:<start>-<end>`) form a
  ready-made round-trip; Task 6 reads the MUC label set, intersects
  with `assumptions`, and projects via the provenance string. The
  shape of `FormalVerificationTrace` already captures the MUC list.
- Threshold rules in `deduce::rules::Phase0Thresholds` are *advisory* —
  the SMT layer is the authoritative source of arithmetic claims.
  Task 6 should NOT cross-import the threshold band into the SMT
  preamble; instead the `OnionLIRTree → SmtConstraintMatrix`
  pipeline (Task 4) carries the canonical encoding, and the
  deductive engine is a downstream consumer for alarms/triage.
- Web-search `"State of the art SMT proof emission Alethe LFSC 2026"`
  before pinning the cvc5 invocation flags (Plan §10 #4).

## Open notes carried forward

- **Translator boundaries (Task 4 contract).** Every guideline `*.txt`
  needs a sibling `*.recorded.json`; the `RecordedAdapter` is the only
  Phase 0 path. Switching to a live LLM is a `LiveAdapter`-class swap
  (and a separate ADR — keep ADR-012 narrowly scoped to the recorded
  contract).
- **OP_MAP is the SMT-lowering contract.** Adding a relation op is a
  coordinated edit across `OP_MAP`, the AST authors (Task 4 fixtures
  today, future LLM tomorrow), and downstream SMT verification (Task 6).
  The tripwire test `test_op_map_covers_phase0_operators` will surface
  any drift.
- **Source-span = byte offsets, not character offsets** (ADR-005, ADR-010).
  The translator's UTF-8 byte-length validation is the boundary check
  that protects Task 6's MUC reverse-projection.
- **Single-`Variable`-term atom elision** mirrors the Task 2 golden's
  `hba1c P` ⇒ `hba1c` pattern. Patient-scoped variables are descriptive,
  not parameters of the lowered SMT formula. Anything richer raises
  `UnsupportedNodeError` until Task 5/6 broadens the contract.
- **`CANONICAL_VITALS` is duplicated in two places now** (Python
  `cds_harness.ingest.canonical` + Rust `cds_kernel::canonical`).
  Add a tripwire to the Python `test_schema_roundtrip` (or a new
  `test_canonical_parity`) that diff-checks the slice when convenient
  — for now manual coordination per ADR-011 holds.

## Session 2026-04-29 — Task 4 close-out

Shipped a Python-only autoformalization translator that lifts local
guideline `*.txt` files into validated `OnionLIRTree` envelopes and lowers
each one to a Z3-checkable `SmtConstraintMatrix`. The LLM-touched
formalization stage is hidden behind `AutoformalAdapter`; the Phase 0
gate uses `RecordedAdapter` (deterministic fixtures), and `LiveAdapter`
is a placeholder that raises `NotImplementedError` for late-binding the
real client.

**Module layout (`python/cds_harness/translate/`):**

| File             | Role                                                                                        |
| ---------------- | ------------------------------------------------------------------------------------------- |
| `__init__.py`    | Public re-exports.                                                                          |
| `__main__.py`    | `python -m cds_harness.translate` shim.                                                     |
| `errors.py`      | `TranslateError` hierarchy (Missing / Invalid / UnsupportedNode / UnsupportedOp).           |
| `adapter.py`     | `AutoformalAdapter` Protocol + `RecordedAdapter` + `LiveAdapter` (stub).                    |
| `clover.py`      | `translate_guideline`, `translate_path`, `discover_translations`; source-span byte validator. |
| `smt_emitter.py` | `OP_MAP`, `emit_smt`, `serialize`, `smt_sanity_check` (Z3 binding).                          |
| `cli.py`         | argparse CLI with `--smt-check`, `--logic`, `--pretty`, `--output`.                          |

**Sample fixtures (`data/guidelines/`):**
- `hypoxemia-trigger.txt` (31 bytes) + `hypoxemia-trigger.recorded.json` → `sat`.
- `contradictory-bound.txt` (30 bytes) + `contradictory-bound.recorded.json` → `unsat`.
- `data/guidelines/README.md` documents adding new fixtures.

**Tests:** `python/tests/test_translate.py` — 34 cases covering adapter
lookup + error paths, source-span validation (doc_id, byte bounds, UTF-8),
discovery walk semantics, OP_MAP coverage tripwire, IndicatorConstraint
lowering, single-`Variable` term elision, literal handling, unknown-op
and richer-atom rejection, the **sat / unsat smoke gate** for both
fixtures, disabled-assumption drop, and CLI exit codes.

**Justfile wiring:** `py-translate` recipe (overridable `GUIDELINE_PATH`)
runs the full translator + SMT smoke check end-to-end.

**Dependency:** `z3-solver==4.16.0.0` added to `[project.dependencies]`
(ADR-001 pre-authorized the Z3/cvc5 Python bindings; the warden
subprocess wrapper still lands in Task 6 per ADR-004).

Final gate (all green):
- `uv run pytest` → **71 pass** (3 smoke + 9 schema + 25 ingest + 34 translate).
- `uv run ruff check .` → clean.
- `cargo test --workspace` → 18 pass (no Rust changes — sanity).
- `cargo clippy --workspace --all-targets -- -D warnings` → clean.
- `just py-translate` → 2 records, `hypoxemia-trigger=sat`, `contradictory-bound=unsat`.

Decisions captured in **ADR-012**.

## Open notes carried forward

- **Translator boundaries (Task 4 contract).** Every guideline `*.txt`
  needs a sibling `*.recorded.json`; the `RecordedAdapter` is the only
  Phase 0 path. Switching to a live LLM is a `LiveAdapter`-class swap
  (and a separate ADR — keep ADR-012 narrowly scoped to the recorded
  contract).
- **OP_MAP is the SMT-lowering contract.** Adding a relation op is a
  coordinated edit across `OP_MAP`, the AST authors (Task 4 fixtures
  today, future LLM tomorrow), and downstream SMT verification (Task 6).
  The tripwire test `test_op_map_covers_phase0_operators` will surface
  any drift.
- **Source-span = byte offsets, not character offsets** (ADR-005, ADR-010).
  The translator's UTF-8 byte-length validation is the boundary check
  that protects Task 6's MUC reverse-projection.
- **Single-`Variable`-term atom elision** mirrors the Task 2 golden's
  `hba1c P` ⇒ `hba1c` pattern. Patient-scoped variables are descriptive,
  not parameters of the lowered SMT formula. Anything richer raises
  `UnsupportedNodeError` until Task 5/6 broadens the contract.
- Source data format for ingestion: **CSV + sidecar JSON OR whole-envelope
  JSON.** Anything else is rejected. New canonical vital → coordinated edit
  of `CANONICAL_VITALS` + golden fixtures + downstream rules.
- Vitals dict ordering on the wire is **lexicographic** (matches Rust
  `BTreeMap`). Any new ingestion path MUST do the same.
- Wall-clock canonical form: `YYYY-MM-DDTHH:MM:SS.ffffffZ`.
- Duplicate `monotonic_ns` is a hard ingestion error.

## Open questions deferred

- HNN MUC heuristic — pretrained weights or train at provision time?
  Defer to Task 6.
- Kimina headless server packaging on Linux — official binary release vs
  build-from-source? Defer to Task 7; check `just fetch-bins` recipe shape
  closer to deadline.
- Dapr local-mode topology — single placement service per dev box?
  Defer to Task 8.
- `tool.uv.dev-dependencies` is deprecated in `pyproject.toml`; migrate to
  `dependency-groups.dev`. **Cosmetic only**, schedule as a tooling-cleanup
  task once Task 5+ stabilizes — non-blocking warning today.
- `schemars` JSON-Schema export for the SvelteKit frontend (Task 9). Not
  needed until then; revisit when wiring the BFF.
- `cds-ingest` / `cds-translate` console scripts (`[project.scripts]`) —
  currently invoked via `python -m cds_harness.<module>`. Add thin
  entrypoints when a packaged distribution is needed.
- Z3 access pattern. Task 4 uses the in-process `z3-solver` binding for
  the smoke check. Task 6 introduces the Rust subprocess warden + the
  `.bin/z3` binary; revisit at that boundary whether the Python harness
  also routes through the warden for parity.

## Hazards / known caveats

- **Wire format is load-bearing.** Any change to a schema field, the
  `kind` discriminator, OR the canonical-vital allowlist OR the
  `OP_MAP`/lowering contract MUST bump `SCHEMA_VERSION` in both Rust and
  Python and update goldens.
- **`CANONICAL_VITALS` is part of the boundary contract.** Adding a key
  is a coordinated edit across translator (Task 4 — `OP_MAP`/atom
  predicates), deductive engine (Task 5), and SMT integration (Task 6).
  Treat as ADR-grade.
- **Subprocess hygiene** is non-negotiable (ADR-004). Any new
  `Command::spawn` site MUST go through the warden and carry
  `.kill_on_drop(true)` + timeout. Task 4 sidesteps this with the
  in-process `z3-solver` Python binding; Task 5 sidesteps it with
  in-process `ascent` Datalog (ADR-013). Task 6 reinstates the
  discipline when external `.bin/z3` and `.bin/cvc5` children land.
- **C6 (JSON-over-TCP / MCP only)** — when adding any new IPC, double-check;
  gRPC / shared-mem / FFI across services are forbidden.
- **C5 (one atomic task per session)** — under no circumstance pre-emptively
  start the *next* task. Update memory + commit + terminate.

## Re-Entry Prompt (verbatim copy — see `Plan.md §9`)

> "Initialize session. Execute the Environment Verification Protocol, utilizing `sudo` if necessary. Ingest the persistent memory files located within the `.agent/` directory and evaluate the active plan checklist. Select STRICTLY the single next uncompleted atomic task from the plan. Execute exclusively that specific micro-task utilizing the defined 2026 stack and architectural constraints. Implement absolute resource cleanup and thread-safe operations. Update the `.agent/` memory files to reflect task progress. Flush all updates to disk, execute `git add .` and `git commit -m 'feat: complete [Task Name]'`, and formally terminate this session immediately to preserve the context window for the subsequent task."
