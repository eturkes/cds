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

---

## ADR-010 — Cross-language schema wire-format conventions

**Status:** Accepted
**Date:** 2026-04-29

**Context.** Task 2 lands the four conceptual schemas (`ClinicalTelemetryPayload`, `OnionLIRTree`, `SmtConstraintMatrix`, `FormalVerificationTrace`) in both Rust (`serde`) and Python (Pydantic v2). The wire format must be byte-stable across the language boundary — JSON serialized by either side must round-trip through the other.

**Decision.**

1. **Single source of truth for the wire format = the JSON shape** — not the Rust struct, not the Pydantic model. Authoritative fixtures live in `tests/golden/*.json` and are loaded by integration tests on **both** sides; any change requires updating both fixtures and both implementations together.
2. **Variant discriminator** for tagged unions = the `snake_case` string field `kind`. Serde uses `#[serde(tag = "kind", rename_all = "snake_case")]`; Pydantic uses `Annotated[A | B, Field(discriminator="kind")]` with `kind: Literal["..."]` defaulted on each variant.
3. **Schema version** is a string constant `SCHEMA_VERSION` exported from `cds_kernel::schema` and `cds_harness.schema`. Every top-level envelope (each of the four schemas) carries a `schema_version: str` field. The two constants MUST be equal in any commit; the cross-language test asserts equality.
4. **Map ordering.** Rust uses `BTreeMap<String, _>` for any keyed map (e.g. `vitals`); Pydantic dicts inherit insertion order. Ingestion pipelines must insert keys in lexicographic order to keep payloads byte-stable across both runtimes.
5. **Timestamps.** Wall-clock = RFC 3339 / ISO-8601 UTC string with explicit `Z` suffix. Monotonic = `u64` nanoseconds (Pydantic: `int = Field(ge=0)`).
6. **Source-span trace.** `Atom` MUST carry `SourceSpan { start: usize, end: usize, doc_id: str }`; absence is a validation error in both languages. This is the contract for constraint C4 (MUC → text projection).
7. **Models are frozen.** Pydantic models use `model_config = ConfigDict(frozen=True, extra="forbid")` so unknown JSON fields raise on validation rather than silently surviving a round trip.

**Consequences.** Two-language schema duplication is real but small (≈250 LOC each side) and held in lock-step by the golden fixtures. Adding a fifth schema or evolving an existing one is a coordinated edit across exactly two trees + the goldens. CI catches any drift on the next workspace test.

**Alternatives rejected.**
- Code-generation from a single IDL (Cap'n Proto, OpenAPI). Heavyweight for four schemas; constraints C6 (JSON-over-TCP/MCP) reduces the marginal value of a binary IDL.
- Adjacently-tagged or externally-tagged unions (`{"Atom": {...}}`). Less ergonomic for Pydantic v2 discriminator unions and noisier on the wire.
- Hashable map types with insertion-order assumption (HashMap on the Rust side). Risks non-deterministic JSON ordering between runs.

---

## ADR-011 — Phase 0 telemetry-ingestion contract

**Status:** Accepted
**Date:** 2026-04-29

**Context.** Task 3 lands the live-data ingestion path. Constraint C1 fixes the source as **local CSV/JSON in `data/`** (no HTTP fetch, no FHIR streaming in Phase 0). The ingestion stage is the first opportunity to enforce semantics that the schema deliberately leaves loose (vital-key namespace, timestamp shape, monotonic-marker uniqueness) — once data crosses the boundary into the deductive pipeline, every downstream stage assumes those guarantees.

**Decision.**

1. **Two recognised file shapes**, dispatched by extension:
   - `*.csv` row stream **plus** a mandatory sidecar `<stem>.meta.json` carrying `source` (and optional `events`). Each CSV produces one payload.
   - `*.json` whole-envelope payloads (already shaped like `ClinicalTelemetryPayload`). One file → one payload.

   Sidecar metadata files (`*.meta.json`) are skipped by the directory dispatcher and never returned as standalone payloads. Anything else is rejected.

2. **Canonical vital-key namespace** is a `frozenset` exported as `cds_harness.ingest.canonical.CANONICAL_VITALS`. Phase 0 set: `heart_rate_bpm`, `spo2_percent`, `systolic_mmhg`, `diastolic_mmhg`, `temp_celsius`, `respiratory_rate_bpm`. Any other vital column / dict key is a hard `UnknownVitalError`. Adding a key is a coordinated edit across this constant, the translator (Task 4), the Rust deductive engine (Task 5), and Z3/cvc5 wiring (Task 6); treat as ADR-grade.

3. **Wall-clock canonicalization.** All wall-clock strings must be RFC 3339 / ISO-8601 UTC ending in literal `Z`. The loader normalizes them to `YYYY-MM-DDTHH:MM:SS.ffffffZ` (zero-padded microseconds) so that two equivalent payloads diff byte-for-byte. Naive datetimes, non-UTC offsets, and otherwise-malformed strings raise `InvalidTimestampError`.

4. **Monotonic-marker uniqueness.** Two samples in the same payload sharing a `monotonic_ns` raise `DuplicateMonotonicError`. The schema does not enforce this; the boundary does.

5. **Vital ordering on the wire = lexicographic.** The CSV loader sorts vital column names before constructing each `TelemetrySample.vitals` dict to match the Rust `BTreeMap<String, f64>` serialization order. Any new ingestion path MUST preserve lexicographic insertion order.

6. **Event bucketing.** Sidecar `events` are bisect-bucketed into the latest sample whose `monotonic_ns` is `≤ event.at_monotonic_ns`. Events that predate the first sample attach to the first sample. The CSV happy path relies on this so the only event annotation lives on a single sample.

7. **Error hierarchy.** All ingestion errors derive from `IngestError(ValueError)`. The CLI exits `1` for any `IngestError`, `2` for missing-path, `0` on success.

8. **Discovery is a deterministic directory walk.** No manifest file. Iteration is sorted by path so that `discover_payloads()` results are stable across runs and OSes.

**Consequences.** Strict boundary keeps every downstream stage simple: the translator (Task 4) and deductive engine (Task 5) can treat `vitals` keys as a closed alphabet and `monotonic_ns` as a primary key. The cost is a small frozen allowlist that must move in lockstep with `SCHEMA_VERSION` whenever a new vital is added; that's caught by golden-fixture tests on both sides of the wire. The sidecar-metadata convention also keeps CSVs human-readable in `git diff` while still letting us carry structured event annotations.

**Alternatives rejected.**
- **Pydantic computed validators on the schema** for vital-key + monotonic-uniqueness checks. Tighter coupling but conflates wire-format decoding with policy; the schema would reject Rust-emitted payloads that happened to carry an off-namespace key, breaking forward extensibility.
- **Manifest file (`data/manifest.toml`)** to enumerate ingestible files. Adds a second source of truth that drifts; directory walk is simpler and Phase 0 ships only a handful of samples.
- **Auto-coerce unknown vitals into a `data` blob** on a `DiscreteEvent`. Hides namespace drift from authors and pollutes the event stream; we want the loud failure instead.
- **Permissive timestamp parsing** (e.g. dateutil). Pulls a heavyweight dep for a contract that is already strict on paper; stdlib `datetime.fromisoformat` (Python 3.11+) handles the canonical form natively.

---

## ADR-012 — Phase 0 autoformalization-translator contract

**Status:** Accepted
**Date:** 2026-04-29

**Context.** Task 4 lands the autoformalization translator: clinical
guideline natural-language text → `OnionLIRTree` → `SmtConstraintMatrix`
ready for Z3 (`check-sat`) and (from Task 6) for cvc5 + MARCO MUC
extraction. Constraint **C2** binds: all unstructured text **must** flow
through `OnionLIRTree` before any solver touches it. Constraint **C4**
binds: every contradiction must be projectable back to its offending
textual node. ADR-005 already commits the pipeline (CLOVER + NL2LOGIC),
the AST shape (OnionL), and the source-span trace; this ADR pins the
*Phase 0 implementation contract* — the boundary every later phase
inherits.

**Decision.**

1. **Adapter seam for the LLM-touched stage.** The translator package
   exposes an `AutoformalAdapter` Protocol (single method:
   `formalize(*, doc_id, text) -> OnionLNode`). Phase 0 ships
   `RecordedAdapter` (deterministic, fixture-driven, **the only adapter
   exercised by the gate**) and `LiveAdapter` (placeholder that raises
   `NotImplementedError`). Real LLM wiring is a future ADR — until then,
   no network calls run as part of `just py-translate`, `just ci`, or any
   test.

2. **Recorded fixtures are full `OnionLIRTree` envelopes.** Each guideline
   `<doc>.txt` lives next to a sibling `<doc>.recorded.json` whose top-level
   shape validates against the Task 2 schema. The adapter returns
   `tree.root`. This keeps the file independently inspectable and makes
   schema drift loud.

3. **Two recognised file shapes**, dispatched by extension. `*.txt` is the
   ingestible guideline; `*.recorded.json` is its sidecar; anything else
   under `data/guidelines/` (e.g. `README.md`) is silently skipped by the
   directory walker. Mirrors the ingestion convention of ADR-011.

4. **Source-span byte-offset validation at the boundary.** Every
   `Atom.source_span` carried by the recorded fixture must satisfy
   `0 <= start <= end <= len(text.encode("utf-8"))` and
   `span.doc_id == <file stem>`. Violations raise `InvalidGuidelineError`.
   This is the boundary check that protects MUC reverse-projection (C4)
   from drift between fixture authoring and source revisions.

5. **SMT lowering contract (Phase 0).**
   - The root `Scope`'s direct children are the *clause set*. Each
     becomes one `LabelledAssertion`. Label format: `clause_NNN`
     (zero-padded ord). `provenance` format:
     `atom:<doc_id>:<start>-<end>` taken from the first `Atom`
     reached by left-to-right walk. The pattern is verbatim from the
     Task 2 golden fixture so MUC labels round-trip to source spans
     mechanically.
   - `Relation.op` lowers through a fixed `OP_MAP`
     (`and`, `or`, `not`, `implies`, `equals`, `less_than`,
     `less_or_equal`, `greater_than`, `greater_or_equal`, `plus`,
     `minus`, `times`, `divide`). Unknown ops raise `UnsupportedOpError`.
     A tripwire test pins this set; widening it is a coordinated edit.
   - `IndicatorConstraint(guard, body)` lowers to `(=> guard body)`.
   - `Atom` lowering: `predicate == "literal"` with one `Constant` term
     emits the constant value verbatim (numeric literal). Otherwise the
     predicate is treated as a 0-ary `Real` symbol. A *single*
     `Variable` term is descriptive and elided (matches the Task 2
     golden's `hba1c P` ⇒ `hba1c` pattern). Anything richer raises
     `UnsupportedNodeError` until Tasks 5/6 widen the contract.
   - Default logic is `QF_LRA`; `THEORIES_BY_LOGIC` maps the small
     set of Phase 0 logics to their theory lists.

6. **SMT smoke gate via in-process Z3 binding.** The Phase 0 sanity gate
   (`smt_sanity_check`) parses the emitted SMT-LIBv2 script through
   `z3-solver`'s `parse_smt2_string` and runs `Solver.check()`. This
   intentionally side-steps the Rust subprocess warden (ADR-004) — that
   warden lands with the binary cvc5 + Z3 wiring in Task 6, which is also
   when MUC extraction begins to need a real subprocess. Until then, the
   in-process binding is sufficient and avoids an out-of-order Task 5/6
   dependency on `.bin/z3`.

7. **Error hierarchy.** All translator errors derive from `TranslateError
   (ValueError)`: `MissingFixtureError`, `InvalidGuidelineError`,
   `UnsupportedNodeError`, `UnsupportedOpError`. CLI exits `1` for any
   `TranslateError`, `2` for missing path, `0` on success. Mirrors the
   ingestion exit-code semantics from ADR-011 so wrapper scripts can
   handle both uniformly.

8. **Discovery is a deterministic, sorted directory walk.** No manifest
   file. Mirrors ADR-011 #8. Iteration order is `sorted(path.iterdir())`
   so output is reproducible across runs and OSes.

**Consequences.** A complete deterministic Phase 0 translator: no LLM in
the gate, no network, byte-stable on the wire, MUC labels already
threaded back to source spans. The `LiveAdapter` placeholder makes the
seam for the LLM client obvious without committing to a specific SDK
today; the next ADR can pick the client (likely `anthropic`) and pin
prompt-cache strategy. The `OP_MAP` and atom-lowering rules form a small
contract that the AST-authoring side (whether human-recorded or
LLM-emitted) must respect — tripwire tests and explicit
`UnsupportedNodeError` paths keep drift loud rather than silent.

**Alternatives rejected.**
- **Live LLM call in the Task 4 gate.** Pulls a network dependency into
  `just ci`, which violates determinism and makes CI flaky. The
  `RecordedAdapter`/`LiveAdapter` split keeps both possible without
  forcing the trade-off now.
- **Rust subprocess warden routing for the Phase 0 SMT smoke.** Couples
  Task 4 to Task 5/6 binary plumbing without buying anything for the
  smoke check (an in-process `(check-sat)` returns sat/unsat exactly the
  same as the binary). Task 6 reinstates the warden discipline at the
  point where MUC extraction and proof emission make the binary mode
  necessary.
- **Storing recorded fixtures as bare `OnionLNode` JSON** (without the
  `OnionLIRTree` envelope). Loses the schema-version round-trip and
  makes drift between Rust + Python schemas harder to detect at fixture
  load time.
- **Character-offset source spans.** ADR-005 / ADR-010 pin byte offsets;
  byte semantics survive any future ingestion of multi-byte clinical
  glyphs (e.g. `°C`, `µ`, `≥`) without an additional encoding hop.
- **Per-atom `LabelledAssertion`s** (one per Atom rather than per
  top-level clause). Bloats the matrix without buying MUC granularity
  beyond what the source-span trace already provides. Phase 0 stays at
  one assertion per clause; if the MUC-extraction quality in Task 6
  needs finer granularity, that is a separate ADR.

---

## ADR-013 — Phase 0 deductive-engine substitution: Nemo → `ascent`

**Status:** Accepted (Phase 0 narrow-scope substitution)
**Date:** 2026-04-30

**Context.** Task 5 lands the Rust deductive kernel. ADR-001 + Plan §6
lock `Nemo Datalog` as the rule engine, with the Memory Scratchpad
expectation that "Task 5 may not yet need `Command::spawn` (Datalog is
in-process via `nemo`)." A `cargo search nemo` (verified 2026-04-30
against crates.io) returns no Nemo Rust *library* crate — only the
`nmo` CLI, a browser/WASM frontend, and Python bindings published by
the upstream knowsys/nemo team. The only in-process option that
honours the scratchpad's expectation is to substitute another active
Rust Datalog engine; the only out-of-process options are the `nmo`
CLI subprocess (which would force the warden discipline of ADR-004
into Task 5, ahead of the Z3/cvc5 binary integration in Task 6) or a
network-bound Nemo server (no upstream artefact exists). The
single-process substitution preserves both the scratchpad's
in-process invariant and ADR-004's intent that the warden lands with
the *first* external solver/Lean child (Z3 in Task 6).

In parallel, the *Octagon* abstract domain has a textbook
implementation (Miné 2006) that requires either a from-scratch DBM or
a third-party numerical-domain crate. No mature 2026 Rust crate ships
the relational octagonal domain off the shelf (Apron has C bindings
but is heavyweight and not a clean build dep for the kernel). Phase 0
needs only a *streaming hull* over canonical vital scalars to
demonstrate "Octagon bounds tighten correctly on sample telemetry";
the relational `+x +y ≤ c` machinery and Floyd-Warshall closure are
not on the critical path until rules grow beyond per-vital bands.

**Decision.**

1. **Datalog engine (in-process, sequential).** Replace Nemo with
   `ascent` (`crates.io/crates/ascent`, v0.8, MIT, `default-features
   = false`). `ascent` is a procedural-macro Datalog DSL with seminaive
   evaluation, mature relation algebra, and active 2024-2026
   maintenance; the macro generates a plain `Default + Send + Sync`
   struct so it cleanly composes with the rest of the kernel. The
   `par` default feature (rayon + dashmap + once_cell) is disabled so
   the kernel stays single-threaded and deterministic at this stage;
   re-enabling it is a future micro-decision tied to throughput need.
2. **Datalog program shape.** All numeric reasoning happens *outside*
   `ascent` (in the evaluator + Octagon). The Datalog input schema is
   exclusively threshold-breach facts keyed by `monotonic_ns` (`u64`);
   columns are `Eq + Hash` by construction, sidestepping the
   `f64`/Datalog impedance mismatch. Derived predicates split into
   named clinical conditions (`tachycardia`, `desaturation`, ...) and
   roll-up alarms (`early_warning`, `compound_alarm`).
3. **Octagon scope.** Phase 0 emits only single-variable bound
   constraints (`+x ≤ c`, `-x ≤ c`); the DBM is full-shape (`2n × 2n`
   over the canonical-vital arity) so future relational tightening
   does not require a struct refactor. Floyd-Warshall closure is
   *not* run in Phase 0 — for the single-variable subset of the
   octagonal lattice the cell-wise lattice operations (`update_min`
   on `tighten`; cell-wise `max` on `join`) already produce closed
   forms. Streaming semantics: `tighten_*` is *meet* (intersection),
   per-sample point octagons are *joined* (LUB) to recover the
   convex hull across the sample stream.
4. **Verdict surface is internal to the kernel.** The four wire-format
   schemas (Task 2) are unchanged; Task 6 introduces the SMT-backed
   `FormalVerificationTrace` populated from the Verdict + the SMT
   solver. The Verdict struct does derive `Serialize/Deserialize` so
   workflow plumbing in Task 8 can hand it across a Dapr/MCP boundary
   without re-encoding.
