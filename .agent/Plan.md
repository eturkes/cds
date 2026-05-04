# Plan.md — Neurosymbolic CDS, Phase 0 MVP

> **Audience:** future Claude sessions. Token-optimized. Authoritative source of truth for atomic-task scheduling.

---

## 1. Vision (compressed)

Backend pipeline. Input: unstructured clinical guidelines + continuous physiological telemetry. Output: mathematically-rigorous, machine-checkable safe care pathways. **Phase 0 closed at Task 9.3** — headless engine + stakeholder visualizer round-tripping the canonical `contradictory-bound` fixture against a live Dapr cluster. **Phase 1 open at Task 10.1** — FHIR R5 streaming ingestion + distributed-cloud (Kubernetes) microservice deployment + ZKSMT post-quantum proof attestation, decomposed across three axis-aligned super-tasks 10 / 11 / 12 per ADR-024.

## 2. Epistemic constraints (binding)

- LLMs = **syntactic translators only**. Never trusted for clinical reasoning.
- Deductive reasoning = SMT (Z3, cvc5) + Lean 4 ITP only. Sound w.r.t. declared theories.
- Fuzzy / probabilistic stages emit **deterministic crisp scalars** before SMT.
- All claims bounded by published academic literature for each tool.
- Research prototype. Does not diagnose / decide care; produces proof certificates over formalized guideline fragments.

## 3. Pipeline (7 stages, ordered)

1. **Semantic Autoformalization** — NL guideline → FOL AST. Tools: CLOVER compositional framework, AST-Guided Parsing (NL2LOGIC). AST shape: OnionL (Scope / Relation / IndicatorConstraint / Atom).
2. **Knowledge Retrieval & Alignment** — GraphRAG; OWL 2 EL via ELK consequence engine + owlapy; HermiT for ontology alignment.
3. **Continuous Bounding & Fuzzy Inference** — Octagons abstract domain (`±x ±y ≤ c`); TSK fuzzy inference → crisp scalars.
4. **Deterministic Rule Execution & Defeasible Logic** — Nemo Datalog (main-memory); ASP via clingo; ASPARTIX argumentation; indicator constraints to preserve LP relaxations.
5. **SMT & Bounded Model Checking** — SMT-LIBv2 → Z3 (CDCL(T), `check-sat-assuming`).
6. **Unsat-Core Extraction** — MARCO algorithm + HNN heuristics + CASHWMaxSAT stratification → Minimal Unsatisfiable Cores (MUCs).
7. **Formal Proof Certification** — cvc5 emits Alethe / LFSC certs → Lean 4 (Kimina headless server) for mechanical re-check.

## 4. Conceptual schemas (target: Task 2)

| Name                          | Shape                                                                                                              |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| `ClinicalTelemetryPayload`    | Continuous floats (vitals) + discrete events; precise temporal markers (UTC ISO-8601 + monotonic ns).              |
| `OnionL_IR_Tree`              | Recursive ADT. Variants: `Scope { id, kind, children }`, `Relation { op, args }`, `IndicatorConstraint { guard, body }`, `Atom { predicate, terms, source_span }`. JSON-serialized. |
| `SMT_Constraint_Matrix`       | `{ logic_string: SMT-LIBv2, theories: [LIA, LRA, ...], assumptions: [LabelledAssertion] }`. Supports `check-sat-assuming` retraction. |
| `Formal_Verification_Trace`   | `{ sat: bool, muc: [textual_node_id], alethe_proof: <Lean4-ingestible serialization> }`. MUC entries trace back to `Atom.source_span` in OnionL tree. |

## 5. Hard constraints (NON-NEGOTIABLE)

C1. Live ingestion uses **genuine clinical data only** — Phase 0: local CSV/JSON in `data/`; Phase 1: FHIR R5 server connectivity (Task 10) plus the existing local CSV/JSON path retained for regression (ADR-024 §3).
C2. All unstructured text → OnionL JSON before any solver / deductive engine touches it.
C3. SMT solver evaluates the entire constraint matrix before yielding the validity flag.
C4. Every contradiction triggers topological mapping back to its offending textual node (MUC → `source_span`).
C5. **One atomic task per session.** No batching across sessions.
C6. All inter-process comms = JSON-over-TCP/IP and/or MCP.

## 6. Stack (locked)

