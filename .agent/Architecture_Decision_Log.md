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