5. **Threshold rule fixtures are advisory.** `Phase0Thresholds` lives
   in the kernel for ergonomics today; the *authoritative* arithmetic
   claims are encoded as `OnionLIRTree → SmtConstraintMatrix` (Tasks
   4 + 6). The deductive engine is a downstream consumer — the SMT
   layer must NOT cross-import threshold bands.

**Consequences.** Phase 0 has a working deductive layer today without
inflating the warden roadmap. The Nemo substitution is narrow:
re-evaluating once the upstream Nemo project ships a Rust library
crate (or once we want the existential-rule chase that `ascent`
doesn't natively expose) is a single-decision swap behind the same
`evaluate(payload, rules) -> Verdict` API. Octagon scope is a Phase 0
conservative approximation; widening to relational octagonal
constraints is additive — the DBM shape and the meet/join scaffolding
are ready, only the Floyd-Warshall closure + relational `tighten_*`
methods need to be added. No subprocesses are spawned, so ADR-004's
warden discipline lands cleanly in Task 6 alongside the first Z3 /
cvc5 child.

**Alternatives rejected.**
- **`nmo` CLI subprocess from Task 5.** Forces warden boilerplate
  ahead of Task 6 (which must build it anyway for Z3/cvc5) and
  introduces an OS dependency for a pipeline stage that has a clean
  in-process option.
- **`crepe` (Datalog-as-procedural-macro).** Less actively maintained
  than `ascent`; lacks BYODS (Bring-Your-Own-Data-Structures), which
  we may want for indexed relations once the rule base grows.
- **`datafrog`.** Used by rustc/polonius; lower-level (manual
  iteration loops) than `ascent`, and doesn't generate a struct/run
  abstraction. Net: more boilerplate, less ergonomic for the rule
  set we expect to author by hand.
- **From-scratch Datalog in `cds_kernel`.** NIH violates ADR-007's
  "use the modern ecosystem" stance, and seminaive correctness is
  load-bearing for Phase 1+ rule scale.
- **Apron via FFI for the Octagon.** Heavyweight C dep; ADR-002
  forbids cross-language FFI for service boundaries (allowed inside
  the kernel process, but the build-system cost is disproportionate
  for Phase 0 single-variable bounds).
- **Per-clause Floyd-Warshall closure now.** Cubic in DBM size and
  unnecessary for the single-variable subset; revisit when relational
  constraints land.

---

## ADR-014 — Phase 0 SMT/cvc5 binary integration contract

**Status:** Accepted
**Date:** 2026-04-30

**Context.** Task 6 lands the Rust solver layer: a subprocess warden
that owns Z3 + cvc5 children plus thin drivers that turn an
[`SmtConstraintMatrix`] into a [`FormalVerificationTrace`] (Z3 →
sat/unsat + unsat core; cvc5 → Alethe proof). ADR-001 + ADR-006 fix
the *what* (Z3 primary, cvc5 for Alethe, MARCO for MUC enumeration in a
later phase). ADR-004 fixes the *defense-in-depth* for spawned
children. This ADR pins the *Phase 0 implementation contract* — the
solver-flag set, the script-rendering convention, the MUC ↔
source-span projection, and the small Phase 0 deviation from ADR-004's
SIGTERM→SIGKILL escalation.

A 2026-04-30 web search (`"State of the art SMT proof emission Alethe
LFSC 2026"`) confirmed the cvc5 1.3 Alethe-emission preconditions
(`--proof-format-mode=alethe`, `--simplification=none`,
`--dag-thresh=0`, `--proof-granularity=theory-rewrite`) and that Z3's
`(get-unsat-core)` is unchanged from prior versions — both still
require the corresponding `(set-option …)` directive ahead of the
logic header.

**Decision.**

1. **Module layout.** All solver code lives under
   `crates/kernel/src/solver/`. `mod.rs` exposes `verify`,
   `VerifyOptions`, `SolverError`, and `project_muc`. Submodules:
   `warden` (subprocess plumbing), `script` (SMT-LIB rendering),
   `z3` (Z3 driver), `cvc5` (cvc5 driver). The warden is intentionally
   solver-agnostic so Task 7's Lean / Kimina bridge can reuse it
   verbatim.
2. **Script rendering.**
   `script::render(matrix, RenderMode)` is the single source of truth
   for the SMT-LIBv2 text shipped to a solver. Every enabled
   `LabelledAssertion` is wrapped as `(assert (! <formula> :named
   <label>))` so:
   - Z3 returns the unsat core via `(get-unsat-core)` as a parenthesised
     list of those labels;
   - cvc5 references them in its Alethe `(assume <label> …)` steps,
     keeping the proof artifact and the MUC label set on a single
     stable identifier scheme.
   `RenderMode::UnsatCore` prepends `(set-option :produce-unsat-cores
   true)` and appends `(get-unsat-core)`. `RenderMode::Proof` is the
   bare `(check-sat)` script; cvc5's CLI flag handles proof emission.
3. **Z3 invocation.** `z3 -smt2 -in` over stdin, parsing
   `sat`/`unsat`/`unknown` + a single `(label …)` line on the unsat
   path. `(error …)` is surfaced as `SolverError::Z3Error`.
4. **cvc5 invocation.** `cvc5 --lang=smt2 --dump-proofs
   --proof-format-mode=alethe --simplification=none --dag-thresh=0
   --proof-granularity=theory-rewrite` over stdin. The verdict is the
   first non-empty line; everything after it is the Alethe
   S-expression and is captured verbatim into
   `FormalVerificationTrace.alethe_proof`. Empty proof bodies are
   coerced to `None` rather than `Some("")`.
5. **MUC ↔ source-span projection.** `solver::project_muc` looks up
   each unsat-core label in `matrix.assumptions[*].provenance`. When
   present, the label is replaced by the provenance string
   (`atom:<doc>:<start>-<end>`); when absent (e.g. a kernel-synthesised
   domain bound), the bare label survives so the trace still surfaces
   the offending assumption. Output is sorted + deduplicated for
   byte-stable JSON.
6. **Cross-solver agreement on `unsat`.** `verify` insists Z3 and cvc5
   agree before accepting an Alethe certificate. Disagreement is a
   hard `SolverError::SolverDisagreement` rather than a silent
   verdict-pick. Phase 0 does *not* run cvc5 on `sat` — Z3 alone is
   authoritative on consistency; cvc5 is only invoked when there is a
   refutation to certify.
7. **Z3 `unknown` is a hard error.** `SolverError::UnknownVerdict` is
   returned rather than fabricating a verdict. Phase 0's QF_LRA
   workload should never produce `unknown` for the canonical fixtures;
   if it does, the guideline must be triaged manually.
8. **Warden contract.** `warden::run_with_input(bin, args, stdin,
   timeout) -> RunOutcome` is the only spawn site in Task 6. Every
   `Command` carries `kill_on_drop(true)`. The wall-clock timeout is
   enforced by wrapping `child.wait_with_output()` in
   `tokio::time::timeout` — on expiry the future drops, which drops
   the child handle, which delivers `SIGKILL`. No UNIX-signal
   handlers are installed in any worker task. `SolverError::Warden`
   wraps `WardenError::{Spawn, Timeout, Io}` so callers can branch on
   the failure mode.
9. **Phase 0 deviation from ADR-004 §2.** ADR-004 specifies a
   SIGTERM-first escalation with SIGKILL on second expiry. Phase 0
   collapses this into a single SIGKILL via `kill_on_drop`. Z3 + cvc5
   are batch-style children with no shutdown hooks — a SIGTERM grace
   window buys nothing, and the Rust ecosystem's lints
   (`#![forbid(unsafe_code)]`) preclude `libc::kill(SIGTERM)` without
   pulling in a `nix`-style dependency. The two-stage escalation is
   reinstated in **Task 7** when the Lean / Kimina child lands, where
   shutdown grace materially differs (Lean keeps caches warm and is
   long-running). At that point either add a `nix` dep for safe
   SIGTERM delivery or amend this ADR if Phase 0 SIGKILL-only proves
   sufficient in practice.
10. **Binary discovery.** `VerifyOptions::{z3_path, cvc5_path}`
    default to bare command names (`z3`, `cvc5`) resolved via `$PATH`
    — Phase 0 convention is that the `Justfile` PATH-prefixes
    `.bin/` (ADR-008). The `solver_smoke` integration tests resolve
    `<repo>/.bin/{z3,cvc5}` explicitly via `env!("CARGO_MANIFEST_DIR")`
    so `cargo test --workspace` works outside `just`. Tests print a
    skip notice when the binaries are absent rather than failing
    (run `just fetch-bins`).
11. **Materialized proof artifact.** `proofs/contradictory-bound.alethe.proof`
    holds the cvc5 Alethe certificate for the canonical Phase 0
    contradiction. Checked-in for human inspection / snapshot diffing;
    the authoritative emitter is `solver::verify`. `proofs/README.md`
    documents the regeneration command.

**Consequences.**

- The Phase 0 SMT layer is now the deductive boundary required by
  hard-constraint **C3** (`SMT solver evaluates the entire constraint
  matrix before yielding the validity flag`). `verify` consumes the
  full matrix, runs `(check-sat)`, and only then emits a
  `FormalVerificationTrace`.
- Constraint **C4** (MUC → offending textual node) is honoured by
  `project_muc`: every unsat-core label round-trips to its
  `atom:<doc>:<start>-<end>` source-span via the provenance string the
  Python translator wrote in Task 4. The translator's UTF-8
  byte-offset validation (ADR-012 §4) is the boundary check that
  protects this round-trip from drift.
- The warden is solver-agnostic, so Task 7's Lean / Kimina bridge can
  reuse `warden::run_with_input` verbatim. Task 7 should add a
  `cds_kernel::lean` driver next to `solver::{z3, cvc5}` — not a
  parallel spawn site.
- The Phase 0 SIGKILL-only escalation is documented but not amended
  into ADR-004; Task 7 closes the loop.
- `tracing::debug!` from `solver::{z3, cvc5}` surfaces solver stderr
  for diagnostics without pollutiting the wire-format trace.

**Alternatives rejected.**

- **One driver for both Z3 and cvc5.** Diverging flag sets and parsing
  rules (Z3's `(label …)` core list vs. cvc5's S-expression Alethe
  body) bloat the abstraction without gaining anything; the two
  drivers are <120 LOC each.
- **Run cvc5 on `sat` payloads too.** No artifact to certify, doubles
  the wall-clock for the common case. Z3 alone is authoritative on
  consistency.
- **Run MARCO MUC enumeration in Task 6.** ADR-006 lists MARCO + HNN +
  CASHWMaxSAT for full MUC enumeration; that is a *post-Phase-0*
  refinement. Z3's single-pass `(get-unsat-core)` produces *a* core
  (not necessarily minimal in the formal MUC sense), which is
  sufficient for the Phase 0 gate and the source-span trace. The
  schema field is named `muc` for forward-compat; replacing the
  enumerator is a downstream swap behind the same `verify` API.
- **Carcara for in-process Alethe re-checking.** Carcara is the
  canonical 2026 Alethe checker, but ADR-006 routes the foundational
  re-check through Lean 4 / Kimina (Task 7), not Carcara. Re-evaluating
  this when Task 7 lands is allowed; for now, the `alethe_proof` field
  is treated as opaque text.
- **Implement `nix`-backed SIGTERM in Task 6.** `nix` (or any unsafe
  libc shim) is a dep we don't otherwise need today; the kernel
  forbids `unsafe_code`. Phase 0 SIGKILL-only is the simpler
  trade-off; reinstate at Task 7 when Lean process management
  benefits from a grace window.
- **Ship the Alethe proof inline as the gate artifact only.** Checking
  the proof file under `proofs/` keeps it inspectable in `git diff`
  and gives Task 7 a stable target for Kimina re-check experiments
  ahead of full pipeline wiring. Cost: one tracked file (~3.5 KB).

---

## ADR-015 — Phase 0 Lean 4 / Kimina re-check contract

**Status:** Accepted
**Date:** 2026-04-30

**Context.** Task 7 lands the Lean 4 interop. Plan §6 and ADR-006 fix
the *what* (Lean 4 via Kimina headless server is the foundational
re-checker for cvc5 Alethe certificates); ADR-014 §9 deferred the
SIGTERM-first warden escalation to Task 7 with the expectation that
Lean would land as a *kernel-spawned child*. Two surface-level
realities forced refinement before this ADR could pin the Phase 0
boundary:

1. **Protocol.** Plan §6 said "JSON-RPC". A 2026-04-30 web search
   (`"Kimina Lean headless server JSON-RPC schema 2026 Alethe re-check"`)
   plus a direct fetch of
   `github.com/project-numina/kimina-lean-server` and the technical
   report (arXiv:2504.21230) confirmed the actual protocol is **REST**
   over HTTP (FastAPI), single endpoint `POST /verify`, default
   `0.0.0.0:8000`. Constraint **C6** (JSON-over-TCP/IP and/or MCP) is
   satisfied — REST is JSON-over-TCP. Plan §6 has been amended to
   reflect the truth.
2. **Process model.** Kimina is an **operator-managed daemon**, not a
   per-call child. It maintains an LRU header cache across requests and
   parallel Lean REPL workers; killing it after each `recheck()` would
   waste the cache and cripple throughput. The kernel therefore does
   *not* spawn Kimina via the warden. Daemon lifecycle is the operator's
   responsibility (`python -m server` from the upstream repo, or a
   future `just kimina-up` recipe). The warden discipline still applies
   to anything the kernel itself spawns (today: Z3 + cvc5).
3. **Foundational vs. structural re-check.** A truly foundational
   Alethe re-check inside Lean's kernel requires `lean-smt`'s Alethe
   importer (or a Carcara-as-Lean tactic), both of which add Mathlib /
   project scaffolding that would explode Kimina's LRU header cache
   and make per-call elapsed time minutes-not-seconds. Phase 0 is a
   research-prototype gate; the bridge surface must be small enough
   that Phase 1 can swap in foundational re-checking without re-doing
   the wire format.

**Decision.**

1. **Module layout.** All Lean code lives under
   `crates/kernel/src/lean/`. `mod.rs` exposes `recheck`,
   `LeanOptions`, `LeanError`, `LeanRecheck`, `LeanMessage`,
   `LeanSeverity`. Submodules: `client` (HTTP — `POST /verify`,
   response decoder), `snippet` (Lean-source generator). The bridge is
   solver-agnostic-shaped: any future foundational re-check swaps
   `snippet::render` (and the Phase 0 probe contract) without
   touching the wire format or `LeanRecheck`.
2. **Transport = `reqwest` 0.13 with `rustls` + `webpki-roots`.**
   No native-TLS, no OpenSSL system dep. JSON body via the `json`
   feature. `default-features = false` keeps the dep tree minimal
   (no cookies, multipart, gzip/brotli).
3. **Request shape.** `POST /verify` with body
   `{ "codes": [{ "custom_id": "...", "proof": "<lean source>" }],
   "infotree_type": "none" }`. `infotree_type=none` skips the proof
   tree we don't consume in Phase 0, shaving response bytes.
4. **Response decoder is permissive.** Accepts the named-array
   envelope (`{ "results": [...] }`), the top-level array, and a
   single-result object. Per-message severity decodes from
   `severity` *or* `level` (both seen across Kimina releases) and
   maps to `LeanSeverity::{Info, Warning, Error}`. Body decodes from
   `data`, `text`, or `message`. Elapsed time decodes from
   `elapsed_ms`, `time` (u64 or f64 seconds), or `elapsed`. The
   permissive shape isolates the bridge from upstream Kimina /
   Lean-REPL field-name churn.
5. **Probe-based structural re-check (Phase 0).** The Lean snippet:
   - is **self-contained** — no `import Mathlib`, no `open` —
     so Kimina's LRU header cache stays cheap;
   - defines `def alethe_proof : String := "<escaped bytes>"` with
     standard Lean string escaping (`\\`, `\"`, `\n`, `\r`, `\t`);
     no raw-string `r#"..."#` density counting, no hex decoder;
   - emits four `#eval s!"PROBE name=value"` info messages:
     `byte_len`, `starts_paren`, `has_assume`, `has_rule`.

   The Rust client requires all four probes to land *and* every
   `byte_len > 0`, `starts_paren=true`, `has_assume=true`,
   `has_rule=true`, *and* zero error-severity messages, before
   returning `LeanRecheck::ok = true`. This proves the cvc5
   Alethe certificate has been ingested by Lean 4 across the
   JSON-over-TCP boundary (constraint **C6**) and that it carries
   the structural invariants every Alethe proof must.
6. **`FormalVerificationTrace` is not extended.** Task 2's wire
   format is unchanged. `LeanRecheck` is a kernel-internal wrapper
   that the future Dapr/MCP plumbing (Task 8) will serialize
   alongside the trace as a separate envelope. Bumping
   `SCHEMA_VERSION` is deferred until the Phase 1 foundational
   re-check decides what fields it actually needs.
7. **Daemon lifecycle is operator-owned.** The kernel does not
   spawn Kimina. `LeanOptions::kimina_url` defaults to
   `http://127.0.0.1:8000`. Auth is deliberately omitted in Phase 0
   (no `LEAN_SERVER_API_KEY` wiring); `LeanOptions::extra_headers`
   is the escape hatch when a deployment needs it.
8. **Warden SIGTERM amendment is rolled forward.** ADR-014 §9
   deferred SIGTERM-first escalation to Task 7. Because Kimina is
   not a kernel-spawned child, the deferral is *not* discharged
   here — it rolls forward to **Task 8** (Dapr workflow), where
   sidecar lifecycle owns daemon shutdown grace. The Z3 + cvc5
   batch children still use the single-stage SIGKILL path documented
   in ADR-014 §8–9; that is unchanged.
9. **Integration smoke is opt-in.** `tests/lean_smoke.rs` runs the
   full pipeline (`solver::verify` → `lean::recheck`) only when
   `CDS_KIMINA_URL` is set *and* the binaries
   (`.bin/{z3,cvc5}`) are present. Both gates print a loud skip
   notice on absence rather than failing — `cargo test --workspace`
   stays green on a fresh checkout. The `just rs-lean` recipe
   forwards `CDS_KIMINA_URL` from the operator's env.

**Consequences.**

- The Phase 0 Lean re-check honours **C6** (JSON-over-TCP) and the
  spirit of ADR-006 (Lean as the final foundational re-checker)
  while explicitly bracketing what "foundational" means in Phase 0.
  The Phase 1 swap to a `lean-smt`-style importer is a single
  rewrite of `snippet::render` plus a richer probe set; the bridge
  surface, response decoder, and `LeanRecheck` shape are
  forward-compatible.
- The kernel takes on `reqwest` (with `rustls` + `webpki-roots` +
  `json`) plus its transitive `hyper` / `tower` / `tokio-rustls`
  dep tree. Build-time cost ~30 s on a cold cache; binary-size
  delta is acceptable for Phase 0.
- The warden remains the single spawn site for kernel-owned
  children. ADR-004's invariants are preserved, and the
  SIGTERM-first deferral now rolls to Task 8 instead of Task 7.
- Plan §6 has been amended from "Kimina headless JSON-RPC" to
  "Kimina headless REST (POST /verify)" so future sessions read
  ground truth.

**Alternatives rejected.**

- **Kimina-as-kernel-child.** Spawning the daemon per-call would
  defeat the LRU header cache (which is half the point of Kimina)
  and force the warden to baby-sit a long-running Python process.
  Operator-owned lifecycle is the upstream-supported pattern.
- **JSON-RPC bridge.** Plan §6 said JSON-RPC, but Kimina exposes
  REST — there is no JSON-RPC endpoint to talk to. Pinning a
  fictional protocol would have meant standing up an MCP shim or
  custom RPC layer for no reason.
- **Foundational re-check via `lean-smt` in Phase 0.** Pulls
  Mathlib + project scaffolding into Kimina's REPL header, blowing
  out cache cost and per-call latency, for a Phase 0 gate that
  doesn't yet have a Phase 1 plan to consume foundational proofs
  end-to-end. Deferred to a future ADR.
- **Embedding the proof via raw-string `r#"..."#`.** Lean's lexer
  does not support arbitrary `#` density (you'd need to count `"#`
  occurrences in the proof body and pick `n+1` `#`s on both sides).
  Standard string escaping is round-trip safe and decoder-free.
- **Hex-encoding the proof and decoding in Lean.** Adds a Lean-side
  decoder for no benefit over standard string escaping.
- **Adding a `lean_recheck` field to `FormalVerificationTrace`.**
  Bumps `SCHEMA_VERSION` for an outcome that is downstream of the
  trace, not part of the Task 2 wire-format contract. The
  `LeanRecheck` struct is its own Dapr/MCP envelope.
- **`reqwest` with `default-tls` (native-tls / OpenSSL).** Pulls
  in OpenSSL system deps; `rustls` keeps the build hermetic and
  cross-distro.
- **`hyper` directly (no `reqwest`).** Saves <1 MB of compile-time
  cost in exchange for ~150 LOC of body-shaping boilerplate;
  `reqwest` is the 2026 standard for async HTTP per the same web
  search referenced above.

---

## ADR-016 — Phase 0 Dapr 1.17 foundation contract (Task 8 split)

**Status:** Accepted
**Date:** 2026-04-30

**Context.** Task 8 (Dapr workflow orchestration — sidecar boundaries
Rust↔Python↔solvers) is too large for a single context-window session.
Past sessions exhausted the budget on installer plumbing alone. This
ADR splits Task 8 into four atomic sub-sessions and pins the **Phase 0
foundation** that all of them depend on.

A 2026-04-30 web search (`"State of the art Dapr workflow polyglot
orchestration 2026 1.17 slim mode"`) confirms Dapr 1.17 (released
2026-02-27) ships:

- **Workflow versioning** for safe in-flight code evolution.
- **41 % higher Workflow throughput.**
- **End-to-end tracing** with caller-trace-linked workflow spans.
- Polyglot Workflow SDKs (Python, .NET, Go, Java, JS).
- First-party `pubsub.in-memory` and `state.in-memory` components for
  zero-dependency dev/test.
- **Slim self-hosted mode** (`dapr init -s`) that skips Docker and
  stages `daprd`, `placement`, `scheduler`, `dashboard` as plain
  binaries under a configurable runtime path.

**Decision.**

### 1. Sub-task split

| Sub-task | Scope | Smoke gate |
| -------- | ----- | ---------- |
| **8.1 — Foundation** *(this ADR)* | Component manifests + Configuration + Justfile recipes (`fetch-dapr`, `dapr-init`, `dapr-status`, `dapr-clean`, `dapr-smoke`) + foundation pytest. | `just dapr-smoke` boots `daprd` ~3 s, both components load, Workflow engine starts, clean shutdown. |
| **8.2 — Python harness service** | FastAPI/uvicorn app exposing `/v1/ingest` + `/v1/translate`; runs under `dapr run --app-id cds-harness …`. | Service-level pytest exercises both endpoints through the sidecar. |
| **8.3 — Rust kernel service** | Axum service exposing `/v1/deduce`, `/v1/solve`, `/v1/recheck`; runs under `dapr run --app-id cds-kernel …`. | Cargo integration test exercises all three endpoints through the sidecar. |
| **8.4 — End-to-end Workflow** | Python Dapr Workflow chaining `ingest → translate → deduce → solve → recheck`; placement + scheduler spawned at orchestration time; per-stage `tracing` spans + Workflow events. | End-to-end pipeline runs under Dapr against a canonical guideline; verification flag round-trips. |

### 2. Slim self-hosted mode (Phase 0 lock)

Phase 0 runs Dapr in **slim mode**. No Docker, no Redis, no Zipkin
sidecar. The CLI + slim binaries (`daprd`, `placement`, `scheduler`,
`dashboard`) are staged under `.bin/.dapr/.dapr/` by `just fetch-dapr`,
keeping the install hermetic and project-local in line with ADR-008.
Phase 1+ revisits the K8s deployment when it materially helps the
research prototype (it does not in Phase 0).

### 3. Component locked-in selections

- `pubsub.in-memory v1` (`cds-pubsub`) — ephemeral broker; Phase 0 only.
- `state.in-memory v1` (`cds-statestore`) with **`actorStateStore=true`**
  — Dapr 1.17 Workflow runs on durable actors and *requires* a state
  store flagged as the actor store. The in-memory backing means
  Workflow state evaporates on `daprd` restart; Phase 0 accepts that
  one pipeline run is one daprd lifecycle. Phase 1+ swaps to a durable
  backend (SQLite first, Postgres second) once long-lived workflows
  matter.

### 4. Configuration locked-in

`dapr/config.yaml` (`metadata.name: cds-config`):

- `tracing.samplingRate: "1"` (sample everything) +
  `tracing.stdout: true` (Phase 0 has no OTLP collector — Phase 1+
  swaps to OpenTelemetry Collector / Jaeger).
- `metric.enabled: true`.
- `mtls.enabled: false` (single dev host; constraint **C6** still holds
  because the wire is JSON-over-TCP and Dapr's API is local-only on
  127.0.0.1 by default).

### 5. Sidecar invocation contract

Each Phase 0 service launches under

```
dapr run \
  --runtime-path .bin/.dapr \
  --app-id <cds-harness | cds-kernel> \
  --resources-path dapr/components \
  --config dapr/config.yaml \
  --app-protocol http \
  -- <command>
```

`--runtime-path .bin/.dapr` is the project-local override; `dapr run`
appends `/.dapr/bin/daprd`. Constraint **C6** (JSON-over-TCP/IP and/or
MCP) is satisfied — Dapr APIs are HTTP/JSON or gRPC/JSON and the
component wire is itself JSON-over-TCP between sidecar and broker.

### 6. Placement / scheduler bring-up — deferred to Task 8.4

`dapr init -s` *stages* the `placement` and `scheduler` binaries but
does **not** start them. A `dapr run` invocation today loads
components and starts the Workflow engine, then logs `connection
refused` on `:50005` (placement) and `:50006` (scheduler) every ~500 ms
until shutdown. These warnings are expected in 8.1's foundation smoke
because no actor / Workflow instance is being driven yet.

Task 8.4 owns standing up placement + scheduler as background processes
(via `just placement-up` / `just scheduler-up` recipes that route
through tokio `Command::kill_on_drop(true)` + a shutdown trap in line
with ADR-004). The same recipes can ship a `just dapr-pipeline` that
drives the end-to-end Workflow.

### 7. SIGTERM-first deferral (carried from ADR-014 §9 → ADR-015 §8)

This ADR rolls the SIGTERM-first escalation forward to Task 8.4. The
foundation smoke drives `daprd` only; clean shutdown is delivered by
the Dapr CLI's own SIGTERM path (`Exited Dapr successfully` line in the
log). Task 8.4 introduces kernel-managed `placement`/`scheduler`
children, which is when the warden gains a graceful-shutdown grace
window — either via the `nix` crate for safe `kill(SIGTERM, …)` or by
amending ADR-014 to ratify Phase 0's SIGKILL-only stance permanently.