| Layer                 | Tech                                                                |
| --------------------- | ------------------------------------------------------------------- |
| Deductive kernel      | Rust Edition 2024 (Nemo Datalog, Octagons, subprocess warden)        |
| Neurosymbolic harness | Python 3.12+ (CLOVER, GraphRAG, owlapy, clingo, Z3/cvc5 bindings)   |
| Theorem subprocesses  | Lean 4 via Kimina headless REST (POST /verify); Z3 + cvc5 binaries (.bin/) |
| Visualizer            | SvelteKit + TS + Vite + utility-first CSS                           |
| Orchestration         | Dapr Workflows, sidecar pattern, MCP, JSON-over-TCP                 |
| Pkg mgmt              | `uv` (Py), `bun` (TS), `cargo` (Rust)                                |
| Lint                  | `ruff`, `clippy + rustfmt`, `eslint + prettier`                     |
| Task runner           | `just` (`Justfile` at root)                                         |

**Phase 1 stack additions** (deferred to per-axis ADRs at first
sub-task; selection bound by Plan §10 step 4 web-search at decision
time, not pre-locked here):

| Phase 1 axis                                | Open candidates (search-pending)                                                        | Locked at        |
| ------------------------------------------- | --------------------------------------------------------------------------------------- | ---------------- |
| FHIR R5 streaming (Task 10)                 | FHIR R5 server impl (HAPI / Firely / Microsoft / etc.); Python client (`fhir.resources` etc.); Rust client (`fhirbolt` etc.); FHIR Subscriptions topic delivery; FHIRcast pub/sub | Task 10.1 ADR-025 |
| Distributed cloud microservices (Task 11)   | Kubernetes (`kind` local); Dapr helm chart pin; OpenTelemetry collector; Prometheus / Grafana                                                                          | Task 11.1 ADR-026 |
| ZKSMT post-quantum attestation (Task 12)    | ZK toolchain (Risc0 / SP1 / Halo2 / PLONK 2026 SOTA)                                                                                                                    | Task 12.1 ADR-027 |

## 7. Subprocess defense-in-depth

- Rust subprocess warden owns every external solver/Lean child.
- `.kill_on_drop(true)` (tokio) or equivalent guard on every `Child`.
- Hard wall-clock timeout monitor → SIGTERM, then SIGKILL on expiry.
- Verification work isolated in async process pools. Worker comms = message-passing only. No UNIX-signal handlers in worker threads.

## 8. Atomic-task checklist

### 8.1 Phase 0 (Closed)

