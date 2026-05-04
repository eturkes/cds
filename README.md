# Neurosymbolic Clinical Decision Support System (CDS)

> A research-grade backend pipeline that ingests unstructured clinical guidelines and continuous physiological telemetry, **autoformalizes** them into mathematical constraints, and runs **deductive verification** to emit mathematically-rigorous, *safe* care pathways.

This repository hosted the **Phase 0 Vertical-Slice MVP** — a headless execution engine wired to a stakeholder-facing visualizer that renders the autoformalization, abstract-interpretation, and SMT-verification pipeline in real time. **Phase 0 closed at Task 9.3.** The repository is now in **Phase 1**, which extends the vertical slice with HL7 FHIR R5 streaming ingestion, distributed-cloud (Kubernetes) microservice deployment, and ZKSMT post-quantum proof attestation. See §7 for the live roadmap; `.agent/Architecture_Decision_Log.md` ADR-024 captures the Phase 1 axis split.

---

## 1. Epistemic Framing (Read This First)

This is a **research prototype**. To prevent over-claiming:

- *Deductive reasoning* is performed exclusively by the **Satisfiability Modulo Theories (SMT)** solvers (Z3, cvc5) and the **Lean 4** interactive theorem prover. These tools are sound w.r.t. their declared theories and proof systems.
- *Large Language Models* are used **strictly as syntactic translation agents**: natural-language guidelines → structured logic AST. Their output is verified by symbolic engines downstream; LLMs are never trusted for clinical reasoning.
- *Probabilistic and fuzzy components* (TSK fuzzy inference, HNN heuristics for MUC selection) are deterministic at evaluation time — they output crisp scalars consumable by SMT, never probability distributions left undecided.
- All algorithmic claims are bounded by what the underlying academic literature establishes for each specific tool. Nothing in this repo "diagnoses" or "decides" clinical care; it produces *machine-checkable proof certificates over formalized guideline fragments*.

---

## 2. Architectural Overview

The system is structured as an **Event-Driven Polyglot Microservices** pipeline coordinated via **Dapr Workflows** with language-agnostic sidecars.

```
                ┌─────────────────────────────────────────────────────┐
                │  SvelteKit / TypeScript stakeholder visualizer       │
                │  (live AST, Octagon bounds, MUC topology, proofs)   │
                └───────────────▲─────────────────────────────────────┘
                                │ JSON-over-TCP/IP, MCP
        ┌───────────────────────┴────────────────────────┐
        │              Dapr Workflow orchestrator          │
        └──┬─────────────┬─────────────────┬──────────────┘
           │             │                 │
   ┌───────▼──────┐ ┌────▼─────────┐ ┌─────▼────────────┐
   │ Rust kernel  │ │ Python harness│ │ Theorem subprocs │
   │ — Nemo       │ │ — Autoformal. │ │ — Z3, cvc5       │
   │   Datalog    │ │   (CLOVER /   │ │ — Lean 4 (Kimina │
   │ — Octagon    │ │   NL2LOGIC)   │ │   headless)      │
   │   abstract   │ │ — GraphRAG +  │ │                  │
   │   interp.    │ │   ELK / OWL2  │ │   .kill_on_drop  │
   │ — Subprocess │ │ — clingo ASP  │ │   isolated pools │
   │   warden     │ │ — Z3/cvc5 API │ │                  │
   └──────────────┘ └───────────────┘ └──────────────────┘
```

### Verification pipeline (data-flow)

1. **Semantic Autoformalization** — natural-language guideline → First-Order Logic AST via the **CLOVER** compositional framework and **AST-Guided Parsing** (NL2LOGIC). The AST conforms to the **OnionL** traceability schema (scopes, relations, indicator constraints, atomic propositions).
2. **Knowledge Retrieval & Alignment** — medical ontologies extracted via **GraphRAG**, reasoned over with **OWL 2 EL** description logics through **ELK** (consequence-based) and **owlapy**; intersecting ontologies aligned with the **HermiT** engine.
3. **Continuous Bounding & Fuzzy Inference** — physiological domains constrained with the **Octagon** abstract-interpretation domain ($\pm x \pm y \le c$); probabilistic medical thresholds collapsed to deterministic scalars via **Takagi-Sugeno-Kang (TSK)** fuzzy inference.
4. **Deterministic Rule Execution & Defeasible Logic** — real-time logical entailment in the **Nemo** main-memory Datalog engine; defeasible pathways via **Answer Set Programming** (clingo) with **ASPARTIX** argumentation; discrete implications encoded as **indicator constraints** to preserve linear relaxations.
5. **Mathematical Satisfiability & Bounded Model Checking** — AST → SMT-LIBv2 → **Z3** (CDCL(T), `check-sat-assuming`) over multimorbidity guideline composites.
6. **Unsatisfiable-Core Extraction** — Minimal Unsatisfiable Cores via the **MARCO** algorithm augmented with **Hypergraph Neural Network (HNN)** ranking heuristics and **CASHWMaxSAT** stratification.
7. **Formal Proof Certification** — deep verification delegated to **cvc5**, emitting **Alethe** and **LFSC** proof certificates; certificates routed to **Lean 4** via the **Kimina** headless JSON-RPC server for mechanical re-checking.

