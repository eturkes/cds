# Architecture Decision Log

> One ADR per material decision. Append-only. Format: ADR-NNN, status, context, decision, consequences, alternatives.

---

## ADR-001 — Polyglot stack: Rust + Python + TypeScript + Lean 4

**Status:** Accepted (Phase 0 lock)
**Date:** 2026-04-29

**Context.** Pipeline domains are heterogeneous: high-performance deductive evaluation + OS-level subprocess management; symbolic / NLP / ontology tooling with first-class library coverage; interactive frontend; mechanically-checked proofs.

**Decision.**
- **Rust (Edition 2024)** for the deductive kernel: Nemo Datalog, Octagon abstract interpretation, subprocess warden orchestrating external SMT/Lean binaries.
- **Python 3.12+** as the multi-agent neurosymbolic harness: CLOVER autoformalization, AST translation, GraphRAG, owlapy/ELK, clingo, Z3/cvc5 official bindings.
- **TypeScript + SvelteKit** for the stakeholder visualizer.
- **Lean 4** for foundational proof checking via the Kimina headless JSON-RPC server.

**Consequences.** Multi-language toolchain complexity. Cross-language IPC is required (resolved by ADR-002). Justfile must unify build / lint / test (resolved by ADR-008). Each ecosystem locked to its native modern package manager (resolved by ADR-007).

**Alternatives rejected.**
- Pure Python: insufficient for guaranteed subprocess hygiene + Datalog perf.
- Pure Rust: ecosystem gaps in NLP, ontology, ASP bindings.
- JVM: heavyweight, slower iteration.

---

## ADR-002 — Inter-process communication: JSON-over-TCP/IP + MCP

**Status:** Accepted
**Date:** 2026-04-29

**Context.** Polyglot services + headless solver subprocesses require a stable, language-agnostic IPC.