> **Note.** Task 8 (originally a single line) was split into four atomic
> sub-sessions on 2026-04-30 because a monolithic Dapr-orchestration
> task repeatedly exhausted the context window. ADR-016 captures the
> rationale, the locked component selections, and the per-sub-task
> smoke gates. **Task 8.3 was further split into 8.3a + 8.3b on
> 2026-04-30** for the same reason: the Rust kernel service binds
> three distinct subprocess pipelines (`deduce`, `solve`, `recheck`)
> behind one axum app, and the foundation + endpoint plumbing each
> warrant their own session. ADR-018 captures the kernel-side
> foundation contract. **Task 8.3b was further split into 8.3b1 +
> 8.3b2 on 2026-05-01** because the original 8.3b scope (three
> handlers + their `IntoResponse` impls + comprehensive unit tests +
> `AppState` wiring + a Dapr-driven cargo integration test driving all
> three endpoints through daprd) again exceeded a single context
> window. ADR-019 captures the rationale and the per-sub-task gates.
> **Task 8.3b2 was further split into 8.3b2a + 8.3b2b on 2026-05-01**
> for the same reason: the original 8.3b2 scope bundled `AppState`
> introduction + env-driven `VerifyOptions` / `LeanOptions` resolution
> + handler refactor onto `axum::extract::State` + lifting shared
> smoke helpers into `tests/common.rs` + three daprd-driven cargo
> integration tests (one per pipeline) — and the
> external-dependency gate of the solve / recheck tests
> (`.bin/z3`, `.bin/cvc5`, `CDS_KIMINA_URL`) cleanly separates from
> the dependency-free `/v1/deduce` smoke + the foundation refactor.
> ADR-020 captures the rationale and the per-sub-task gates. **Task
> 8.4 was further split into 8.4a + 8.4b on 2026-05-01** for the same
> reason: the original 8.4 scope bundled placement+scheduler bring-up
> recipes + production SIGTERM-first warden escalation (deferred six
> times — ADR-014 §9 → ADR-015 §8 → ADR-016 §7 → ADR-018 §6 →
> ADR-019 §11 → ADR-020 §6) + readiness gate flip + a new Python
> `cds_harness.workflow` Dapr Workflow package + Dapr Python SDK
> introduction + aggregated cross-stage envelope + per-stage tracing
> + `just dapr-pipeline` recipe + end-to-end pytest smoke close-out
> — and the Rust-foundation vs. Python-composition boundary cleanly
> separates the cluster bring-up + warden refactor from the Workflow
> harness composition. ADR-021 captures the rationale and the
> per-sub-task gates. **Task 9 was further split into 9.1 + 9.2 + 9.3
> on 2026-05-01** for the same reason: the original Task 9 scope
> bundled first-time JS/TS toolchain introduction (SvelteKit 2 +
> Svelte 5 runes + Vite 7 + Tailwind 4 + ESLint 9 + Prettier 3 +
> Playwright + bun + Justfile recipes) + six TypeScript schema mirrors
> mirroring the Phase 0 Rust source-of-truth + a SvelteKit `+server.ts`
> BFF speaking JSON-over-TCP through daprd to `cds-harness` + `cds-kernel`
> + a canonical happy-path round-trip smoke against a live cluster +
> four Svelte 5 visualizer components (AST tree, Octagon abstract
> domain, MUC viewer, verification trace banner) + Playwright E2E
> + the Phase 0 → Phase 1 marker flip — and the natural three-axis
> boundary (toolchain-foundation / wire-contract+transport /
> visualizers+close-out) cleanly separates the green-field scaffold
> from the BFF contract from the UI close-out. ADR-022 captures the
> rationale, the locked toolchain, the visualizer-library policy
> (hand-rolled SVG, no D3 / Plotly / svelte-flow), the BFF transport
> policy (direct service-invocation, Workflow deferred), the
> schema-mirror policy (hand-written TS + parity tripwire, no
> `schemars` codegen), and the per-sub-task gates.

| #     | Task                                                                                                          | Status   | Session output gate                                                                                                                  |
| ----- | ------------------------------------------------------------------------------------------------------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| 1     | Foundational repo scaffolding + env provisioning + memory init                                                | **DONE** | git commit `chore: initial project scaffolding`                                                                                      |
| 2     | Core conceptual schemas — Rust structs + Pydantic v2 models for the 4 schemas                                 | **DONE** | git commit `feat: complete Core Conceptual Schemas`                                                                                  |
| 3     | Live genuine data ingestion — local CSV/JSON parser → Python harness                                          | **DONE** | git commit `feat: complete Live Genuine Data Ingestion`                                                                              |
| 4     | Python neurosymbolic translators — CLOVER text→AST→SMT-LIB                                                    | **DONE** | git commit `feat: complete Python neurosymbolic translators`                                                                         |
| 5     | Rust deductive engine — Nemo Datalog + Octagon state vectors                                                  | **DONE** | git commit `feat: complete Rust deductive engine`                                                                                    |
| 6     | Mathematical solver integration — Z3/cvc5, MUC extraction, Alethe proof emission                              | **DONE** | git commit `feat: complete Mathematical solver integration`                                                                          |
| 7     | Headless Lean 4 interop — Kimina REST bridge                                                                  | **DONE** | git commit `feat: complete Headless Lean 4 interop`                                                                                  |
| 8.1   | Dapr foundation — slim init + components + Configuration + Justfile recipes + smoke gate                      | **DONE** | git commit `feat: complete Task 8.1 Dapr foundation`                                                                                 |
| 8.2   | Python harness Dapr service — FastAPI app exposing `/v1/ingest` + `/v1/translate`                             | **DONE** | git commit `feat: complete Task 8.2 Python harness Dapr service`                                                                     |
| 8.3a  | Rust kernel service foundation — axum app skeleton + `/healthz` + `[[bin]]` + Justfile recipes                | **DONE** | git commit `feat: complete Task 8.3a Rust kernel service foundation`                                                                 |
| 8.3b1 | Rust kernel pipeline handlers — `/v1/deduce` + `/v1/solve` + `/v1/recheck` + `IntoResponse` lifts + unit tests | **DONE** | git commit `feat: complete Task 8.3b1 Rust kernel pipeline handlers`                                                                 |
| 8.3b2a | Rust kernel `AppState` + `/v1/deduce` Dapr smoke — env-driven option resolution + dependency-free pipeline smoke | **DONE** | git commit `feat: complete Task 8.3b2a Rust kernel AppState + deduce Dapr smoke`                                                     |
| 8.3b2b | Rust kernel `/v1/solve` + `/v1/recheck` Dapr smokes — gated on `.bin/z3`+`.bin/cvc5` and `CDS_KIMINA_URL`        | **DONE** | git commit `feat: complete Task 8.3b2b Rust kernel solve + recheck Dapr smokes`                                                     |
| 8.4a   | Dapr cluster bring-up + production SIGTERM-first warden — `placement-up` / `scheduler-up` recipes + warden two-stage shutdown + readiness gate flip | **DONE** | git commit `feat: complete Task 8.4a Dapr cluster bring-up + SIGTERM-first warden`                                                                  |
| 8.4b   | End-to-end Dapr Workflow — `cds_harness.workflow` package + Dapr Python SDK + aggregated envelope + `just dapr-pipeline` + end-to-end pytest smoke | **DONE** | git commit `feat: complete Task 8.4b End-to-end Dapr Workflow + Task 8 close-out`                                                    |
| 9.1    | Frontend foundation — SvelteKit 2 + Svelte 5 runes + Vite 7 + Tailwind 4 + ESLint 9 + Prettier 3 + Playwright tombstone + Justfile `frontend-*` recipes | **DONE** | git commit `feat: complete Task 9.1 Frontend foundation`                                                                              |
| 9.2    | TS schema mirrors + BFF + canonical smoke — six TS schemas + `+server.ts` routes + `frontend-bff-smoke` Justfile recipe + parity tripwire           | **DONE** | git commit `feat: complete Task 9.2 TS schema mirrors + BFF + canonical smoke`                                                       |
| 9.3    | Visualizers + Phase 0 close-out — AST tree + Octagon + MUC viewer + verification trace + Playwright E2E + PHASE 0 → 1 flip                          | **DONE** | git commit `feat: complete Task 9.3 Visualizers + Phase 0 close-out` — **Phase 0 closed**                                                  |