---

## 3. Conceptual Data Schemas

| Schema                        | Purpose                                                                                              |
| ----------------------------- | ---------------------------------------------------------------------------------------------------- |
| `ClinicalTelemetryPayload`    | Continuous floating-point physiological measurements + discrete patient events with temporal markers |
| `OnionL_IR_Tree`              | Hierarchical FOL AST with distinct node variants (Scope / Relation / IndicatorConstraint / Atom). JSON-serialized. |
| `SMT_Constraint_Matrix`       | SMT-LIBv2 string + linear-arithmetic theory namespaces + retractable `check-sat-assuming` assertions |
| `Formal_Verification_Trace`   | `{ sat: bool, muc: [textual_node_id], alethe_proof: <Lean4-ingestible serialization> }`              |

Concrete typed implementations land in **Task 2** (Rust structs + Python Pydantic models).

---

## 4. Stack

| Layer                          | Technology                                                            |
| ------------------------------ | --------------------------------------------------------------------- |
| Deductive kernel               | **Rust** (Edition 2024) — Nemo, Octagons, subprocess warden            |
| Neurosymbolic harness          | **Python 3.12+** — CLOVER/NL2LOGIC, GraphRAG, owlapy, clingo, Z3/cvc5 |
| Theorem proving                | **Lean 4** via **Kimina** headless JSON-RPC; **Z3**, **cvc5** as isolated binaries |
| Stakeholder visualizer         | **SvelteKit** + **TypeScript** + **Vite** + utility-first CSS         |
| Orchestration                  | **Dapr Workflows** (sidecar pattern), **MCP**, JSON-over-TCP/IP       |
| Package management             | `uv` (Python), `bun` (TS/JS), `cargo` (Rust)                           |
| Lint / format                  | `ruff` (Python), `clippy + rustfmt` (Rust), `eslint + prettier` (TS)  |
| Task runner                    | `just` (`Justfile` at repo root)                                      |

External binaries (cvc5, Z3, Lean 4 toolchain) are fetched into a project-local `.bin/` directory by `just fetch-bins`. `.bin/` is prepended to `$PATH` by the Justfile recipes.

---

## 5. Repository Layout

```
.
├── .agent/                  # Persistent agent memory (Plan, ADR, Scratchpad)
├── .bin/                    # Project-local prebuilt binaries (cvc5, z3, lean4)
├── crates/                  # Rust workspace
│   └── kernel/              # Deductive kernel (Nemo, Octagons, subprocess warden)
├── python/                  # Python neurosymbolic harness (uv-managed)
│   └── cds_harness/         # autoformalize / ontology / fuzzy / smt clients
├── frontend/                # SvelteKit stakeholder visualizer
├── tests/                   # Cross-cutting integration tests
├── data/                    # Local clinical datasets (CSV/JSON)
├── proofs/                  # Generated Alethe / LFSC certificates
├── Cargo.toml               # Rust workspace manifest
├── pyproject.toml           # Python project (uv + ruff)
├── Justfile                 # Unified cross-ecosystem task runner
├── LICENSE                  # Apache 2.0 with LLVM exceptions
├── README.md                # This file
└── .gitignore
```

---

## 6. Quickstart

```bash
# Verify host toolchain (uv, cargo, bun, just) and PATH wiring
just env-verify

# Phase 0 bootstrap: install local Python venv, fetch external binaries to .bin/
just bootstrap

# Lint everything
just lint

# Run all tests
just test
```

`just --list` enumerates every available recipe.

### Running Phase 0 end-to-end

The full vertical slice (telemetry → autoformalization → deduction → SMT
solve → Lean recheck → live UI) needs both daprd sidecars, the SvelteKit
adapter-node BFF, and a Kimina headless Lean server. Two close-out
gates exercise the stack:

```bash
# Wire-contract gate (Task 9.2): drives the canonical contradictory-bound
# fixture through the BFF via curl and asserts trace.sat == false +
# recheck.ok == true.
CDS_KIMINA_URL=http://127.0.0.1:8000 just frontend-bff-smoke

# Visualizer gate (Task 9.3): drives the same flow through the live UI
# and asserts the unsat banner + ≥2 MUC entries + AST highlights via
# Playwright.
CDS_KIMINA_URL=http://127.0.0.1:8000 just frontend-pipeline-smoke
```

For interactive exploration, bring up the cluster + sidecars + BFF and
load `http://127.0.0.1:5173/`:

```bash
just dapr-cluster-up
just py-service-dapr   # cds-harness sidecar
just rs-service-dapr   # cds-kernel sidecar
just frontend-dev      # SvelteKit + Vite dev server on :5173
```

The page renders the OnionL IR tree (left), the Octagon abstract domain
(right), the verification trace banner (top), and the MUC viewer
(bottom); MUC entries cross-link back into the AST tree on click.

---

## 7. Roadmap

### 7.1 Phase 0 (Closed)