**Decision.** All inter-process communication uses **JSON-over-TCP/IP** and the **Model Context Protocol (MCP)** exclusively. No proprietary RPC; no shared memory; no FFI for service boundaries (FFI permitted only inside a single language's process).

**Consequences.** Forces explicit, inspectable wire payloads — easy to tee/log/diff. Adds serialization cost; acceptable for Phase 0 (deductive verification dominates compute, not IPC). Aligns with hard constraint C6.

**Alternatives rejected.** gRPC (binary; harder to inspect); shared mmap (lifetime hazards across language runtimes); raw stdio framing (fragile).

---

## ADR-003 — Macro-architecture: Event-Driven Polyglot Microservices via Dapr

**Status:** Accepted
**Date:** 2026-04-29

**Context.** Phase 0 must remain modular enough to extend to Phase 1+ (FHIR streaming, cloud, ZKSMT) without rewrite. Need a sidecar pattern that is language-agnostic and decouples app code from infra.

**Decision.** Dapr Workflows with language-agnostic sidecars. Each microservice (Rust kernel, Python harness, frontend BFF) communicates via Dapr building blocks (pub/sub, state, workflow). Phase 0 runs Dapr in self-hosted mode; Phase 1 can swap to Kubernetes without app-code change.

**Consequences.** Adds Dapr runtime dependency. Sidecar pattern is well-understood and documented. Migration path to cloud is the natural Dapr K8s deployment. Workflow durability handled by Dapr, not bespoke code.

**Alternatives rejected.** Bespoke message bus (NIH); raw HTTP between services (loses workflow semantics); monolith (violates Phase 1+ scaling intent).

---

## ADR-004 — Subprocess defense-in-depth (`.kill_on_drop` + timeout warden)

**Status:** Accepted
**Date:** 2026-04-29

**Context.** Z3, cvc5, Lean 4 are long-lived child processes. Naive spawning leaks zombies on panic / OOM / crash. Past production CDSS deployments have hit fork-bomb pathologies under high error rates.

**Decision.** All external solver / theorem-prover subprocesses are owned by the Rust kernel's **subprocess warden**. Every spawned `Child`:

1. Wrapped with `.kill_on_drop(true)` on tokio handles (or `Drop` impl with explicit `kill()` for non-tokio).
2. Bounded by a hard wall-clock timeout monitor → `SIGTERM`, escalating to `SIGKILL` on expiry.
3. Confined to a dedicated async process pool. Workers communicate exclusively via message-passing channels — no shared mutable state, no UNIX-signal handlers in worker threads.

**Consequences.** Stronger guarantees against zombie processes and resource leaks. Slight added complexity (warden module). Worth it given clinical-software risk profile.

**Alternatives rejected.** Per-call `spawn` + best-effort `wait_with_timeout` (leaks on panic); shell wrapper scripts (timeout escapes, signal-handling pitfalls).

---

## ADR-005 — Autoformalization via CLOVER + NL2LOGIC, AST = OnionL

**Status:** Accepted
**Date:** 2026-04-29

**Context.** Need a faithful, traceable bridge from natural-language clinical guidelines to first-order logic that downstream symbolic engines can consume. Trace-back from MUC to source span is mandatory (constraint C4).

**Decision.** Pipeline: **CLOVER compositional framework + AST-Guided Parsing (NL2LOGIC)** → **OnionL** AST schema. OnionL nodes carry explicit `source_span` annotations to enable MUC ↔ textual contradiction mapping.

**Consequences.** Every atom is traceable. LLM hallucinations remain detectable downstream because every formal claim must round-trip through deterministic SMT. Schema versioning required (handled in Task 2).

**Alternatives rejected.** Direct LLM → SMT-LIB string (no source traceability, no AST integrity check); custom DSL (NIH; no academic grounding for clinical autoformalization).

---

## ADR-006 — SMT theory selection + proof certification chain

**Status:** Accepted
**Date:** 2026-04-29

**Context.** Multimorbidity guidelines require linear-arithmetic reasoning over continuous physiological scalars + boolean combinators + indicator constraints. Need machine-checkable proofs.

**Decision.**
- **Z3** is the primary SMT engine, run with **CDCL(T)** and **`check-sat-assuming`** for retractable assertions across guideline-overlap scenarios.
- **cvc5** delegated to deep-verification mode emitting **Alethe** + **LFSC** proof certificates.
- **MARCO** (augmented with HNN heuristics + CASHWMaxSAT stratification) extracts MUCs.
- **Lean 4** via **Kimina** headless server is the final foundational checker — re-validates Alethe certs against its kernel.

**Consequences.** Two-stage proof: SMT solver finds, ITP re-checks. Higher trust at the cost of extra compute (acceptable; pipeline is throughput-bounded only at SMT itself).

**Alternatives rejected.** Z3 alone (no foundationally-checked proof); CVC5 alone (Z3 has stronger CDCL(T) ergonomics for our workload); custom proof checker (NIH).

---

## ADR-007 — Hyper-modern toolchains: uv, bun, cargo, just

**Status:** Accepted
**Date:** 2026-04-29

**Context.** 2026 ecosystem standards for reproducible builds, fast iteration.

**Decision.**
- **Python:** `uv` for env + pkg mgmt, **exclusive**. `ruff` for lint + format, **exclusive** (replaces black, isort, flake8).
- **TS/JS:** `bun` for pkg + scripting, **exclusive**. `Vite` for frontend build, **exclusive**.
- **Rust:** `cargo` (Edition 2024).
- **Workspace orchestration:** `just` via root `Justfile`. **All cross-ecosystem build/lint/test/run flows route through `just`.**

**Consequences.** Lock-in to fast modern tools. Faster CI. Single discoverable entrypoint (`just --list`). For any tooling decision not specified here, mandatory web-search `"State of the art [tool type] 2026"` before deciding.

**Alternatives rejected.** Pip / poetry (slower, fragmented); npm / pnpm / yarn (slower than bun); Make (poor cross-OS, weaker UX than just).

---

## ADR-008 — Local-first provisioning under `.bin/`, prepended `$PATH`

**Status:** Accepted
**Date:** 2026-04-29

**Context.** External binaries (cvc5, Z3, Lean 4) must be reproducible across hosts. System-wide installs are versioned poorly and require sudo.

**Decision.** `Justfile` recipe `fetch-bins` autonomously downloads + verifies + extracts pre-compiled Linux binaries to `.bin/` at repo root. All Justfile recipes prepend `.bin/` to `$PATH`. `.bin/*` is gitignored (with a `.gitkeep` to preserve the directory).

**Consequences.** Reproducible per-checkout toolchain. No sudo required for solver/ITP install. Single source of pinned versions (in Justfile). Adds a one-time bootstrap step (`just bootstrap`).

**Alternatives rejected.** System packages (versions drift across distros); Nix (overkill for Phase 0; revisit in Phase 1+ for hermeticity).

---

## ADR-009 — Documentation bifurcation: `.agent/` (machine) vs `README.md` (human)

**Status:** Accepted
**Date:** 2026-04-29

**Context.** Two distinct audiences: (a) future LLM sessions consuming context-window-priced tokens; (b) human developers wanting prose & rationale.

**Decision.** Maintain two tracks:
- **`.agent/Plan.md`, `Architecture_Decision_Log.md`, `Memory_Scratchpad.md`** — token-optimized, dense, machine-first.
- **`README.md`** + future `docs/` — verbose, prose, human-first. Prose explains *why*; agent files state *what* and *which task is next*.

**Consequences.** Slight duplication of facts. Acceptable: divergent audiences justify divergent forms. `.agent/Plan.md` is authoritative for task scheduling; README is authoritative for narrative.

**Alternatives rejected.** Single doc set (either bloats agent context or starves humans of rationale).