### 8.2 Phase 1 (Open)

> **Note.** Phase 1 opens with three axes — FHIR streaming, distributed
> cloud, and ZKSMT post-quantum attestation — drawn from Plan §1's
> deferred scope. Each axis is structurally larger than any single
> Phase 0 super-task; the same atomic-session discipline holds. Tasks
> 10 / 11 / 12 are the three super-tasks, each with sub-tasks
> 10.1–10.4 / 11.1–11.4 / 12.1–12.4 covering foundation → integration
> → close-out. Mid-flight sub-task splits (e.g., 10.1a / 10.1b) follow
> the Phase 0 precedent (ADR-016 / 018 / 019 / 020 / 021 / 022) — each
> split lands its own ADR. Per-axis architectural locks land at each
> axis's first sub-task: ADR-025 (FHIR R5 server impl + client libs),
> ADR-026 (Kubernetes / Dapr helm / observability), ADR-027 (ZK
> toolchain). The PHASE constants stay at 1 across all Phase 1 sub-
> tasks and flip 1 → 2 at Task 12.4 close-out (mirrors ADR-023 §7's
> "flip at last task of phase" discipline). ADR-024 captures the
> structural decision; the four "Alternatives rejected" entries
> (single-axis super-task, five-axis split, pre-locked tools, new C7)
> document the discarded options.