| Task | Title                                                            | Status |
| ---- | ---------------------------------------------------------------- | ------ |
| 1    | Foundational scaffolding & environment provisioning              | **DONE** |
| 2    | Core conceptual schemas (Rust structs + Pydantic models)         | **DONE** |
| 3    | Live genuine data ingestion pipeline (CSV/JSON → harness)        | **DONE** |
| 4    | Python neurosymbolic translators (CLOVER → SMT-LIB)              | **DONE** |
| 5    | Rust deductive engine (Nemo + Octagon state vectors)             | **DONE** |
| 6    | Mathematical solver integration (Z3/cvc5, MUC, Alethe)           | **DONE** |
| 7    | Headless Lean 4 interop (Kimina JSON-RPC)                        | **DONE** |
| 8    | Dapr workflow orchestration (sidecar boundaries)                 | **DONE** (8.1–8.4b) |
| 9    | SvelteKit frontend wired to live backend                         | **DONE** (9.1–9.3) |

**Phase 0 closed at Task 9.3.** The stakeholder visualizer round-trips
the canonical `contradictory-bound` flow against a live Dapr cluster,
demonstrating the Plan §1 success criterion.

### 7.2 Phase 1 (Open)

Phase 1 extends the Phase 0 vertical slice across three architecturally-
independent axes per ADR-024. Per-axis tool selections are **not**
pre-locked here; each axis lands its own architectural-lock ADR
(ADR-025 / 026 / 027) at its first sub-task, bound by the
`.agent/Plan.md` §10 step 4 web-search discipline at decision time.

| Task | Title                                                                                                                                  | Status |
| ---- | -------------------------------------------------------------------------------------------------------------------------------------- | ------ |
| 10.1 | FHIR foundation — FHIR R5 server bootstrap + canonical `Observation` fixtures + Python / Rust client lib selection (ADR-025)            | **DONE** |
| 10.2 | FHIR Subscriptions streaming → harness ingest                                                                                           | **PLANNED** |
| 10.3 | FHIRcast collaborative-session events via Dapr pub/sub                                                                                  | **PLANNED** |
| 10.4 | FHIR streaming axis close-out — end-to-end `contradictory-bound` smoke                                                                  | **PLANNED** |
| 11.1 | Cloud foundation — Kubernetes manifests + `kind` cluster bootstrap + Dapr helm chart pin (ADR-026)                                       | **PLANNED** |
| 11.2 | Phase 0 services → Kubernetes deployment                                                                                                | **PLANNED** |
| 11.3 | Cloud observability — OpenTelemetry + Prometheus + Grafana + Dapr metrics scrape                                                         | **PLANNED** |
| 11.4 | Cloud axis close-out — cloud-deployed `contradictory-bound` smoke against `kind`                                                         | **PLANNED** |
| 12.1 | ZK toolchain selection — Risc0 / SP1 / Halo2 / PLONK 2026 SOTA web-search + `zk_kernel/` crate stub (ADR-032)                            | **DONE**    |
| 12.2 | ZKSMT witness gen — fixed-size SMT-trace serialization + witness extraction (ADR-033)                                                    | **DONE**    |
| 12.3a | ZKSMT prove + verify install plumbing + guest crate scaffold — sha-pinned cargo-risczero v3.0.1 + `crates/zk_kernel/guest/` skeleton + workspace exclusion (ADR-034) | **DONE**    |
| 12.3b1 | ZKSMT prove + verify body fills — `risc0-zkvm` workspace + host + guest deps + guest body + `prove`/`verify` body + cargo-risczero pin bumped 3.0.1 → 3.0.5 (ADR-035) | **DONE**    |
| 12.3b2 | ZKSMT prove + verify canonical round-trip — `zk-prove-smoke` recipe + `tests/canonical_roundtrip.rs` driving `extract → prove → verify` on the canonical `contradictory-bound` fixture (ADR-035) | **PLANNED** |
| 12.4 | ZKSMT pipeline integration + Phase 1 close-out — `zk_attestation` field + PHASE 1 → 2                                                     | **PLANNED** |

Each task is executed in its **own atomic session** under the *Context-Governed Re-Entry Protocol* documented in `.agent/Plan.md`.

---

## 8. Subprocess Defenses

External SMT solvers and Lean 4 instances are dangerous in long-lived processes if not carefully managed. The Rust kernel guarantees:

- **Drop-on-kill semantics** — every spawned `Child` process is wrapped with `.kill_on_drop(true)` (or equivalent for non-tokio handles), so a panic, abort, or scope exit guarantees solver termination.
- **Strict timeout monitors** — each solver call carries a hard wall-clock budget; expiry triggers `SIGTERM` then `SIGKILL`.
- **Thread-safe CPU isolation** — verification work runs in dedicated async process pools. Workers communicate exclusively via message-passing (no shared mutable state, no UNIX-signal handlers in worker threads).

---

## 9. Contributing

Phase 0 is a closed research prototype. Once Phase 1+ scope opens (FHIR streaming, distributed deployment, ZKSMT attestation), a `CONTRIBUTING.md` will be added with the public contribution policy.

---

## 10. License

Apache License 2.0 with LLVM Exceptions. See [`LICENSE`](./LICENSE).
