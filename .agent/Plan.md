# Plan.md — Neurosymbolic CDS, Phase 0 MVP

> **Audience:** future Claude sessions. Token-optimized. Authoritative source of truth for atomic-task scheduling.

---

## 1. Vision (compressed)

Backend pipeline. Input: unstructured clinical guidelines + continuous physiological telemetry. Output: mathematically-rigorous, machine-checkable safe care pathways. Phase 0 = headless engine + stakeholder visualizer (vertical slice). Phase 1+ deferred: FHIR streaming, distributed cloud, ZKSMT.

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

C1. Live ingestion uses genuine local datasets only (CSV/JSON in repo).
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

## 7. Subprocess defense-in-depth

- Rust subprocess warden owns every external solver/Lean child.
- `.kill_on_drop(true)` (tokio) or equivalent guard on every `Child`.
- Hard wall-clock timeout monitor → SIGTERM, then SIGKILL on expiry.
- Verification work isolated in async process pools. Worker comms = message-passing only. No UNIX-signal handlers in worker threads.

## 8. Atomic-task checklist

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
| 8.3b2 | Rust kernel pipeline Dapr smoke — daprd-driven cargo integration test for all three endpoints                 | pending  | Cargo integration test drives `/v1/deduce` + `/v1/solve` + `/v1/recheck` through daprd's `/v1.0/invoke/cds-kernel/method/v1/...` against canonical fixtures (`data/guidelines/contradictory-bound.recorded.json` for solve+recheck, telemetry payload for deduce); `AppState` wires env-driven `VerifyOptions` / `LeanOptions` overrides (`CDS_KIMINA_URL`, `CDS_Z3_PATH`, `CDS_CVC5_PATH`); `just rs-service-smoke` covers the new pipeline cases with the existing `--test-threads=1` discipline. |
| 8.4   | End-to-end Dapr Workflow — `ingest → translate → deduce → solve → recheck`                                    | pending  | End-to-end pipeline runs under Dapr against a canonical guideline; placement + scheduler up; per-stage tracing; flag round-trips.    |
| 9     | SvelteKit frontend — wire to live backend; render AST, Octagon, MUCs                                          | pending  | UI shows live trace from real dataset; verification flag round-trips.                                                                |

**At any session:** select STRICTLY the lowest-numbered uncompleted
task. No leapfrogging. Sub-tasks follow the same discipline —
`8.1 < 8.2 < 8.3a < 8.3b1 < 8.3b2 < 8.4 < 9`.

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