| #     | Task                                                                                                                                                            | Status       | Session output gate                                                                                       |
| ----- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------ | --------------------------------------------------------------------------------------------------------- |
| 10.1  | FHIR foundation — FHIR R5 server bootstrap + canonical `Observation` fixture set + Python / Rust client lib selection (ADR-025)                                  | **DONE**     | git commit `feat: complete Task 10.1 FHIR foundation`                                                     |
| 10.2  | FHIR Subscriptions streaming — topic-based subscription delivery → harness ingest path                                                                          | **DONE**     | git commit `feat: complete Task 10.2 FHIR Subscriptions streaming`                                        |
| 10.3  | FHIRcast collaborative-session events — patient-open / patient-close routed through Dapr pub/sub                                                                 | **DONE**     | git commit `feat: complete Task 10.3 FHIRcast pub/sub`                                                    |
| 10.4  | FHIR streaming axis close-out — end-to-end FHIR → canonical `contradictory-bound` smoke                                                                          | **DONE**     | git commit `feat: complete Task 10.4 FHIR streaming close-out` — **FHIR axis closed**                     |
| 11.1  | Cloud foundation — Kubernetes manifests + `kind` local cluster bootstrap + Dapr helm chart pin (ADR-028)                                                         | **DONE**     | git commit `feat: complete Task 11.1 Cloud foundation`                                                    |
| 11.2  | Cloud service deployment — Phase 0 services (cds-harness + cds-kernel + frontend BFF) → Kubernetes                                                               | **DONE**     | git commit `feat: complete Task 11.2 Cloud service deployment`                                            |
| 11.3  | Cloud observability — OpenTelemetry collector + Prometheus + Grafana + Dapr metrics scrape                                                                       | **TODO**     | git commit `feat: complete Task 11.3 Cloud observability`                                                 |
| 11.4  | Cloud axis close-out — cloud-deployed `contradictory-bound` smoke against `kind`                                                                                  | **TODO**     | git commit `feat: complete Task 11.4 Cloud close-out`                                                     |
| 12.1  | ZK toolchain selection — Risc0 / SP1 / Halo2 / PLONK 2026 SOTA web-search + `zk_kernel/` crate stub (ADR-027)                                                    | **TODO**     | git commit `feat: complete Task 12.1 ZK toolchain selection`                                              |
| 12.2  | ZKSMT witness gen — fixed-size SMT-trace serialization + witness extraction                                                                                      | **TODO**     | git commit `feat: complete Task 12.2 ZKSMT witness gen`                                                   |
| 12.3  | ZKSMT prove + verify — round-trip on canonical `contradictory-bound` fixture                                                                                      | **TODO**     | git commit `feat: complete Task 12.3 ZKSMT prove + verify`                                                |
| 12.4  | ZKSMT pipeline integration + Phase 1 close-out — `Formal_Verification_Trace.zk_attestation` field + PHASE 1 → 2 + full integration smoke + README Phase 1 → DONE | **TODO**     | git commit `feat: complete Task 12.4 ZKSMT close-out + Phase 1 closed` — **Phase 1 closed**               |

**At any session:** select STRICTLY the lowest-numbered uncompleted
task. No leapfrogging. Sub-tasks follow the same discipline —
`8.1 < 8.2 < 8.3a < 8.3b1 < 8.3b2a < 8.3b2b < 8.4a < 8.4b < 9.1 < 9.2 < 9.3 < 10.1 < 10.2 < 10.3 < 10.4 < 11.1 < 11.2 < 11.3 < 11.4 < 12.1 < 12.2 < 12.3 < 12.4`.

## 9. Context-Governed Re-Entry Prompt (verbatim)

> "Initialize session. Execute the Environment Verification Protocol, utilizing `sudo` if necessary. Ingest the persistent memory files located within the `.agent/` directory and evaluate the active plan checklist. Select STRICTLY the single next uncompleted atomic task from the plan. Execute exclusively that specific micro-task utilizing the defined 2026 stack and architectural constraints. Implement absolute resource cleanup and thread-safe operations. Update the `.agent/` memory files to reflect task progress. Flush all updates to disk, execute `git add .` and `git commit -m 'feat: complete [Task Name]'`, and formally terminate this session immediately to preserve the context window for the subsequent task."

## 10. Operating discipline for every session

1. **Verify env first.** `just env-verify`. If missing tooling: install locally (`.bin/`, `~/.cargo/bin`, `~/.bun/bin`, `~/.local/bin`). `sudo` only for OS pkgs.
2. **Read `.agent/`** in full before acting.
3. **Pick exactly one task** from §8, lowest uncompleted #.
4. **Mandatory temporal verification:** for any unspecified tooling decision, web-search `"State of the art [tool type] 2026"` before terminal exec.
5. **Strict modernity persistence:** on `command not found`, troubleshoot `$PATH`, hidden bin dirs, absolute paths — do not fall back to a stale toolchain.
6. **Subprocess hygiene:** every external solver/Lean process under `.kill_on_drop` + timeout.
7. **Update `.agent/`** (Plan checkbox flip + Scratchpad notes + ADR if a decision was made).
8. **Commit** `git add . && git commit -m "feat: complete <TaskName>"` (or `chore:` / `fix:` as fits Conventional Commits).
9. **Terminate immediately** to preserve context window.