### 8. Dapr install pinning

`DAPR_VERSION` defaults to `1.17.0` in the Justfile; `DAPR_OS=linux`,
`DAPR_ARCH=amd64`. Override via env (`DAPR_VERSION=1.17.1 just
fetch-dapr`). `fetch-dapr` is idempotent — skips if both `.bin/dapr`
and `.bin/.dapr/.dapr/bin/daprd` are already executable. `dapr-clean`
removes `.bin/dapr` and `.bin/.dapr/`; `dapr-init` is the
"force-re-init" alias.

### 9. Foundation smoke gate

The Task 8.1 smoke test (`just dapr-smoke` + the matching pytest
`test_daprd_smoke_loads_components_and_starts_workflow` in
`python/tests/test_dapr_foundation.py`) drives `dapr run --
sleep 2` and asserts five log markers in the captured output:

1. `Component loaded: cds-pubsub (pubsub.in-memory/v1)`
2. `Component loaded: cds-statestore (state.in-memory/v1)`
3. `Using 'cds-statestore' as actor state store`
4. `Workflow engine started`
5. `Exited Dapr successfully`

Any missing marker → smoke fails loudly with the captured daprd log
piped to stderr. The pytest variant gates skip-with-reason if the CLI
or daprd binary is absent, mirroring `rs-lean`'s gate shape.

**Consequences.** Future Claude sessions hand off a small, repeatable
foundation that 8.2/8.3/8.4 can build on without re-deriving install
plumbing or component selection. Each sub-session has its own clear
gate; none has to ship "all of Task 8" inside one context window.
The in-memory state store creates one operational hazard — Workflow
state evaporates on daprd restart — but Phase 0 is a single-run
research prototype and the trade is documented at the boundary.

**Alternatives rejected.**

- **Single Task-8 session.** Repeatedly tried; repeatedly truncated
  by context-window pressure. C5 (one atomic task per session) holds
  only if the atomic unit is small enough to ship.
- **Docker-mode `dapr init` (no `-s`).** Pulls the placement + Redis
  + Zipkin containers, requires Docker on the host, hostile to
  hermetic provisioning under `.bin/`. Phase 0's research-prototype
  scope makes the trade clearly net-negative.
- **`pubsub.redis` / `state.sqlite` for Phase 0.** Adds a runtime
  dependency for a single-run research prototype. Phase 1+ takes the
  swap when durable Workflow replay actually matters.
- **`actorStateStore=false` to silence placement noise.** Breaks the
  Workflow engine — Dapr 1.17 Workflows ride on durable actors. The
  warning noise is the right trade.
- **Re-enabling mTLS now.** Single-host loopback traffic; mTLS adds
  CA-rotation overhead with zero security benefit before Phase 1's
  multi-host deployment.

---

## ADR-017 — Phase 0 Python harness Dapr service contract (Task 8.2)

**Status:** Accepted
**Date:** 2026-04-30

**Context.** Task 8.2 is the second of the four Task-8 sub-sessions split
in ADR-016. The Python harness already shipped CLI entrypoints for
ingest (Task 3) and translate (Task 4); 8.2 binds them behind a thin
JSON-over-TCP service so a Dapr sidecar can drive them via
service-invocation.

**Decision.**

### 1. Module layout (`python/cds_harness/service/`)

- `app.py` — `create_app()` factory; `_StrictModel` request envelopes
  (discriminated `format` for `/v1/ingest`); `_InlineAdapter` plumbs the
  recorded-fixture-equivalent root straight into `translate_guideline`
  without a filesystem detour.
- `__main__.py` — argparse + `uvicorn.Server` entrypoint. Honours
  `CDS_HARNESS_HOST` / `CDS_HARNESS_PORT` (default `127.0.0.1:8081`),
  with `--host` / `--port` overrides.
- `__init__.py` — re-exports the constants + `create_app` +
  `resolve_host` / `resolve_port` so callers (and tests) bind only the
  public surface.

### 2. Endpoint contracts (constraint C6 — JSON-over-TCP)

- `GET /healthz` → `{status, harness_id, phase, schema_version}`. Used
  as the app-readiness probe.
- `POST /v1/ingest` accepts a discriminated body keyed on `format`:
  - `{"format": "json", "envelope": {...}}` →
    `cds_harness.ingest.load_json_envelope` (validate + canonicalize an
    in-memory `ClinicalTelemetryPayload`).
  - `{"format": "csv", "csv_text": "...", "meta": {...},
    "file_label"?: "..."}` → `cds_harness.ingest.load_csv_text`.
  Returns `{"payload": {...ClinicalTelemetryPayload}}`.
- `POST /v1/translate` accepts `{doc_id, text, root, logic?, smt_check?}`
  and returns `{tree, matrix, smt_check}` where `smt_check` is
  `"sat"`/`"unsat"`/`"unknown"`/`null`.

### 3. Sidecar wiring

The Phase 0 invocation contract is the one ADR-016 §5 already
documented. With `CDS_HARNESS_PORT=8081`, the canonical command is:

```
dapr run \
  --app-id cds-harness \
  --app-port 8081 \
  --app-protocol http \
  --runtime-path .bin/.dapr \
  --resources-path dapr/components \
  --config dapr/config.yaml \
  -- uv run python -m cds_harness.service
```

Inbound traffic from peers lands at
`http://localhost:<dapr-http-port>/v1.0/invoke/cds-harness/method/v1/{ingest|translate}`.
The `just py-service-dapr` recipe wraps the canonical command.

### 4. Readiness probe — `/v1.0/healthz/outbound`, NOT `/v1.0/healthz`

Dapr 1.17's `/v1.0/healthz` returns 500 until placement/scheduler are
reachable. Placement bring-up is deferred to Task 8.4 (ADR-016 §6), so
for 8.2 the right readiness gate is `/v1.0/healthz/outbound`, which
returns **204 No Content** as soon as daprd can route service-invocation
calls to the app port. The pytest sidecar smoke probes outbound, then
drives both endpoints. When 8.4 stands placement up, Task 8.4 may flip
the gate back to `/v1.0/healthz`.

### 5. JSON-over-TCP first; Dapr SDK deferred

Phase 0 sticks to plain `httpx` over the daprd HTTP port. The Dapr
Python SDK is a candidate for Phase 1+ but adds a dependency and a
learning surface that 8.2 does not need to validate the
service-invocation contract.

### 6. In-memory ingestion helpers

`cds_harness.ingest.load_json_envelope(raw)` and
`cds_harness.ingest.load_csv_text(csv_text, meta, *, file_label)` were
added so the service can accept payloads on the wire without writing to
the local filesystem. Existing `load_json(path)` / `load_csv(path)`
delegate to the new helpers; behaviour for the file-based loaders is
unchanged.

### 7. Console scripts

`[project.scripts]` now exposes `cds-ingest`, `cds-translate`, and
`cds-harness-service`. The third was the carry-forward note from Task 7
and simplifies `dapr run -- cds-harness-service` for downstream
orchestrators.

### 8. Dependency migration

- `fastapi>=0.115`, `uvicorn[standard]>=0.32`, `httpx>=0.28` added to
  `[project.dependencies]`.
- `[tool.uv] dev-dependencies` migrated to top-level
  `[dependency-groups] dev = [...]` per the deprecation warning surfaced
  by `uv` since Task 4. The two are kept in sync — the `[project.optional-dependencies] dev`
  group still exists for `pip install '.[dev]'` compatibility, and the
  `[dependency-groups] dev` group is uv-native and silences the
  deprecation warning.

**Consequences.** Task 8.3 (Rust kernel) inherits the same JSON-over-TCP
shape, the same readiness-probe gate, and the same exception-to-422
mapping convention. Task 8.4 (Workflow) builds on top of
service-invocation between the two app-ids; the Workflow harness now has
a stable wire surface to chain.

**Alternatives rejected.**

- **Multipart `/v1/ingest` for CSV.** FastAPI supports it, but the wire
  format diverges from the JSON-over-TCP discipline (constraint C6) and
  costs an extra dependency on `python-multipart`. The discriminated
  `format` field on a JSON body keeps every payload inspectable / teeable
  and aligns with ADR-002.
