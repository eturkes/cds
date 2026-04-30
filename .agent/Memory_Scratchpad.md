# Memory Scratchpad

> Ephemeral working memory between sessions. Append at top; prune aggressively. Authoritative state lives in `Plan.md` + `Architecture_Decision_Log.md`.

---

## Active task pointer

- **Last completed:** Task 5 — Rust deductive engine (ascent Datalog + Octagon abstract domain over canonical vitals) (2026-04-30).
- **Next up:** Task 6 — Mathematical solver integration (Z3/cvc5, MUC extraction, Alethe proof emission).

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
