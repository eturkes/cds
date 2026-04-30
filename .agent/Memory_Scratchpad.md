# Memory Scratchpad

> Ephemeral working memory between sessions. Append at top; prune aggressively. Authoritative state lives in `Plan.md` + `Architecture_Decision_Log.md`.

---

## Active task pointer

- **Last completed:** Task 7 — Headless Lean 4 interop (Kimina REST bridge: `cds_kernel::lean::recheck` ships a self-contained Lean snippet that probes the cvc5-emitted Alethe S-expression through `POST /verify`) (2026-04-30).
- **Next up:** Task 8 — Dapr workflow orchestration (sidecar boundaries Rust↔Python↔solvers; end-to-end pipeline runs under Dapr; logs traceable per stage).

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