- **Dapr Python SDK in Phase 0.** Adds a runtime dependency for a
  feature (service invocation) that is one HTTP POST through
  `:dapr-http-port`. Phase 1+ may swap when actor / Workflow
  state-store handles materially benefit from typed bindings.
- **Spawning Kimina from the harness.** Per ADR-015 the Lean re-checker
  daemon is operator-managed; 8.2 stays out of that lifecycle.
- **Probing `/v1.0/healthz` for sidecar readiness in Phase 0.** Returns
  500 with placement down — would force a fragile retry loop. Outbound
  is the documented Phase 0 gate until Task 8.4 stands placement up.

---

## ADR-018 — Phase 0 Rust kernel Dapr service foundation contract (Task 8.3a)

**Status:** Accepted
**Date:** 2026-04-30

**Context.** Task 8.3 (Rust kernel Dapr service) was the third sub-task
in the Task 8 split (ADR-016). Like its predecessors, the original
single-session scope — three pipeline endpoints (`/v1/deduce`,
`/v1/solve`, `/v1/recheck`) plus the foundation plus the Dapr smoke —
repeatedly exceeded a single context window. Plan §8 §nb on
2026-04-30 split it into **8.3a (this ADR — foundation only)** and
**8.3b (three pipeline endpoints + cargo integration test through
daprd)**. The split mirrors the foundation-then-binding shape that
ADR-016 / ADR-017 already established for the Python harness side;
8.3a is the symmetric Rust-side foundation.

**Decision.**

### 1. Module layout (`crates/kernel/src/service/`)

- `app.rs` — `build_router()` factory; `KernelHealthz` response shape;
  `SERVICE_APP_ID` / `HEALTHZ_PATH` constants. The router wires
  `tower_http::trace::TraceLayer::new_for_http()` so 8.3b's `/v1/*`
  handlers and 8.4's Workflow events inherit a single tracing
  convention.
- `config.rs` — `resolve_host` / `resolve_port` from `CDS_KERNEL_HOST`
  / `CDS_KERNEL_PORT`, with a pure `parse_port_raw` helper so the
  unit tests do not need to mutate the process environment.
- `errors.rs` — `ErrorBody { error, detail }` struct + `IntoResponse`
  impl returning HTTP 422 by default. The wire shape is identical to
  the Python harness service's `JSONResponse({"error", "detail"})`
  (ADR-017 §2) so polyglot clients use one decoder.
- `bin/cds_kernel_service.rs` — argparse-equivalent (only `--help` /
  `-h`; everything else is an env var) + tokio multi-thread runtime +
  `axum::serve(...).with_graceful_shutdown(...)` listening on
  `Ctrl-C` and SIGTERM (Unix only). A `[[bin]]` entry named
  `cds-kernel-service` lets `dapr run -- cds-kernel-service` resolve
  via `$PATH` once `target/debug/` is on it.

### 2. Endpoint contract (Phase 0 / Task 8.3a)

- `GET /healthz` → `{status: "ok", kernel_id, phase, schema_version}`.
  Response field order matches the Python harness `_Healthz` so
  smoke clients can decode either backend without reshaping.
- `/v1/deduce`, `/v1/solve`, `/v1/recheck` are **out of scope** for
  8.3a. The `errors::ErrorBody` envelope is the wire shape they will
  drop into in 8.3b.

### 3. Sidecar wiring

The Phase 0 invocation contract is the one ADR-016 §5 documented;
ADR-017 §3 instantiated it for the Python side. The kernel side
mirrors:

```
dapr run \
  --app-id cds-kernel \
  --app-port 8082 \
  --app-protocol http \
  --runtime-path .bin/.dapr \
  --resources-path dapr/components \
  --config dapr/config.yaml \
  -- target/debug/cds-kernel-service
```

Inbound traffic from peers lands at
`http://localhost:<dapr-http-port>/v1.0/invoke/cds-kernel/method/...`.
The `just rs-service-dapr` recipe wraps the canonical command;
`just rs-service` runs the binary standalone (no sidecar).

### 4. Default port — 8082, not 8081

The Python harness service holds 8081 (ADR-017 §1). The kernel
service deliberately picks 8082 so both can run side-by-side under
a single `just dapr-pipeline` (Task 8.4). Override via
`CDS_KERNEL_PORT` if 8082 collides locally.

### 5. Readiness probe — same `/v1.0/healthz/outbound` gate

Phase 0 placement bring-up is deferred to Task 8.4 (ADR-016 §6), so
the kernel-side smoke uses the same `/v1.0/healthz/outbound` (204)
probe that ADR-017 §4 documents. Task 8.4 may flip both services'
gates back to `/v1.0/healthz` once placement is up.

### 6. SIGTERM-first test cleanup via `nix`

The gated `dapr_sidecar_drives_healthz_through_service_invocation`
integration test sends `SIGTERM` to the dapr CLI process before
falling back to SIGKILL after a 5 s grace. Reason: tokio's
`Child::kill()` (SIGKILL on the immediate child) **does not
propagate** to the dapr CLI's grandchildren (daprd + the kernel
binary), which would orphan them to PID 1 and leak state across
test invocations. The Python harness test uses Python's
`subprocess.terminate()` — which is SIGTERM by default and lets the
dapr CLI's signal handler reap its descendants — and 8.3a matches
that behaviour by adding `nix = { version = "0.31", default-features = false, features = ["signal"] }`
as a `[dev-dependencies]` entry on the kernel crate. `nix` is a
safe wrapper over the `kill(2)` syscall, preserving the kernel's
top-level `#![forbid(unsafe_code)]` invariant.

The kernel-side warden's own SIGTERM-first escalation (ADR-014 §9 →
ADR-015 §8 → ADR-016 §7) **remains deferred to Task 8.4**. ADR-018
narrowly authorizes SIGTERM for *test cleanup* of the `dapr` CLI
process; the production solver-warden behaviour is unchanged in
8.3a.

### 7. JSON-over-TCP only; Dapr SDK deferred (parity with ADR-017 §5)

8.3a sticks to plain HTTP through daprd; the Dapr Rust SDK is a
candidate for Phase 1+ if the workflow / actor / pub-sub
state-store handles materially benefit from typed bindings.

### 8. axum 0.8 + tower-http 0.6, default-features = false

`axum = { features = ["http1", "json", "tokio", "macros"] }` —
HTTP/2, multipart, query, ws, fs are intentionally *not* enabled.
JSON-over-TCP (constraint **C6**) does not need them; pulling them
in widens the attack surface and the dependency closure with no
8.3a / 8.3b benefit. `tower = { features = ["util"] }` for
`ServiceExt::oneshot` in unit tests; `tower-http = { features =
["trace"] }` for the request-level tracing span.

**Consequences.** Task 8.3b inherits a stable router factory + error
envelope + binary entrypoint, and only needs to add the three
pipeline handlers + their domain-error `IntoResponse` impls + a
broader sidecar smoke that exercises all three endpoints under
daprd. Task 8.4 (Workflow) gets a kernel sidecar with the same
service-invocation shape as the harness sidecar; the polyglot
Workflow can chain them with one HTTP client.

**Alternatives rejected.**

- **`hyper` directly, no axum.** Saves one dep but loses ergonomic
  routing, extractors, and the `IntoResponse` mapping that 8.3b
  needs for three error types. axum 0.8 is the documented 2026 SOTA.
- **`actix-web` instead of axum.** Larger runtime, separate
  thread-per-core actor model, and no clean tokio-only path that
  matches the warden's existing `tokio::process::Command` lifecycle.
- **`clap` for argument parsing.** Useful when more than `--help` is
  needed; for 8.3a everything is env-var driven so a hand-rolled
  `--help` keeps the binary tiny. Re-evaluate in 8.3b if richer
  flag parsing emerges.
- **A `cds_kernel_service::AppState` struct.** No state is shared in
  8.3a (the healthz handler is pure). 8.3b will introduce one if
  the pipeline handlers need shared `VerifyOptions` / `LeanOptions`;
  introducing an empty `AppState` now would be premature
  abstraction.
- **Cargo integration test calling `cargo run` to spawn the binary.**
  Re-builds inside a test invocation are fragile; cargo's
  `CARGO_BIN_EXE_<name>` env var gives the integration test a
  pre-built binary path with no fork-from-cargo cost.
- **Spawning daprd directly without the dapr CLI.** Loses the
  components/config-path resolution + automatic shutdown of the
  app; would force the test to manage daprd's flag surface
  manually. The CLI is the documented Phase 0 entrypoint.

## ADR-019 — Phase 0 Rust kernel pipeline handlers contract (Task 8.3b → 8.3b1 + 8.3b2 split)

**Status:** Accepted
**Date:** 2026-05-01

**Context.** Task 8.3b inherited the foundation that ADR-018 / Task
8.3a shipped (router factory, `ErrorBody { error, detail }` envelope,
`bin/cds_kernel_service.rs` entrypoint, sidecar Justfile recipes).
Its original single-session scope bundled four work items: (a) three
`POST /v1/{deduce,solve,recheck}` handlers wiring the existing
in-process pipelines (`crate::deduce::evaluate`,
`crate::solver::verify`, `crate::lean::recheck`); (b) per-pipeline
`IntoResponse` impls so `DeduceError` / `SolverError` / `LeanError`
lift transparently to HTTP 422 with the `{error, detail}` envelope;
(c) comprehensive unit tests via `tower::ServiceExt::oneshot`; (d) a
daprd-driven cargo integration test exercising all three endpoints
through `/v1.0/invoke/cds-kernel/method/v1/...` plus an `AppState`
materializing env-driven `VerifyOptions` / `LeanOptions` overrides
(`CDS_KIMINA_URL`, `CDS_Z3_PATH`, `CDS_CVC5_PATH`). That bundle
again exceeded a single context window — the same pattern that
forced Task 8 → 8.1–8.4 (ADR-016) and 8.3 → 8.3a + 8.3b (ADR-018).
Plan §8 §nb on 2026-05-01 split 8.3b along the natural
foundation/integration boundary into **8.3b1 (this ADR — handlers +
`IntoResponse` impls + unit tests, stateless)** and **8.3b2 (daprd
integration test + `AppState` + env-driven option overrides)**.

**Decision.**

### 1. Module layout (additions to `crates/kernel/src/service/`)

- `handlers.rs` (new) — three `async fn` handlers (`deduce`, `solve`,
  `recheck`), three request envelopes (`DeduceRequest`,
  `SolveRequest`, `RecheckRequest`) all carrying
  `#[serde(deny_unknown_fields)]`, two option-wire structs
  (`SolveOptionsWire`, `RecheckOptionsWire`) with
  `into_verify_options()` / `into_lean_options()` lowerings, and
  three Lean wire DTOs (`LeanRecheckWire`, `LeanMessageWire`,
  `LeanSeverityWire`) that bridge from internal `lean::LeanRecheck`
  to the JSON wire shape. Path constants
  `DEDUCE_PATH = "/v1/deduce"`, `SOLVE_PATH = "/v1/solve"`,
  `RECHECK_PATH = "/v1/recheck"` live alongside `HEALTHZ_PATH`.
- `errors.rs` (extension) — three `IntoResponse` impls for
  `DeduceError`, `SolverError`, `LeanError` plus three
  stable-tag helpers (`deduce_error_kind`, `solver_error_kind`,
  `lean_error_kind`). Every variant of every error lifts to HTTP
  422 with `{"error": "<stable_tag>", "detail": "<Display>"}`.
- `app.rs` (extension) — `build_router()` now mounts three
  `post(...)` routes alongside the existing `get(healthz)`; routing
  middleware (`TraceLayer`) is unchanged.
- `mod.rs` (extension) — `pub mod handlers;` plus re-exports of
  the wire types so external consumers (cargo integration tests in
  8.3b2) can import directly from `cds_kernel::service::*`.

### 2. Request envelope contract — strict by default

All three request envelopes carry `#[serde(deny_unknown_fields)]`.
This is intentionally conservative: silent drop of unknown fields
would mask Workflow producer bugs (Task 8.4) and contradicts the
strict-decode discipline that ADR-011 §3 / ADR-017 §2 already
enforced on the Python harness side. The cost — clients must keep
their schemas in sync — is the right cost for a Phase 0 polyglot
contract where a typo in `optoins` is far more likely than a real
forward-compat extension. Forward compatibility, when it matters,
will be carried by an explicit `schema_version` field rather than
permissive decoding.

### 3. `timeout_ms` wire shape, not `timeout_seconds`

`SolveOptionsWire.timeout_ms` and `RecheckOptionsWire.timeout_ms`
are `Option<u64>` of milliseconds. Internal `VerifyOptions::timeout`
and `LeanOptions::timeout` are `std::time::Duration`; the wire
lowering uses `Duration::from_millis`. Reasons: (a) JSON has no
`Duration` type and milliseconds are unambiguous on the wire;
(b) the harness side already emits `timeout_ms` (ADR-017 §2 — the
guideline-tuner trace records ms), so a single client decoder
covers both backends; (c) `u64` gives ~584 million years of
headroom which is fine for any timeout the warden will ever honour.
If sub-millisecond precision becomes relevant it will be a new
field, not a breaking change to this one.

### 4. Unwrapped responses — pipeline results lower directly

Handlers return `Result<Json<T>, E>` where `T` is the pipeline's
own result type (`deduce::Verdict`, `solver::FormalVerificationTrace`,
`LeanRecheckWire`) — no `{result: ..., warnings: ..., metadata: ...}`
envelope. Reasons: (a) every pipeline result already carries its
own structured detail (verdict + matched rules; trace + Alethe
proof + MUC; recheck + diagnostics) and wrapping would duplicate
nothing useful; (b) unwrapped success + enveloped error
(`{error, detail}` 422) is the same shape the Python harness
service uses (ADR-017 §2), so a single client decoder works across
all six Phase 0 endpoints; (c) Workflow stages in 8.4 will pass
results between sidecars by structured value, not by HTTP
envelope, so the wire contract should map to the value shape.

### 5. `LeanRecheckWire` DTO — break the Serialize coupling

The internal `lean::LeanRecheck` does **not** derive `Serialize`,
deliberately: deriving it would force `#[serde(rename_all =
"snake_case")]` on `lean::LeanSeverity`, a public type with
existing `Display` / `Debug` test assertions across the lean
module. Adding a wire-only DTO (`LeanRecheckWire`,
`LeanMessageWire`, `LeanSeverityWire`) with `From<&LeanRecheck>`
lowering is the standard Rust workaround for this serde-vs-domain
collision: the internal type stays free to evolve (it can grow
non-`Serialize`-compatible fields later), and the wire shape is
explicit at the boundary. The same pattern already exists in
`crate::deduce` (no internal `Serialize`; the harness translator
side speaks AST JSON via its own DTOs) and the cost — three small
structs in `handlers.rs` — is well below the cost of forcing
serde traits down through the lean module.

### 6. Per-handler tracing spans

Each handler is annotated with
`#[tracing::instrument(skip(req), fields(stage = "<deduce|solve|recheck>"))]`.
This gives the Workflow side (Task 8.4) per-stage spans that
nest cleanly under the `tower_http::trace::TraceLayer` request
span without leaking the request payload (which can carry
clinical data) into trace fields. `skip(req)` is non-negotiable
for any handler whose payload could be PHI; `fields(stage = ...)`
gives operators a single search key to slice all traces by
pipeline.

### 7. CPU-bound deduce on `spawn_blocking`

The deduce handler wraps `deduce::evaluate(&payload, &rules)` in
`tokio::task::spawn_blocking`. Reason: the ascent Datalog seminaive
pass (ADR-013) is fully synchronous CPU work; running it on the
async runtime's scheduler thread would block the executor and
starve concurrent solve/recheck calls under load. `solver::verify`
and `lean::recheck` already drive subprocesses / HTTP via tokio
async I/O so they stay on the runtime threads. The blocking task
is owned by the handler `Future`; cancellation drops the
`JoinHandle`, which causes the blocking pool to drop the closure
once it next yields — acceptable for a Datalog evaluator that
runs in tens of milliseconds for Phase 0 fixtures.

### 8. Subprocess hygiene — preserved through the handler boundary

`solver::verify` and `lean::recheck` keep their existing
`.kill_on_drop(true)` semantics (ADR-004 §2). The handlers `await`
them directly inside the request future, so a client cancellation
or a tower timeout drops the future, which drops the `Child`
handle, which sends SIGKILL to z3/cvc5/curl-equivalent on Unix.
No new subprocess code is introduced in 8.3b1; the only addition
is the HTTP boundary on top.

### 9. Test discipline — `tower::oneshot` for handler unit tests

All in-handler tests use `tower::ServiceExt::oneshot(req)` to drive
the router without binding a TCP listener. Two reasons: (a) it
matches the per-route discipline ADR-018 §6 already established
for the foundation tests (no real port, no real sidecar); (b)
spinning up a real listener in unit tests would conflict with the
8.3b2 daprd integration test for port 8082 / 50001. The
`runtime_tests` module covers: deduce-happy (verdict round-trip),
deduce-non-canonical-vital (kind tag + 422), solve-warden (warden
spawn failure → kind tag + 422), recheck-no-proof
(`{sat: true}` → kind tag + 422), recheck-transport (URL
unreachable → kind tag + 422). Solver z3/cvc5 happy paths and
Lean Kimina happy paths are not exercised here because they need
real subprocess / HTTP fixtures; those land in 8.3b2's daprd
integration test where the sidecar plus existing
`solver_smoke` / `lean_smoke` fixtures already cover them.

### 10. AppState — deferred to 8.3b2

8.3b1's handlers consume request-side options + `::default()`
fallbacks (`VerifyOptions::default()`, `LeanOptions::default()`).
No state is shared. Introducing an empty `AppState` now would be
premature abstraction; introducing a populated one would conflate
the env-override resolution (which 8.3b2 owns) with the handler
plumbing. The router factory keeps its `Router::new()` shape and
will gain `.with_state(AppState { … })` in 8.3b2.

### 11. SIGTERM-first warden escalation — still deferred

ADR-014 §9 → ADR-015 §8 → ADR-016 §7 → ADR-018 §6 each rolled the
production solver-warden's SIGTERM-first escalation forward. 8.3b1
**does not change that contract**: the warden still uses tokio
`Child::kill()` (SIGKILL on the immediate child) for production
timeouts. ADR-018 §6's narrow authorization for SIGTERM in *test
cleanup* of the dapr CLI is unchanged. Production SIGTERM-first
remains scheduled for Task 8.4 alongside the Workflow-driven
end-to-end gate where graceful subprocess shutdown matters most.

**Consequences.** Task 8.3b2 inherits a stable handler surface +
error envelope + per-pipeline `IntoResponse` impls + a green
`tower::oneshot` test suite, and only needs to add the daprd-driven
cargo integration test, the `AppState` populated from env vars at
boot, and the `just rs-service-smoke` extension that exercises the
new pipeline cases. Workflow (Task 8.4) gets a polyglot pipeline
where `ingest → translate` (harness) → `deduce → solve → recheck`
(kernel) all share the same `{error, detail}` 422 envelope and the
same per-stage tracing convention.

**Alternatives rejected.**

- **Single `/v1/pipeline` endpoint dispatching by `stage` field.**
  Forces every caller through one handler with a giant enum
  payload; loses URL-level routing and the per-handler tracing
  spans; complicates the OpenAPI / type story Workflow will want
  in 8.4. Three explicit endpoints map 1:1 to three pipelines.
- **Permissive request decoding (no `deny_unknown_fields`).**
  Saves a clippy gate but masks producer bugs. ADR-011 / ADR-017
  already established strict decode on the harness side; matching
  it on the kernel side keeps the polyglot story consistent.
- **`timeout_seconds: f64` instead of `timeout_ms: u64`.** Floats
  on JSON timeout fields invite NaN/Inf edge cases in serde and
  mismatch the harness's existing `timeout_ms` wire convention.
- **Forcing `Serialize` on `lean::LeanRecheck` instead of a wire
  DTO.** Would propagate `#[serde(rename_all = "snake_case")]` to
  `LeanSeverity` and force serde derives across the lean module,
  coupling internal evolution to the wire format. The `From`
  lowering is the standard fix.
- **Synchronous deduce on the async runtime thread.** The ascent
  pass is CPU-bound; running it on a runtime thread starves
  concurrent async handlers. `spawn_blocking` keeps the executor
  responsive at the cost of one thread-pool hop per call.
- **Wrapping success responses in `{result, warnings}`.** Adds a
  second envelope shape to the polyglot contract for no concrete
  Phase 0 benefit. Errors are already enveloped; success flows
  the pipeline value directly. Symmetric with the harness side.
- **Introducing `AppState` in 8.3b1 as an empty placeholder.**
  Empty state increases the router factory's signature, breaks
  `Router::new()` typing in tests, and adds nothing the handlers
  use. 8.3b2 owns `AppState` because it owns the env-override
  resolution that gives it a reason to exist.
- **Daprd-driven integration test in 8.3b1.** That is exactly the
  scope cut — fitting it back in is what blew the original 8.3b
  context budget. 8.3b2 owns it.

## ADR-020 — Phase 0 Rust kernel pipeline Dapr smoke split (Task 8.3b2 → 8.3b2a + 8.3b2b)

**Status:** Accepted
**Date:** 2026-05-01

**Context.** Task 8.3b2 inherited from ADR-019 §10 + the
Memory_Scratchpad open-notes block a four-fold scope: (a) introduce
`KernelServiceState { verify_options: VerifyOptions, lean_options:
LeanOptions }` resolved at boot from `CDS_Z3_PATH` / `CDS_CVC5_PATH`
/ `CDS_KIMINA_URL` / `CDS_SOLVER_TIMEOUT_MS` / `CDS_LEAN_TIMEOUT_MS`;
(b) refactor the three pipeline handlers from stateless to
`axum::extract::State<KernelServiceState>` consumers, with
per-request `options` retaining replace-the-floor semantics; (c)
lift the existing smoke helpers (`pick_free_port`,
`wait_until_ready`, SIGTERM-cleanup teardown) from
`tests/service_smoke.rs` into a shared `tests/common.rs` module; and
(d) ship three daprd-driven cargo integration tests, one per
pipeline endpoint, hitting `/v1.0/invoke/cds-kernel/method/v1/{deduce,solve,recheck}`
against canonical fixtures. That bundle again exceeded a single
context window — the same context-overflow pattern that already
forced Task 8 → 8.1–8.4 (ADR-016), Task 8.3 → 8.3a + 8.3b
(ADR-018), and Task 8.3b → 8.3b1 + 8.3b2 (ADR-019). Plan §8 §nb on
2026-05-01 split 8.3b2 along the natural external-dependency
boundary into **8.3b2a (this ADR — foundation refactor + the
dependency-free `/v1/deduce` Dapr smoke)** and **8.3b2b (close-out:
`/v1/solve` + `/v1/recheck` Dapr smokes gated on `.bin/z3` +
`.bin/cvc5` and `CDS_KIMINA_URL` respectively)**.

**Decision.**

### 1. Split rationale — external-dependency boundary

8.3b2's three integration tests fall cleanly into two cohorts:

- **`/v1/deduce`** — drives `cds_kernel::deduce::evaluate` against
  a synthetic `ClinicalTelemetryPayload`. Pure Rust + ascent Datalog
  (ADR-013). No subprocess, no external solver, no Kimina daemon. The
  only runtime dependency is daprd itself, which the existing
  `service_smoke.rs` foundation gate already wires up.
- **`/v1/solve`** — depends on `.bin/z3` + `.bin/cvc5` binaries
  staged by `just fetch-z3` / `just fetch-cvc5` (ADR-008). On a
  fresh checkout `.bin/` is empty until `just fetch-bins` runs. The
  fixtures (`data/guidelines/contradictory-bound.recorded.json`)
  carry the canonical unsat trace.
- **`/v1/recheck`** — depends on a running Kimina daemon
  (operator-managed per ADR-015 §3); the test must skip with a
  loud notice when `CDS_KIMINA_URL` is unset, mirroring
  `tests/lean_smoke.rs`.

Splitting along this boundary keeps 8.3b2a's gate self-contained
(no `.bin/` provisioning required at session-time, no Kimina
dependency) while 8.3b2b inherits a stable foundation and adds the
two gated tests as a focused close-out. The foundation refactor
(`KernelServiceState`, handler `State` extraction, `tests/common.rs`
lift) is the prerequisite for both gated tests but is large enough
on its own to warrant its own session.

### 2. 8.3b2a contract — foundation + deduce smoke

- **State type.** `KernelServiceState { verify_options:
  VerifyOptions, lean_options: LeanOptions }` lives in
  `cds_kernel::service::state` (new module) or folds into `app.rs`
  if compact. `Clone` + `Send + Sync` (axum `State` requires
  `Clone`).
- **Constructor `from_env()`.** Reads the five env vars in §1's
  context. Defaults match the existing `VerifyOptions::default()`
  / `LeanOptions::default()` shapes: bare `z3` / `cvc5` from
  `$PATH`, `http://127.0.0.1:8000`, 30 s solver timeout, 60 s lean
  timeout. Invalid values (non-utf8, non-numeric ms, overflowing
  u64) **panic at boot**; same fail-loud discipline as
  `service::config::parse_port_raw` (ADR-018 §1).
- **Handler refactor.** Three handlers gain `State(state):
  State<KernelServiceState>` as a leading argument. Per-request
  `options` retains replace-the-floor semantics: present fields
  win; absent fields fall back to `state.verify_options` /
  `state.lean_options`. `/healthz` stays stateless via either a
  separate stateless sub-router merged in via `Router::merge`, or
  a healthz-router-then-pipeline-router composition. The choice is
  a session-time implementation detail; the constraint is "no
  state plumbed through `/healthz`".
- **`build_router(state: KernelServiceState) -> Router<()>`.**
  The factory signature changes; tests must construct a
  state instance (cheap — `KernelServiceState::default()` provided
  for tests). The `bin/cds_kernel_service.rs` entrypoint
  constructs state via `KernelServiceState::from_env()` before
  serving.
- **`tests/common.rs`.** New module-shared file collecting the
  three helpers (`pick_free_port`, `wait_until_ready`, SIGTERM
  cleanup wrapper) that 8.3a originally inlined into
  `service_smoke.rs`. Each integration test file declares
  `mod common;` and uses `#[allow(dead_code)]` on items the file
  doesn't exercise. This was forecast in 8.3b1's open notes
  ("lift them to a shared `tests/common.rs` module if a second
  integration test grows") — 8.3b2a is exactly that growth point.
- **Deduce Dapr smoke.** Single new test in
  `tests/service_smoke.rs`. Synthetic `ClinicalTelemetryPayload`
  with samples spanning the canonical-vital allowlist; one
  out-of-band reading (e.g., `heart_rate = 30 bpm`); asserts
  non-empty `breach_summary`. Runs through
  `/v1.0/invoke/cds-kernel-deduce-smoke/method/v1/deduce` (distinct
  app-id from the foundation healthz smoke).
- **Justfile.** No recipe rename. `rs-service-smoke` continues to
  run the whole `tests/service_smoke.rs` suite; the new test joins
  the existing two cases for a 3-test gate. `--test-threads=1`
  carried unchanged.
- **Gate.** `cargo test --workspace` green (target ~143 pass:
  137 baseline + ~5 state unit + 1 deduce-Dapr smoke); clippy
  clean; fmt clean; pytest 95/95 untouched; `just rs-service-smoke`
  3/3.

### 3. 8.3b2b contract — solve + recheck smokes (close-out)

- **`/v1/solve` Dapr smoke.** Drives
  `data/guidelines/contradictory-bound.recorded.json` through
  `/v1.0/invoke/cds-kernel-solve-smoke/method/v1/solve`. Asserts
  `verdict == Unsat` + Alethe proof present. Gated on `.bin/z3` +
  `.bin/cvc5` presence with loud SKIP when absent.
- **`/v1/recheck` Dapr smoke.** Re-derives or re-uses the trace
  from the solve smoke and POSTs to
  `/v1.0/invoke/cds-kernel-recheck-smoke/method/v1/recheck`.
  Asserts `severity == Info` + recheck succeeded. Gated on
  `CDS_KIMINA_URL` presence with loud SKIP when absent
  (matches `tests/lean_smoke.rs` discipline).
- **Per-request `options` pin the binaries.** Both smokes set
  `options.z3_path` / `options.cvc5_path` to absolute `.bin/z3` /
  `.bin/cvc5` paths so the test does not rely on `$PATH`
  resolution inside daprd's environment. This also serves as the
  on-the-wire validation that 8.3b2a's per-request override
  semantics work end-to-end.
- **Test-file decision (deferred to 8.3b2b session-time).** If
  `tests/service_smoke.rs` grew long enough during 8.3b2a (>~500
  lines or >~7 tests), 8.3b2b splits solve+recheck into
  `tests/service_pipeline_smoke.rs` and adds a new
  `just rs-service-pipeline-smoke` recipe; otherwise both cases
  stay in `service_smoke.rs` and `rs-service-smoke` covers them.
  The decision is made at 8.3b2b session-time based on actual
  file shape; this ADR doesn't pre-commit.
- **Gate.** `cargo test --workspace` green (target ~143 + 2 gated
  smokes when binaries + Kimina present, else ~143 + 2 SKIPs);
  clippy/fmt/pytest unchanged; `just rs-service-smoke` (or paired
  `just rs-service-pipeline-smoke`) covers solve + recheck cases;
  manual six-endpoint round-trip check (kernel: `/healthz`,
  `/v1/{deduce,solve,recheck}`; harness: `/healthz`,
  `/v1/{ingest,translate}`) against their respective daprd
  sidecars. **This is the close-out of 8.3b** — 8.4 composes
  these endpoints via Dapr Workflow.

### 4. Env mutation hazard — pick `serial_test` or sub-process

`from_env()` reads process-global state; cargo's parallel test
runner can race two `from_env_panics_on_non_numeric_timeout`-style
tests if they each set and unset the same variable. 8.3b2a picks
**one** of: (a) `serial_test = "3"` as a `[dev-dependencies]`
addition with `#[serial_test::serial]` on the env-mutating
unit tests; or (b) drive the env-mutation tests via a sub
`std::process::Command` so each owns its environment. Pick the
shorter dep delta at session-time; both are defensible. The
constraint this ADR pins is: **do not** rely on cargo's
single-thread-default-for-integration-tests as the env isolation
mechanism, because integration-test serialization is enforced via
the Justfile `--test-threads=1`, not via cargo defaults, and that
discipline must not bleed into unit tests.

### 5. Per-request override semantics — replace, not cap

Per-request `options.timeout_ms`, when present, **replaces** the
env-resolved timeout; it does not add or cap. Same for
`z3_path` / `cvc5_path` / `kimina_url`. This matches the 8.3b1
contract where `Option<…OptionsWire>` already had per-field
replace semantics; 8.3b2a is changing the floor from
`::default()` to `state.…`. The replace rule is documented in
handler-side comments and in the 8.3b2a open-notes block in
`Memory_Scratchpad.md`.

### 6. SIGTERM-first warden escalation — still deferred

ADR-014 §9 → ADR-015 §8 → ADR-016 §7 → ADR-018 §6 → ADR-019 §11
each rolled the production solver-warden's SIGTERM-first escalation
forward. Neither 8.3b2a nor 8.3b2b changes that contract: the
warden still uses tokio `Child::kill()` (SIGKILL on the immediate
child) for production timeouts. ADR-018 §6's narrow authorization
for SIGTERM in *test cleanup* of the dapr CLI is unchanged; the
helper that lives in `tests/common.rs` after 8.3b2a continues to
own that narrowly-authorized SIGTERM path. Production SIGTERM-first
remains scheduled for Task 8.4 alongside the Workflow-driven
end-to-end gate.

**Consequences.** Task 8.3b2a is sized to fit a single context
window: a focused refactor (state introduction + handler `State`
extraction + helper lift) plus one dependency-free integration
test plus ~5 state unit tests. Task 8.3b2b inherits a stable
foundation and adds the two gated integration tests as a
close-out — both are conceptually small once `tests/common.rs` is
in place. Workflow (Task 8.4) gets a polyglot pipeline where every
kernel-side handler reads its option floor from env, every
per-request override has well-defined replace semantics, and every
sidecar has been validated through a daprd-driven cargo
integration test (kernel `deduce`/`solve`/`recheck` + harness
`ingest`/`translate`).

**Alternatives rejected.**

- **Single `8.3b2` session, accept the context overflow.** Has
  failed twice for the surrounding tasks (ADR-018, ADR-019). The
  cost of another mid-session context exhaustion is far higher
  than the cost of one ADR + plan-row split.
- **Split along the per-endpoint axis (8.3b2a = deduce; 8.3b2b =
  solve; 8.3b2c = recheck).** Three sub-tasks instead of two.
  The foundation refactor (`KernelServiceState` + handler
  `State` extraction + `tests/common.rs`) cuts cleanly with deduce
  but doesn't decompose further. solve + recheck are each small
  enough that splitting them adds session overhead without
  reducing per-session scope. Two sub-tasks is the right
  granularity.
- **Defer `tests/common.rs` lift to 8.3b2b.** Would force 8.3b2a
  to inline its helpers (`pick_free_port`, `wait_until_ready`,
  SIGTERM cleanup) directly in `service_smoke.rs` alongside
  the existing 8.3a helpers, then deduplicate in 8.3b2b. The
  duplication-then-lift path is more total work than the
  lift-once-up-front path, and 8.3b1 already forecast the lift.
- **Defer `KernelServiceState` introduction to Task 8.4.** Would
  leave 8.3b2 owning only the daprd integration tests and 8.4
  inheriting both the state refactor and the Workflow scope. 8.4
  is already large (Workflow harness + placement bring-up + per-
  stage tracing + SIGTERM-first warden decision); folding the
  state refactor in would push *that* session over the budget.
  The state refactor lives where it provides immediate value:
  the test that exercises per-request override semantics
  end-to-end through daprd.
- **Eliminate `KernelServiceState` and read env vars per-request.**
  Pushes env parsing onto every request's hot path; loses the
  fail-loud-at-boot semantics that catch typos in operator
  configuration before the first request. Boot-time resolution +
  one-shot state is the standard axum pattern.
- **Permit silent fallback on invalid env values.** Masks
  operator typos (`CDS_SOLVER_TIMEOUT_MS=30s` parses as a panic
  rather than as 30000 ms — fail-loud is the right call). The
  fail-loud rule lifts directly from `service::config::parse_port_raw`
  (ADR-018 §1) and the same arguments apply.

---

## ADR-021 — Phase 0 end-to-end Workflow split (Task 8.4 → 8.4a + 8.4b)

**Status:** Accepted
**Date:** 2026-05-01

**Context.** Task 8.4 inherited from ADR-016 §6 + the Memory_Scratchpad
open-notes block a seven-fold scope: (a) `just placement-up` /
`just scheduler-up` recipes that bring the slim-staged Dapr
`placement` + `scheduler` binaries up as long-running background
processes (currently staged but never started — ADR-016 §6 explicitly
deferred this); (b) **production** SIGTERM-first warden escalation in
`crate::solver::warden::run_with_input` — replacing the single-stage
`kill_on_drop`-only SIGKILL contract documented in
`solver/warden.rs:1-13` with two-stage SIGTERM → grace-window →
SIGKILL fallback (the deferral has rolled forward through six prior
ADRs: 014 §9 → 015 §8 → 016 §7 → 018 §6 → 019 §11 → 020 §6); (c)
flipping the kernel + harness daprd-driven cargo / pytest readiness
gate from `/v1.0/healthz/outbound` (Phase 0 — placement down, ADR-017
§4 / ADR-018) back to `/v1.0/healthz` once placement is up; (d) a new
Python `cds_harness.workflow` package implementing a Dapr Workflow
that chains `ingest → translate → deduce → solve → recheck` as five
activities, each a service-invocation call against the Phase 0
sidecars validated through Tasks 8.2 + 8.3a + 8.3b1 + 8.3b2a + 8.3b2b;
(e) per-stage `tracing` spans correlated through Workflow
activity-id; (f) the aggregated cross-stage envelope shape
(`{ payload, ir, matrix, verdict, trace, lean_recheck }`) plus the
deferred design call between in-band JSON and Dapr state-store
handles; (g) a `just dapr-pipeline` recipe + integration smoke that
brings everything up, drives the canonical guideline through the
five-stage pipeline, asserts the verification flag round-trips, and
tears the cluster down cleanly. That bundle is materially larger
than 8.3b2 (which itself was split into 8.3b2a + 8.3b2b on
2026-05-01 per ADR-020 because three cohesive integration tests +
one foundation refactor + one helper lift exceeded a single context
window). Plan §8 §nb on 2026-05-01 splits 8.4 along the natural
**Rust-foundation vs. Python-composition** boundary into **8.4a (this
ADR — placement+scheduler bring-up + production SIGTERM-first warden
escalation + readiness gate flip)** and **8.4b (Python Dapr Workflow
harness + aggregated envelope + per-stage tracing +
`just dapr-pipeline` + end-to-end smoke close-out)**.

**Decision.**

### 1. Split rationale — language-stack + dependency boundary

The seven inherited work items partition cleanly by language stack
and dependency direction:

- **8.4a — Rust + Justfile foundation.** Owns the long-deferred
  warden refactor (one file: `crates/kernel/src/solver/warden.rs`,
  ~175 lines today, plus its three existing `tokio::test`
  unit cases), the two new Justfile recipes for placement/scheduler
  bring-up + a unified `dapr-cluster-up` aggregator, and the
  one-line readiness-probe flip in the shared `tests/common.rs`
  helper that all five daprd-driven cargo integration tests funnel
  through (`tests/service_smoke.rs` + `tests/service_pipeline_smoke.rs`).
  Self-contained: no Python touchpoints, no Workflow harness, no
  cross-stage envelope decisions. The outputs feed 8.4b but 8.4b
  cannot need the warden refactor's *implementation details* — it
  only needs the contract that long-running solver children honour
  graceful shutdown.
- **8.4b — Python Workflow + close-out.** Owns the new
  `cds_harness.workflow` package, the five `@activity` decorated
  callables, the aggregated envelope shape, the per-stage tracing
  decision, the `just dapr-pipeline` recipe, and the end-to-end
  pytest smoke. Depends on 8.4a's outputs (placement+scheduler must
  be running for Workflow to schedule activities; the warden
  refactor must not regress the kernel solver / lean pipelines)
  but only at the contract surface. No Rust kernel changes; no
  warden touchpoints.

Splitting along this boundary keeps 8.4a's gate self-contained
within the Rust workspace + Justfile (cargo test + clippy + fmt +
the new `just dapr-cluster-up` smoke) and 8.4b's gate self-contained
within the Python workspace + the cluster bring-up that 8.4a
delivers (pytest + ruff + the new `just dapr-pipeline` smoke). The
Workflow harness composition is the close-out of Task 8 in its
entirety; its scope is exactly large enough on its own to fill a
session given the Dapr Python SDK introduction (ADR-017 §5 deferred
the SDK; 8.4b decides whether to introduce it or stay on plain
`httpx` for service-invocation).

### 2. 8.4a contract — Dapr cluster bring-up + warden hardening

- **`just placement-up` recipe.** Background-spawns
  `.bin/.dapr/.dapr/bin/placement` with stable bind ports
  (`:50005` is the Dapr-1.17 default; pin via `--port` flag for
  reproducibility). Logs to `target/dapr-placement.log`. The recipe
  prints the PID and exits; teardown is by `just dapr-cluster-down`
  (also new). On Linux, supervises the child via the
  `setsid`/process-group trick so a `Ctrl-C` on the launching
  shell propagates SIGTERM to the placement process group.
- **`just scheduler-up` recipe.** Symmetric to `placement-up` —
  background-spawns `.bin/.dapr/.dapr/bin/scheduler` on `:50006`
  (Dapr-1.17 default). Same supervision discipline.
- **`just dapr-cluster-up` aggregator.** Composes
  `placement-up` + `scheduler-up`; idempotent (skips if PIDs in the
  recorded pid-files are still alive). `dapr-cluster-down`
  SIGTERM-then-grace-then-SIGKILLs both children — same shape as
  8.3a's `tests/common::sigterm_then_kill` helper but lifted to the
  Justfile via a small bash function. Pid-files live under
  `target/` so `cargo clean` reclaims them.
- **`just dapr-cluster-status` printout.** Mirrors `dapr-status` —
  prints the placement + scheduler PIDs (or "not running"), the
  log paths, and the bound ports. Useful operationally and for
  the 8.4b workflow smoke's pre-flight check.
- **Production SIGTERM-first warden escalation.** Refactor
  `crate::solver::warden::run_with_input` to two-stage shutdown:
  on wall-clock timeout, send `SIGTERM` to the child (via
  `nix::sys::signal::kill(Pid::from_raw(child.id() as i32),
  Signal::SIGTERM)`), wait up to a configurable grace window
  (default `Duration::from_millis(500)` — same shape as
  `tests/common::sigterm_then_kill(_, Duration::from_secs(5))` but
  shorter because the warden grace is per-child, not per-CLI), then
  fall through to tokio `Child::kill()` (SIGKILL) on grace expiry.
  `kill_on_drop(true)` stays on every `Command` so an upstream
  panic / cancellation still triggers SIGKILL — the two-stage
  escalation only fires on the timeout path. Promote `nix` from
  the kernel crate's `[dev-dependencies]` (added in 8.3a per
  ADR-018 §6 narrow auth) to `[dependencies]`; same feature set
  (`default-features = false`, `features = ["signal"]`).
- **`WardenError` shape preserved.** The existing
  `WardenError::Timeout { bin, timeout }` remains the surface
  error; the two-stage escalation is an implementation detail. No
  variant is added — callers (`solver::z3`, `solver::cvc5`,
  `service::handlers`, error-tag mapping in `service::errors`) all
  continue to consume the same enum.
- **Warden tests grow by two cases.** The existing three tokio
  unit tests (`echoes_stdin_through_cat`,
  `timeout_kills_long_running_child`,
  `missing_binary_yields_spawn_error`) stay; two new cases land:
  (a) `timeout_sigterm_first_when_child_traps_term` — uses a
  small bash one-liner via `/bin/bash -c 'trap "exit 0" TERM;
  while :; do sleep 1; done'` so the child *exits* on SIGTERM
  before the grace expires; assert the warden returns
  `WardenError::Timeout` (the wall-clock budget was still
  exceeded — only the kill mechanism changed) and the elapsed
  wall-clock is in `[wall_clock, wall_clock + grace]`; (b)
  `timeout_sigkill_fallback_when_child_ignores_term` — uses
  `/bin/bash -c 'trap "" TERM; while :; do sleep 1; done'` so
  SIGTERM is no-op'd; assert `WardenError::Timeout` and elapsed
  wall-clock is in `[wall_clock + grace, wall_clock + grace +
  reasonable-margin]`. These are hermetic on any Linux dev host.
- **Readiness gate flip.** `tests/common::wait_until_ready`
  currently probes `/v1.0/healthz/outbound` per ADR-017 §4 /
  ADR-018 §5 (Phase 0, placement down). Once 8.4a's
  `dapr-cluster-up` exists, integration tests can flip back to
  `/v1.0/healthz` (Dapr 1.17's full-readiness probe — returns 204
  iff sidecar + placement are both reachable). The flip is
  optional in 8.4a if it complicates the transition: keep the
  outbound probe as the floor (continues to work whether or not
  placement is up), and let 8.4b's pipeline test additionally
  pre-flight `/v1.0/healthz` after starting the cluster. Pick at
  session-time based on whether the existing five integration
  tests stay green when targeted at `/v1.0/healthz` against a
  cluster-up sidecar — if yes, flip; if no, document the
  asymmetry and defer to 8.4b.
- **Gate.** `cargo test --workspace` green (target: 151 baseline +
  2 new warden cases = 153 pass); clippy clean; fmt clean; pytest
  95/95 untouched (no Python edits); `just dapr-cluster-up`
  followed by `just dapr-cluster-status` prints both PIDs +
  ports; `just dapr-cluster-down` reclaims both children;
  `just rs-service-pipeline-smoke` still green (warden refactor
  must not regress the existing solver/lean integration tests);
  `just env-verify` clean.

### 3. 8.4b contract — Python Workflow + close-out

- **`cds_harness.workflow` package.** New module under
  `python/cds_harness/`:
  - `__init__.py` — public re-exports (workflow registration,
    activity callables, `run_pipeline()` top-level entrypoint).
  - `pipeline.py` — the `@workflow` decorated function chaining
    five `yield ctx.call_activity(...)` calls; the aggregated
    envelope returned at the bottom. Each activity is a thin
    `httpx`-over-daprd wrapper around the relevant
    service-invocation URL.
  - `activities.py` — five `@activity` callables: `ingest`,
    `translate`, `deduce`, `solve`, `recheck`. Each calls
    `httpx.post("http://127.0.0.1:<DAPR_HTTP_PORT>/v1.0/invoke/<app-id>/method/<path>", json=...)`,
    decodes the response, propagates `{error, detail}` 422s as
    `WorkflowActivityError` exceptions so the runtime can apply
    its retry policy.
  - `__main__.py` — argparse + `dapr.workflow.WorkflowRuntime`
    setup + a `run_pipeline(payload)` console script that
    schedules a workflow instance, polls until terminal, prints
    the aggregated envelope, exits 0 on `Verdict::Sat` happy path
    or non-zero on the `Unsat` / `LeanError` paths (with the
    aggregated envelope still printed so an operator sees the
    full trace).
- **Dapr SDK introduction — ADR-017 §5 revisit.** ADR-017 §5
  deferred the Dapr Python SDK to a "Phase 1 candidate".
  Workflow's typed `@workflow` / `@activity` decorators + the
  `WorkflowRuntime`'s replay semantics + the activity-id-tagged
  tracing all materially benefit from the SDK over hand-rolled
  `httpx` orchestration. 8.4b therefore takes the SDK as a
  scoped dependency: `dapr>=1.17` + `dapr-ext-workflow>=1.17` in
  `[project.dependencies]`. The `httpx`-over-daprd path stays for
  service-invocation inside activities (ADR-017 §5's argument
  remains valid at the activity boundary — one HTTP POST does
  not warrant a typed binding); the SDK only owns Workflow
  registration + replay + tracing.
- **Aggregated envelope.** In-band JSON shape:
  ```json
  {
    "payload":  { "...ClinicalTelemetryPayload": "..." },
    "ir":       { "...OnionLIRTree": "..." },
    "matrix":   { "...SmtConstraintMatrix": "..." },
    "verdict":  { "...Verdict": "..." },
    "trace":    { "...FormalVerificationTrace": "..." },
    "recheck":  { "...LeanRecheckWire": "..." }
  }
  ```
  Reasons for in-band over state-store handles: (a) Phase 0
  payloads are small (single-pipeline-run shapes top out at
  low-kB JSON); (b) the JSON-over-TCP discipline (constraint C6 +
  ADR-002) keeps every cross-stage payload directly inspectable /
  teeable; (c) Workflow replay requires deterministic activity
  inputs — state-store handles add a serialization indirection
  that complicates replay debugging; (d) Phase 1+ swaps to
  state-store handles when payload shape grows or when payloads
  carry references to large external resources (raw FHIR
  bundles, full ECG waveforms). Phase 0 in-band JSON is the
  right call.
- **Per-stage tracing.** Every activity is annotated with
  `@tracing.span("workflow.<stage>")`-equivalent (`opentelemetry`
  Python SDK; the harness already imports `tracing`-equivalent
  via uvicorn). Spans link to the Dapr Workflow activity-id via
  the SDK's automatic correlation. The kernel-side
  `#[tracing::instrument(skip(req), fields(stage = "..."))]`
  (ADR-019 §6) already emits matching span structure on the Rust
  side, so the trace tree is end-to-end.
- **`just dapr-pipeline` recipe.** Top-level orchestrator:
  1. `just dapr-cluster-up` (8.4a's recipe) — placement +
     scheduler.
  2. `just py-service-dapr` — harness service under daprd
     (background, pid recorded).
  3. `just rs-service-dapr` — kernel service under daprd
     (background, pid recorded).
  4. `python -m cds_harness.workflow run-pipeline
     --payload data/sample/icu-monitor-01.json
     --guideline data/guidelines/contradictory-bound.txt`
     drives the canonical end-to-end run.
  5. Asserts the aggregated envelope contains
     `verdict.breach_summary` non-empty (deduce stage active),
     `trace.sat == false` (canonical contradictory guideline),
     and `recheck.ok == true` (Lean re-check passed) — the same
     three flags 8.3b2b's pipeline smoke already validates,
     now composed under Workflow.
  6. Tear down in reverse order; `dapr-cluster-down` last.
- **End-to-end pytest smoke.** `python/tests/test_dapr_pipeline.py`:
  one `@pytest.mark.skipif` gated test (gates: `.bin/dapr` +
  `.bin/.dapr/.dapr/bin/{placement,scheduler}` + `.bin/z3` +
  `.bin/cvc5` + `CDS_KIMINA_URL`). Spawns the cluster + both
  sidecars in fixtures, drives the canonical pipeline through
  the workflow runtime, asserts the same three flags as the
  Justfile recipe, tears down via the SIGTERM-first cleanup
  shape that 8.4a's warden refactor codifies. The pytest
  variant is the CI-amenable shape; the Justfile recipe is the
  developer-friendly shape.
- **Gate.** `uv run pytest` green (target: 95 baseline + 1 new
  end-to-end smoke = 96 pass); ruff clean; cargo test 153/153
  unchanged from 8.4a; `just dapr-pipeline` end-to-end against
  `data/guidelines/contradictory-bound.txt` returns
  `verdict ∧ trace.sat=false ∧ recheck.ok=true`; manual run
  on `data/guidelines/hypoxemia-trigger.txt` (consistent
  guideline) returns `verdict ∧ trace.sat=true ∧
  recheck.ok=true` — both canonical fixtures round-trip
  end-to-end. `just env-verify` clean. **This closes Task 8.**

### 4. SIGTERM-first warden — ratified, not deferred again

ADR-014 §9 → ADR-015 §8 → ADR-016 §7 → ADR-018 §6 → ADR-019 §11 →
ADR-020 §6 each rolled the production warden's SIGTERM-first
escalation forward. **8.4a closes the deferral.** The reason the
escalation lands in Task 8.4 specifically (and not earlier) is
that Workflow + placement-bound features introduce long-running
solver children that may hold non-trivial proof-state mid-flight;
SIGKILL-only on those is acceptable at the unit-fixture level
(8.3b1 / 8.3b2b's contradictory-bound traces are tens of
milliseconds) but operationally hostile when a Workflow retry
policy fires against a multi-second proof. The two-stage shape
(SIGTERM + grace + SIGKILL) gives the solver a chance to flush
partial state before being killed — same discipline as the
narrowly-authorized `tests/common::sigterm_then_kill` helper for
the daprd CLI (ADR-018 §6).

### 5. Readiness probe — `/v1.0/healthz` is the new floor when
cluster is up, `/v1.0/healthz/outbound` remains the floor when not

8.4a may flip the readiness gate in `tests/common::wait_until_ready`
from `/v1.0/healthz/outbound` to `/v1.0/healthz` if and only if
all five existing daprd-driven integration tests
(`tests/service_smoke.rs::dapr_sidecar_drives_*` x3 +
`tests/service_pipeline_smoke.rs::dapr_sidecar_drives_*` x2)
stay green when targeted at `/v1.0/healthz` against a cluster-up
sidecar. Otherwise — keep `/v1.0/healthz/outbound` as the helper's
floor (still works whether or not placement is up) and let 8.4b's
Workflow smoke additionally pre-flight `/v1.0/healthz` after
starting the cluster. The transition is documented in
`tests/common.rs` doc-comment so a future session reading the
helper can answer "why does this probe outbound and not the full
healthz?" without grepping ADRs.

### 6. Dapr Python SDK — taken in 8.4b, not deferred further

ADR-017 §5 deferred the Dapr Python SDK. 8.4b reverses that
decision **only for Workflow registration / replay / activity-id
tracing** — the surfaces where the SDK provides materially more
than `httpx`-over-daprd. Service-invocation calls inside activities
remain plain `httpx` POSTs because (a) constraint C6 is satisfied
by JSON-over-TCP without typed bindings, (b) the kernel-side
endpoints expose a stable `{error, detail}` 422 envelope that maps
cleanly to a 4-line `httpx.HTTPStatusError` decode, and (c)
keeping the SDK surface narrow keeps the 8.4b session bounded.

### 7. Cross-stage envelope — in-band JSON, not state-store handles

Phase 0 takes the in-band JSON envelope per §3 above. ADR-016 §3's
in-memory state store has `actorStateStore=true` already; nothing
prevents 8.4b from using state-store handles, but the trade — a
serialization indirection that complicates Workflow replay
debugging — is net-negative for Phase 0 payload sizes. ADR-021 §3
documents the decision; Phase 1+ revisits when payload shape grows.

### 8. Plan §8 ordering note

`8.1 < 8.2 < 8.3a < 8.3b1 < 8.3b2a < 8.3b2b < 8.4a < 8.4b < 9`.
Sub-task progression remains strict per Plan §8 §"At any
session" — no leapfrogging across the new boundary either.

**Consequences.** Task 8.4a is sized to fit a single context window:
one warden refactor (~30 lines net change to a 175-line file) +
two new warden tests + three Justfile recipes (`placement-up`,
`scheduler-up`, `dapr-cluster-up` + symmetric `*-down` aggregator)
+ optional one-line readiness-probe flip in
`tests/common.rs`. Task 8.4b inherits a stable cluster bring-up
contract + a hardened warden + the Phase 0 readiness gate, and
delivers the Workflow harness as a self-contained Python package
that closes Task 8 in its entirety. The end-to-end pipeline smoke
becomes the polyglot integration that validates every ADR-001 to
ADR-021 decision in a single recipe.

**Alternatives rejected.**

- **Single 8.4 session, accept the context overflow.** Has failed
  six times already for the surrounding tasks (ADRs 016, 018, 019,
  020). The cost of another mid-session context exhaustion is far
  higher than the cost of one ADR + plan-row split.
- **Three-way split (8.4a warden / 8.4b cluster recipes / 8.4c
  Workflow).** Adds session overhead without a real reduction in
  per-session scope: the warden refactor + the cluster recipes
  share the same testing discipline (SIGTERM-then-grace-then-
  SIGKILL escalation) and the same `nix` crate dependency
  promotion, so they belong in one session. Two sub-tasks is the
  right granularity.
- **Defer SIGTERM-first warden to Phase 1.** Would mean amending
  ADR-014 §9 to ratify SIGKILL-only as the permanent stance. The
  six-time deferral has already been the right call until now;
  but Workflow's retry-against-long-running-proof failure mode is
  the operational pressure that finally tips the trade. Pushing
  to Phase 1 would require a second pass through every solver
  test fixture once the trade is reconsidered; better to take the
  refactor now alongside the rest of Task 8's lifecycle work.
- **Ship the Workflow harness in 8.4a alongside the warden
  refactor.** Conflates Rust subprocess hygiene with Python
  Workflow composition; doubles the testing surface (cargo +
  pytest + integration smoke); reintroduces the context-overflow
  pattern. Splitting along the language boundary keeps each
  session's gate tractable.
- **Reverse the order: ship Python Workflow first, then warden
  refactor as 8.4b.** Workflow without placement+scheduler does
  not run end-to-end (the WorkflowRuntime can't schedule
  activities without a placement service). Workflow without
  SIGTERM-first warden runs but can leak partial proof-state on
  retry. Both gaps are addressable but make 8.4b's smoke less
  meaningful. Foundation-first is the right ordering.
- **State-store handles for the cross-stage envelope.** Adds a
  serialization indirection; complicates Workflow replay
  debugging; provides no Phase 0 benefit because payloads are
  low-kB. Phase 1+ revisits when payload shape grows.
- **Skip the Dapr Python SDK; do Workflow in pure `httpx`.** The
  Python SDK's `@workflow` / `@activity` decorators + replay
  semantics + automatic activity-id tracing are exactly what
  Workflow is for. Hand-rolling them on top of `httpx` would
  duplicate hundreds of lines from the SDK with no benefit. The
  service-invocation surface stays on `httpx` (per ADR-017 §5
  rationale) but Workflow runtime is the SDK's domain.
- **Forgo per-stage tracing.** Operators need it to triage which
  stage of a five-stage pipeline produced an anomalous result.
  Tracing is non-optional for the Phase 0 close-out.
- **Skip the `just dapr-pipeline` recipe; use the pytest only.**
  Justfile orchestration is the developer-friendly shape;
  pytest is the CI-friendly shape. Both are needed — neither
  fully replaces the other.

---

## ADR-022 — Phase 0 SvelteKit frontend split (Task 9 → 9.1 + 9.2 + 9.3)

**Status:** Accepted
**Date:** 2026-05-01

**Context.** Task 9 — the last open Phase 0 row in Plan §8 — is a
full vertical-slice frontend: SvelteKit project scaffolding under
`frontend/` (currently a `.gitkeep`-only directory) + Tailwind 4
utility-first CSS + ESLint 9 + Prettier 3 + Playwright + bun + Vite
toolchain wiring + a complete set of Justfile recipes
(`frontend-dev` / `frontend-build` / `frontend-lint` /
`frontend-test` / `frontend-e2e`) + TypeScript schema mirrors for the
six Phase 0 wire types (`ClinicalTelemetryPayload`, `OnionLIRTree`
plus its four `kind`-discriminated variants, `SmtConstraintMatrix`,
`Verdict`, `FormalVerificationTrace`, `LeanRecheckWire`, plus the
8.4b aggregated envelope and `PipelineInput`) + a SvelteKit
`+server.ts` BFF that calls the Phase 0 daprd sidecars validated
across 8.2 / 8.3a / 8.3b1 / 8.3b2a / 8.3b2b + a canonical
happy-path round-trip smoke through a real cluster + an AST tree
visualizer rendering the OnionL IR with per-node source-span
tooltips + an Octagon abstract-domain visualizer (2D projections of
`±x ±y ≤ c` constraints) + a MUC viewer cross-linking offending
atoms back into AST highlights + a verification-trace banner
displaying `sat / unsat ∧ Lean recheck pass/fail` with an Alethe
proof preview + an end-to-end Playwright UI smoke driving the
canonical pipeline through a live cluster + the Phase 0 → Phase 1
marker flip on `cds_harness.__init__.PHASE` and `cds_kernel::PHASE`
+ Task 9 close-out documentation. That bundle is materially larger
than every prior Phase 0 task split — Task 8 (ADR-016, 4-way),
8.3 (ADR-018, 2-way), 8.3b (ADR-019, 2-way), 8.3b2 (ADR-020, 2-way),
8.4 (ADR-021, 2-way) — each of which was forced into a planning-only
restructure session because a single context window could not hold
the inherited scope. Plan §8 §nb on 2026-05-01 splits Task 9 along
the natural **frontend-foundation / BFF-and-types / visualizers-and-
close-out** boundary into **9.1**, **9.2**, **9.3**.

**Decision.**

### 1. Split rationale — three-stage layered split, not two-stage

Unlike 8.4 (Rust foundation vs. Python composition) or 8.3b (handler
plumbing vs. integration test), Task 9 has **three** scope axes that
each warrant their own session:

- **Toolchain + scaffolding axis.** First-time introduction of the
  TS/JS toolchain into this repo (no existing `package.json`,
  `node_modules`, `bun.lockb`, `.eslintrc`, `prettier.config.*`,
  `playwright.config.*`, or Vite config exists today). `bun` is
  already in `just env-verify` (1.3.13 verified) but no JS code
  consumes it. Scaffolding is a self-contained, tooling-heavy
  session: SvelteKit's `sv create` template + Tailwind 4 plugin +
  ESLint 9 flat config + Prettier 3 + Playwright + Justfile
  integration. None of it depends on backend wire types or
  visualizer logic.
- **Wire-contract + transport axis.** The frontend's six TS schema
  mirrors and the BFF route shape are the **boundary contract**
  with the Phase 0 backend. They depend on the scaffold (9.1) but
  must precede any visualizer that consumes their types. They are
  also where the BFF's transport policy is decided
  (direct service-invocation vs. Workflow-via-`DaprWorkflowClient`)
  — a non-trivial design call that deserves its own session. A
  canonical happy-path round-trip smoke against the live cluster
  closes 9.2.
- **Visualization + UI close-out axis.** Four Svelte 5 components
  (AST tree, Octagon, MUC viewer, verification trace) + a
  Playwright E2E smoke + the Phase 0 → 1 marker flip + Task 9 (and
  Phase 0) close-out documentation. Each component is
  self-contained but they all consume the 9.2 BFF + types. The
  close-out paperwork (PHASE marker flip + Plan §10 step-7 update +
  the human-facing README touchups that mark Phase 0 complete) lives
  here because Phase 0 is not "done" until the UI shows the live
  trace round-trip end-to-end (Plan §8 row 9 success criterion).

A two-way split (e.g. "scaffold + types" vs. "visualizers +
close-out") would shove the BFF + smoke into one of the halves and
double its scope. A four-way split (e.g. visualizers as
9.3a / 9.3b) is left as a **further-split contingency** in §10
below — pulled in mid-flight only if the 9.3 session repeats the
context-window pattern, mirroring how 8.3 → 8.3b → 8.3b2 → 8.3b2a/b
each split mid-task once.

Splitting along these three axes keeps each session's gate tractable:
9.1's gate is `bun run build` + `bun run check` + lint clean; 9.2's
gate adds the live BFF round-trip against a `dapr-cluster-up`
cluster with both sidecars; 9.3's gate adds Playwright + the
PHASE flip + Phase 0 close-out.

### 2. 9.1 contract — frontend foundation

- **SvelteKit scaffold.** Use `sv create frontend --template minimal
  --types ts --no-add-ons` (the modern Svelte CLI as of 2025+ —
  successor to the deprecated `npm create svelte@latest`). Strip
  to bare minimum: SvelteKit 2.x + Svelte 5 (runes) + TS 5.7+ +
  Vite 7. No demo / hello-world routes — replace with one `+page.svelte`
  that renders "Phase 0 — Neurosymbolic CDS" plus a placeholder
  for the visualizers.
- **Bun adoption — exclusive runtime + package manager + script
  runner.** `bun install` (no `npm install` / `pnpm install`); 9.1's
  Justfile recipes shell out to `bun run <script>`. ADR-007 already
  locked bun + Vite as exclusive; 9.1 is the first place those locks
  bind in the repo. `bunfig.toml` pins the registry + telemetry off.
  No `package-lock.json`, no `pnpm-lock.yaml` — `bun.lockb` only,
  committed.
- **Tailwind 4.** `tailwindcss@^4` + `@tailwindcss/vite` plugin in
  `vite.config.ts` (Tailwind 4 ships its own Vite plugin; no
  `postcss.config.js` / `autoprefixer` needed — Tailwind 4's
  Lightning CSS engine handles vendor prefixes natively). Single
  `src/app.css` with `@import "tailwindcss";`. Utility-first per
  Plan §6 — no custom theme tokens until 9.3 needs them; expand
  inline at component time.
- **ESLint 9 + Prettier 3.** `eslint@^9` flat-config (`eslint.config.js`
  with `eslint-plugin-svelte` + `typescript-eslint`); `prettier@^3.5`
  + `prettier-plugin-svelte`. No legacy `.eslintrc.*` /
  `.prettierrc.*` JSON. The flat config is the 2025+ baseline.
- **Playwright wired but not used yet.** `@playwright/test@^1.51`
  installed, `playwright.config.ts` written, `e2e/` directory
  scaffolded with one tombstone test that asserts `1 + 1 === 2`
  (ensures the Playwright runner is wired and `bun run test:e2e`
  exits 0 without spinning up a server). Real E2E tests land in 9.3.
- **TypeScript strict.** `tsconfig.json` extends SvelteKit's defaults
  with `"strict": true`, `"noUncheckedIndexedAccess": true`,
  `"noImplicitOverride": true`. No JS files allowed under
  `frontend/src/` — `.ts` / `.svelte` only.
- **Justfile recipes (new block — `frontend-*`):**

  | Recipe                  | Role                                                                                                                  |
  | ----------------------- | --------------------------------------------------------------------------------------------------------------------- |
  | `frontend-install`      | `cd frontend && bun install --frozen-lockfile` for CI; plain `bun install` otherwise (env var gated).                  |
  | `frontend-dev`          | `cd frontend && bun run dev -- --host 127.0.0.1 --port 5173` — Vite dev server, HMR, no auto-open browser.            |
  | `frontend-build`        | `cd frontend && bun run build` — production build into `frontend/build/`.                                              |
  | `frontend-preview`      | `cd frontend && bun run preview` — serves the production build on `:4173`.                                             |
  | `frontend-lint`         | `cd frontend && bun run lint` (ESLint + Prettier `--check` chained).                                                   |
  | `frontend-format`       | `cd frontend && bun run format` (Prettier `--write`).                                                                  |
  | `frontend-typecheck`    | `cd frontend && bun run check` (`svelte-check` against the project).                                                   |
  | `frontend-test`         | `cd frontend && bun run test:unit` — vitest (deferred to 9.3 — recipe exists but routes to a tombstone in 9.1).        |
  | `frontend-e2e`          | `cd frontend && bun run test:e2e` — Playwright (tombstone in 9.1, real tests in 9.3).                                  |

  Recipes match the existing `py-*` / `rs-*` Justfile blocks for
  developer ergonomics. None depend on a Dapr cluster being up —
  the BFF only needs daprd at runtime, which 9.2 wires.

- **Gate.** `cd frontend && bun install` succeeds without warnings;
  `just frontend-build` exits 0 with a non-empty `frontend/build/`;
  `just frontend-typecheck` clean; `just frontend-lint` clean; one
  manual `just frontend-dev` smoke confirms `:5173` returns the
  placeholder page; `just frontend-test` + `just frontend-e2e`
  exit 0 against tombstones; cargo + pytest baselines unchanged
  (no Rust / Python touchpoints in 9.1); `just env-verify` clean.

### 3. 9.2 contract — TS schema mirrors + BFF + canonical smoke

- **TypeScript schema mirrors.** New module tree under
  `frontend/src/lib/schemas/`:
  - `telemetry.ts` — `ClinicalTelemetryPayload` (vitals dict +
    discrete events; lexicographic key ordering enforced by a
    `BTreeMap`-equivalent — Phase 0 uses plain `Record<string, number>`
    with a runtime sort guard at the BFF boundary because TS objects
    do not preserve insertion order on integer-string-coerced keys).
  - `onion.ts` — `OnionLIRTree` discriminated union: `Scope` +
    `Relation` + `IndicatorConstraint` + `Atom`, each carrying a
    `kind` literal narrowing tag. Source-span byte offsets are
    `{ start: number; end: number; doc_id: string }`.
  - `smt.ts` — `SmtConstraintMatrix` + `LabelledAssertion`.
  - `verdict.ts` — `Verdict` (mirrors `cds_kernel::deduce::Verdict`
    breach summary).
  - `trace.ts` — `FormalVerificationTrace` (`sat`, `muc[]`,
    `alethe_proof`).
  - `recheck.ts` — `LeanRecheckWire` (`ok`, `custom_id`,
    `lean_proof_text`, diagnostics array).
  - `pipeline.ts` — `PipelineInput` (the 8.4b Pydantic model
    cross-walked) + `PipelineEnvelope`
    `{ payload, ir, matrix, verdict, trace, recheck }`.
  - `index.ts` — barrel re-exports.
  All schemas carry a JSDoc cross-reference back to the Rust /
  Python source-of-truth file path so a future schema bump
  surfaces the cross-language coordination requirement at
  edit-time. **No `schemars` JSON-Schema export** — the open
  question from the Memory_Scratchpad ("schemars JSON-Schema export
  for the SvelteKit frontend (Task 9). Not needed until then;
  revisit when wiring the BFF.") is closed: hand-written TS mirrors
  with a tripwire test in 9.2 (`test_ts_schema_parity`) that
  decodes the cargo-emitted golden JSON fixtures
  (`crates/schemas/tests/fixtures/*.json`) through the TS
  `parse*` helpers and asserts round-trip equivalence. Rationale:
  schemars adds a Rust-side build dependency + a TS-side codegen
  step + a generated-file-in-VCS policy decision, each of which
  needs its own ADR; for six small schemas hand-mirrored TS
  with a parity tripwire is materially simpler. Reopen only when
  schema count > ~12 or when an external consumer needs the
  schema export.
- **BFF transport policy — direct service-invocation, not
  Workflow.** SvelteKit `+server.ts` BFF routes call the Phase 0
  daprd sidecars directly via `fetch` against
  `http://127.0.0.1:${process.env.DAPR_HTTP_PORT_HARNESS}/v1.0/invoke/cds-harness/method/v1/<path>`
  and the symmetric `cds-kernel` URL. No
  `DaprWorkflowClient`. Reasons:
  1. 8.4b's `cds_harness.workflow.run-pipeline` is a CLI
     orchestrator — not an HTTP endpoint that JS can call. Spinning
     a `WorkflowRuntime` from JS would require either the (immature)
     `@dapr/dapr` JS SDK with workflow extension or a long-running
     Python sidecar that exposes Workflow scheduling over HTTP;
     both add complexity that Phase 0 does not need.
  2. The UI wants per-stage round-trip latency so it can stage
     the pipeline incrementally (show ingest → AST → matrix →
     verdict → trace → recheck as each stage completes). A
     Workflow-shaped envelope returns all stages at once; direct
     invocation supports both incremental and aggregated UX.
  3. JSON-over-TCP between BFF and daprd matches constraint **C6**
     and ADR-002. The BFF is a thin proxy whose only job is to
     bridge the browser's same-origin policy and the daprd
     invocation URL.
  Phase 1+ may add a Workflow-via-`DaprWorkflowClient` route under
  `/api/pipeline/workflow` for batch / headless pipelines. Phase 0
  ships per-stage routes only.
- **BFF route shape (`frontend/src/routes/api/`):**

  | Route                      | Method | Body                                               | Returns                                 |
  | -------------------------- | ------ | -------------------------------------------------- | --------------------------------------- |
  | `/api/ingest`              | POST   | `IngestRequest` (telemetry payload + format hint)  | `ClinicalTelemetryPayload`              |
  | `/api/translate`           | POST   | `TranslateRequest` (doc_id + guideline text)       | `{ ir: OnionLIRTree, matrix: SmtConstraintMatrix }` |
  | `/api/deduce`              | POST   | `{ payload: ClinicalTelemetryPayload }`            | `Verdict`                               |
  | `/api/solve`               | POST   | `{ matrix: SmtConstraintMatrix, options? }`        | `FormalVerificationTrace`               |
  | `/api/recheck`             | POST   | `{ trace: FormalVerificationTrace, options? }`     | `LeanRecheckWire`                       |

  Each route is a thin `+server.ts` that proxies through daprd, lifts
  HTTP 422 `{error, detail}` envelopes into a typed
  `BackendError` exception, and emits a structured `console.info`
  per stage (matches the harness's `tracing` shape). Route handlers
  are typed end-to-end via the `lib/schemas` barrel.
- **BFF dependency convention — environment-driven daprd ports.**
  9.2 does **not** spin up daprd from inside the Vite dev server.
  An operator runs `just dapr-cluster-up` + `just py-service-dapr` +
  `just rs-service-dapr` (existing 8.4a recipes) before
  `just frontend-dev`; the BFF reads `$DAPR_HTTP_PORT_HARNESS` /
  `$DAPR_HTTP_PORT_KERNEL` from `process.env` at request time.
  Defaults (`3500` / `3501`) match the existing Phase 0 sidecar
  conventions when env is unset. A short README block in
  `frontend/README.md` documents the dev workflow.
- **Canonical smoke gate.** New Justfile recipe
  `frontend-bff-smoke`: brings up the cluster + both sidecars (via
  `just dapr-cluster-up` / `py-service-dapr` / `rs-service-dapr`),
  starts the SvelteKit BFF on `:5173`, drives a single canonical
  pipeline run via `curl` against the BFF (`/api/ingest` →
  `/api/translate` → `/api/deduce` → `/api/solve` →
  `/api/recheck`), asserts every stage returns 200 + the verification
  flag round-trips end-to-end (`trace.sat=false` for
  `contradictory-bound`), then `trap`-driven reverse-teardown of
  every spawned process. Mirrors the shape of `just dapr-pipeline`
  (8.4b) but exits the SvelteKit + curl path rather than the Python
  Workflow path.
- **Schema parity tripwire.** New unit test
  `frontend/src/lib/schemas/parity.test.ts` (vitest) decodes each
  `crates/schemas/tests/fixtures/*.json` golden through the TS
  parse helpers and asserts `JSON.parse(json) ≡ schema.parse(json)`
  (round-trip identity). Catches drift between Rust source-of-truth
  and TS mirrors at edit-time.
- **Gate.** `just frontend-typecheck` clean (TS strict mode passes
  with all six schemas + BFF routes); `just frontend-test` →
  parity tripwire + any unit cases pass; `just frontend-bff-smoke`
  end-to-end against a live cluster returns the canonical
  `contradictory-bound` envelope; cargo + pytest baselines
  unchanged; `just env-verify` clean. **Visualizers + Playwright
  defer to 9.3.**

### 4. 9.3 contract — visualizers + Phase 0 close-out

- **AST tree component (`frontend/src/lib/components/AstTree.svelte`).**
  Recursive Svelte 5 component (uses `<svelte:self>` or the
  runes-equivalent recursion pattern) rendering an `OnionLIRTree`
  via discriminated-union narrowing on the `kind` tag. Each node:
  - Indented box; collapsible via a `$state` signal per subtree.
  - Source-span tooltip on hover (`title` attribute or a
    Svelte-tooltip primitive — pick at component-time, no
    third-party tooltip lib).
  - When the node's `source_span.id` is in the current
    `FormalVerificationTrace.muc[]`, apply a Tailwind
    `bg-rose-100 ring-1 ring-rose-300` highlight class.
  Tree state is read-only (no edit affordances in Phase 0); the
  whole tree is a derived value of the BFF's `/api/translate`
  response.
- **Octagon visualizer (`frontend/src/lib/components/Octagon.svelte`).**
  Hand-rolled SVG component rendering 2D projections of
  `±x ±y ≤ c` constraints over a configurable pair of canonical
  vitals (selectable from a `<select>` element backed by
  `CANONICAL_VITALS`). Renders:
  - Cartesian axes with vital units labelled.
  - The feasible region as a polygon clip-path filled with
    Tailwind `fill-emerald-100 stroke-emerald-500`.
  - Each constraint as a half-plane line annotated with its
    label (matches `LabelledAssertion.label`).
  - Current telemetry sample as a marker dot (`fill-sky-600`).
  No D3 / Plotly / Chart.js — the abstract domain is geometric
  primitives over half a dozen lines, comfortably within
  hand-rolled SVG. If 9.3 hits a hard limit (e.g. >100 constraints
  per projection — extremely unlikely at Phase 0 fixture sizes),
  open a follow-up ADR before reaching for a viz library.
- **MUC viewer (`frontend/src/lib/components/MucViewer.svelte`).**
  Lists each MUC entry by `source_span` with a click handler that
  scrolls the AST tree to the matching node and pulses its
  highlight. Cross-component state via a small `$state` store in
  `frontend/src/lib/stores/highlight.ts` (one writable rune holding
  the current highlighted span id; AST tree subscribes to it).
- **Verification trace banner
  (`frontend/src/lib/components/VerificationTrace.svelte`).**
  Top-of-page banner: green `sat` / red `unsat` pill + Lean
  recheck status pill (`ok` green / `error` red) + a collapsible
  Alethe proof preview (first 50 lines, scroll for more — uses a
  monospaced `<pre>` block under a `details/summary` widget).
- **Single-page route (`frontend/src/routes/+page.svelte`).**
  Replaces the 9.1 placeholder. Composition order top-to-bottom:
  guideline + telemetry input form → "Run pipeline" button (drives
  `/api/ingest` → `/api/translate` → `/api/deduce` → `/api/solve`
  → `/api/recheck` in sequence, surfacing per-stage errors inline)
  → verification trace banner → AST tree (left column) | Octagon
  (right column) | MUC viewer (bottom row). Pure single-page;
  no SvelteKit form actions in 9.3 (reserved for Phase 1's
  multi-payload comparison view).
- **Playwright E2E smoke (`frontend/e2e/pipeline.e2e.ts`).**
  Drives the canonical `contradictory-bound` flow end-to-end:
  navigate to `/`, submit the form with the canonical payload +
  guideline, wait for the verification banner to settle to
  "unsat", assert the MUC viewer shows two entries, assert the AST
  tree highlights both atoms with `bg-rose-100`, assert the
  verification trace banner shows "Lean recheck ✓". Gate:
  `just frontend-e2e` against a live `dapr-cluster-up` +
  `py-service-dapr` + `rs-service-dapr` + `frontend-preview`
  (production build, not dev — closer to deploy parity).
- **Phase 0 → Phase 1 marker flip.** Bump
  `cds_harness.__init__.PHASE = 0` → `1` and `cds_kernel::PHASE: u8 = 0`
  → `1`. Update the docstring on each constant to reflect "Phase 1
  scope: live FHIR streaming, distributed cloud, ZKSMT" per
  Plan §1. The flip is a one-line edit on each side; the
  micro-decision (Plan §10 step 7) lands in 9.3 because that is
  when Phase 0's success criterion (Plan §8 row 9: "UI shows live
  trace from real dataset; verification flag round-trips") is
  actually demonstrable end-to-end.
- **README touch-up.** Add a "Running Phase 0 end-to-end" section
  to the human-facing `README.md` that points at
  `just frontend-bff-smoke` (9.2) and the visualizer demo URL
  (9.3). One-paragraph close-out — comprehensive docs land in
  Phase 1 once the API surface is durable.
- **Gate.** `just frontend-test` clean (vitest + parity tripwire);
  `just frontend-e2e` green against a live cluster; `just
  frontend-build` clean; cargo + pytest baselines unchanged
  (no kernel / harness touchpoints in 9.3 except the PHASE
  constant flip — which adds zero tests but the existing
  `tests::phase_marker_is_phase_zero` cases in
  `python/tests/test_smoke.py` + `crates/kernel/src/lib.rs`
  flip alongside, so cargo test + pytest both still pass);
  `just env-verify` clean. **Phase 0 closes here.**

### 5. Locked toolchain decisions

Locking the JS/TS stack pins versions at the floor; bun resolves
upper bounds at install time:

| Layer                  | Floor            | Rationale                                                                                                                                                    |
| ---------------------- | ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Bun runtime            | 1.3.x            | Already in `just env-verify`. ADR-007 lock; exclusive pkg manager + script runner.                                                                            |
| SvelteKit              | 2.x              | Current major (Svelte 5 runes are stable; SvelteKit 2 is the matching framework major).                                                                       |
| Svelte                 | 5.x              | Runes API for fine-grained reactivity; succeeds Svelte 4's `$:` reactive declarations.                                                                        |
| Vite                   | 7.x              | Current major; default for `sv create`.                                                                                                                       |
| TypeScript             | 5.7+             | `noUncheckedIndexedAccess` strict-mode + decorators stable.                                                                                                   |
| Tailwind CSS           | 4.x              | `@tailwindcss/vite` plugin replaces `tailwindcss/postcss` chain; Lightning CSS engine; current major.                                                         |
| ESLint                 | 9.x              | Flat config (`eslint.config.js`); legacy `.eslintrc.*` is unsupported as of 9.0.                                                                              |
| Prettier               | 3.x              | + `prettier-plugin-svelte` 3.x for Svelte 5 syntax.                                                                                                            |
| Playwright             | 1.51+            | Current; SvelteKit's recommended E2E runner.                                                                                                                  |
| Vitest                 | 3.x              | Bundled with SvelteKit's `sv create` scaffold; runs unit tests including the schema parity tripwire.                                                          |

No D3, Plotly, Chart.js, ECharts, svelte-flow, vis-network,
react-flow, cytoscape, mermaid, or any node-graph viz library is
introduced in 9.1–9.3. Phase 0's visualizers are simple enough to
hand-roll; introducing a viz library would inflate `package.json`
by megabytes for no Phase 0 benefit. Reopen the decision in Phase 1
if the Octagon component's projection count or the AST node count
exceeds what's tractable with raw SVG.

### 6. Visualizer library policy — hand-rolled SVG + Svelte 5 reactivity

For each visualizer (AST tree, Octagon, MUC viewer, verification
trace), the implementation is hand-rolled Svelte 5 components using
the standard browser SVG / HTML primitives + Tailwind utilities + a
small store for cross-component highlight state. No external
visualization dependency. The trade-off:

- **Pro.** Zero added dependencies; full control over rendering
  semantics (e.g. MUC highlight pulse animation matches the AST
  tree's collapse / expand pattern); aligns with constraint **C6**
  (JSON-over-TCP / MCP only — no FFI / WASM viz blob); simpler
  build pipeline (Vite + SvelteKit + Tailwind only); smaller
  production bundle.
- **Con.** Hand-rolling layout (especially for the Octagon's
  half-plane intersection polygon) requires per-component geometry
  code. The trade is favourable at Phase 0 scale (≤ 50 AST nodes,
  ≤ 10 octagon constraints per projection, ≤ 10 MUC entries) and
  unfavourable at scale where layout libraries pay for themselves.
  Phase 0 sits inside the favourable regime.

If 9.3 hits a hard wall (e.g. AST trees of size O(1000) — extremely
unlikely at Phase 0 fixture sizes), the contingency is a
follow-up ADR introducing one viz library at a time. The default
remains hand-rolled.

### 7. BFF transport policy — direct service-invocation, Workflow deferred

Codified in §3 above. The BFF speaks JSON-over-TCP through daprd
service-invocation directly to `cds-harness` and `cds-kernel`. The
Workflow runtime stays headless (CLI-only, as 8.4b shipped).
Reopening this is a Phase 1 micro-decision — likely driven by a
need for batch / cron-driven pipeline runs that the headless
`python -m cds_harness.workflow run-pipeline` already covers
without UI involvement.

### 8. Schema-mirror policy — hand-written TS, parity tripwire over codegen

Six TypeScript schema modules under `frontend/src/lib/schemas/`,
hand-mirrored from the Rust source-of-truth in
`crates/schemas/src/`. A vitest tripwire (`parity.test.ts`)
round-trips every cargo-emitted golden JSON fixture through the
TS parse helpers; a schema-shape drift on either side fails the
test. **No `schemars` JSON-Schema export, no codegen step.**
Reopen when schema count > ~12 or when an external consumer needs
the schema export. Phase 0's six schemas + the aggregated envelope
are well below that floor.

### 9. PHASE marker semantics

`cds_harness.__init__.PHASE` and `cds_kernel::PHASE` flip 0 → 1
**at the close of Task 9.3**, when the UI visibly demonstrates the
Phase 0 success criterion. The flip is part of 9.3's gate, not
9.1's or 9.2's. ADR-021 §3 documented this same intent for 8.4b but
deferred to Task 9 because the Workflow harness alone — without a
UI — does not yet meet Plan §1's "Phase 0 = headless engine +
stakeholder visualizer" definition. 9.3 closes the gap.

### 10. Further-split contingency

If 9.3 repeats the context-window pattern (visualizers + Playwright
+ Phase 0 close-out exceeds one session), pull in a mid-flight
4-way split:

- **9.3a** — AST tree component + MUC viewer + cross-component
  highlight store + per-component vitest cases.
- **9.3b** — Octagon visualizer + verification trace banner +
  single-page composition + Playwright E2E + Phase 0 → 1 PHASE
  flip + Task 9 (and Phase 0) close-out.

This contingency is **not** triggered at split-time; it is the same
pattern that surfaced for 8.3 → 8.3b → 8.3b1+8.3b2 (each split
mid-flight once the inheriting session encountered the budget
ceiling). Enumerated here so a future session does not have to
re-derive the boundary.

**Consequences.** Task 9.1 inherits a clean slate (no existing
TS/JS code in the repo) and delivers a green-field SvelteKit
scaffold + Justfile recipe set + tombstone Playwright + Tailwind 4
setup. Task 9.2 inherits the scaffold + recipes and delivers the
six TS schema mirrors + the BFF route shape + the canonical smoke
against a live cluster, closing the wire-contract boundary
between frontend and the Phase 0 backend. Task 9.3 inherits the
full schema + transport + smoke harness and delivers the four
Svelte 5 visualizer components + Playwright + the PHASE flip,
closing **Phase 0** end-to-end. Each session's gate is
self-contained within its own scope axis; cargo + pytest baselines
stay green throughout (Rust + Python tree untouched until the 9.3
PHASE flip).

**Alternatives rejected.**

- **Single Task 9 session, accept the context overflow.** Has
  failed at this scale six times now (ADRs 016, 018, 019, 020,
  021). The cost of another mid-session context exhaustion is
  far higher than the cost of one ADR + plan-row split.
- **Two-way split (9.1 scaffold+types / 9.2 visualizers+close-out).**
  Forces the BFF + canonical smoke into one of the two halves;
  doubles that half's scope. Three-way split aligns with the
  three actual scope axes.
- **Four-way split up-front (9.1 / 9.2 / 9.3a / 9.3b).** Each
  visualizer pair is small enough that a single session can
  plausibly carry all four components + Playwright + the close-out.
  Pre-emptive split adds session overhead; the contingency in §10
  pulls it in only if needed.
- **`schemars` JSON-Schema export + TS codegen pipeline.** Adds a
  Rust-side build dependency, a TS-side codegen step, a
  generated-files-in-VCS policy, and a coupling between cargo
  test and frontend test. Six small hand-written schemas with a
  parity tripwire delivers the same drift-detection at materially
  lower complexity. Reopen at >~12 schemas.
- **D3.js / Plotly / Chart.js / svelte-flow for visualizers.**
  Megabytes of bundle weight for a Phase 0 prototype that has ≤ 50
  AST nodes, ≤ 10 octagon constraints, ≤ 10 MUC entries. Hand-rolled
  SVG is the right call at this scale. §6 documents the contingency.
- **BFF via Workflow-via-`DaprWorkflowClient` instead of direct
  service-invocation.** §3 enumerated three reasons against:
  (a) Workflow is a CLI orchestrator, not an HTTP endpoint;
  (b) UI wants per-stage round-trip latency for incremental
  staging; (c) JSON-over-TCP through daprd matches constraint **C6**.
- **BFF embedded inside a Python service instead of SvelteKit
  `+server.ts`.** Adds a sixth Phase 0 process to manage; SvelteKit
  already runs an HTTP server in dev/preview mode; proxying through
  a Python service would double-hop every request for no benefit.
- **Skip the canonical BFF smoke in 9.2.** Would let 9.3 inherit
  an unverified BFF + types contract; failure modes that surface
  in 9.3 (e.g. a TS schema typo that decodes a real envelope
  incorrectly) would conflate visualizer bugs with contract bugs.
  The canonical smoke isolates the contract gate to 9.2.
- **Skip the schema parity tripwire.** Hand-written mirrors drift
  silently from the Rust source-of-truth; the tripwire is the
  cheap continuous check that catches drift at edit-time. Cost is
  one vitest module + one fixture per schema.
- **Defer the PHASE 0 → 1 flip to Phase 1 setup.** Plan §10 step 7
  schedules it on Task 9 close-out. Deferring would leave the
  marker stale across the Phase 1 migration window; flipping at
  9.3 close keeps the marker semantically aligned with what is
  actually demonstrable.

---
