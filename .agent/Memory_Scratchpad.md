# Memory Scratchpad

> Ephemeral working memory between sessions. Append at top; prune aggressively. Authoritative state lives in `Plan.md` + `Architecture_Decision_Log.md`.

---

## Active task pointer

- **Last completed:** Task 3 — Live genuine data ingestion (CSV+sidecar / JSON envelope → `ClinicalTelemetryPayload`) (2026-04-29).
- **Next up:** Task 4 — Python neurosymbolic translators (CLOVER text → OnionL AST → SMT-LIB).

## Session 2026-04-29 — Task 3 close-out

Shipped a Python-only ingestion package that turns local files in `data/`
into validated `ClinicalTelemetryPayload` envelopes. Constraint **C1** is
honored: no HTTP, no FHIR streaming.

**Module layout (`python/cds_harness/ingest/`):**

| File             | Role                                                                              |
| ---------------- | --------------------------------------------------------------------------------- |
| `__init__.py`    | Public re-exports (loaders, errors, helpers, `CANONICAL_VITALS`).                 |
| `__main__.py`    | `python -m cds_harness.ingest` shim.                                              |
| `canonical.py`   | `CANONICAL_VITALS` frozenset (6 lower-snake-case keys).                           |
| `errors.py`      | `IngestError` hierarchy (Duplicate / Invalid / Malformed / Missing / Unknown).    |
| `timestamps.py`  | Strict RFC-3339-Z parse + canonicalize-to-microsecond.                            |
| `validation.py`  | `assert_unique_monotonic`, `assert_canonical_vitals`.                             |
| `csv_loader.py`  | CSV (+ `<stem>.meta.json` sidecar) → payload; bisect-bucketed events.             |
| `json_loader.py` | Whole-payload envelope → re-canonicalized payload; same boundary policies.        |
| `loader.py`      | Directory walk dispatcher; skips sidecar `*.meta.json`.                           |
| `cli.py`         | argparse CLI; emits JSON array, exits 0/1/2.                                      |

**Sample data (`data/sample/`):**
- `icu-monitor-01.csv` (10 rows) + `icu-monitor-01.meta.json` (sidecar).
- `icu-monitor-02.json` (whole envelope).
- `data/sample/README.md` documents adding new samples.

**Tests:** `python/tests/test_ingest.py` — 25 cases:
canonical-namespace shape, timestamp validators (pad / preserve / reject
offset / reject naive / non-string), CSV happy path + 8 boundary errors,
JSON happy path + 3 boundary errors, dispatcher walk + missing-path, CLI
write + missing-path exit code.

**Justfile wiring:** `py-ingest` recipe (overridable `DATA_PATH`);
`run-harness` now aliases to `py-ingest`.

Final gate (all green):
- `uv run pytest` → **37 pass** (3 smoke + 9 schema + 25 ingest).
- `uv run ruff check .` → clean.
- `cargo test --workspace` → **18 pass** (no Rust changes — sanity).
- `cargo clippy --workspace --all-targets -- -D warnings` → clean.
- `just py-ingest` → 2 payloads, lexicographic vital ordering verified.

Decisions captured in **ADR-011**.

## Open notes for Task 4

- Translator entrypoint: `cds_harness.translate.clover` (or similar). Read
  `data/guidelines/*.md` (or `*.txt`) → CLOVER pipeline → `OnionLIRTree`
  JSON → SMT-LIBv2 string. Must round-trip through Z3 `(check-sat)` for
  the gate.
- CLOVER + NL2LOGIC are **LLM-touched** stages — keep all LLM calls
  behind a thin adapter so deterministic test fixtures can swap the
  network call out for a recorded transcript.
- Source-span fidelity: every `Atom` produced by the translator MUST
  carry a `SourceSpan` referencing byte offsets into the original
  guideline text. ADR-005 is the contract; the schema enforces it (no
  `Atom` validates without a `SourceSpan`).
- The translator is the first place we'll need an LLM client. Pick the
  client library (e.g. `anthropic` SDK) at the start of Task 4 and pin
  the version; budget for prompt-cache friendliness (long static
  preamble + dynamic guideline tail).
- Author 1-2 toy guideline fixtures under `data/guidelines/` so the
  translator integration test has a real input — same C1 spirit as the
  ingestion sample dataset.
- Ship at least one negative-path SMT test (a guideline that intentionally
  produces an `unsat`) to prepare the wiring for Task 6 (MUC extraction).

## Open notes carried forward

- Source data format for ingestion: **CSV + sidecar JSON OR whole-envelope
  JSON.** Anything else is rejected. New canonical vital → coordinated edit
  of `CANONICAL_VITALS` + golden fixtures + downstream rules.
- Vitals dict ordering on the wire is **lexicographic** (matches Rust
  `BTreeMap`). The CSV loader sorts keys before constructing the sample;
  any new ingestion path MUST do the same.
- Wall-clock canonical form: `YYYY-MM-DDTHH:MM:SS.ffffffZ` (six microsecond
  digits, literal `Z`). Inputs without fractional seconds are zero-padded.
- Duplicate `monotonic_ns` is a hard ingestion error — surfaced as
  `DuplicateMonotonicError` (subclass of `IngestError` → `ValueError`).

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
  task once Task 4+ stabilizes — non-blocking warning today.
- `schemars` JSON-Schema export for the SvelteKit frontend (Task 9). Not
  needed until then; revisit when wiring the BFF.
- `cds-ingest` console script (`[project.scripts]`) — currently invoked via
  `python -m cds_harness.ingest`. Add a thin `cds-ingest` entrypoint when a
  packaged distribution is needed.

## Hazards / known caveats

- **Wire format is load-bearing.** Any change to a schema field, the
  `kind` discriminator, OR the ingestion canonical-vital allowlist MUST
  bump `SCHEMA_VERSION` in both Rust and Python and update goldens.
- **`CANONICAL_VITALS` is part of the boundary contract.** Adding a key
  is a coordinated edit across translator (Task 4), deductive engine
  (Task 5), and SMT integration (Task 6). Treat as ADR-grade.
- **Subprocess hygiene** is non-negotiable (ADR-004). Any new
  `Command::spawn` site MUST go through the warden and carry
  `.kill_on_drop(true)` + timeout. Reject PRs that bypass.
- **C6 (JSON-over-TCP / MCP only)** — when adding any new IPC, double-check;
  gRPC / shared-mem / FFI across services are forbidden.
- **C5 (one atomic task per session)** — under no circumstance pre-emptively
  start the *next* task. Update memory + commit + terminate.

## Re-Entry Prompt (verbatim copy — see `Plan.md §9`)

> "Initialize session. Execute the Environment Verification Protocol, utilizing `sudo` if necessary. Ingest the persistent memory files located within the `.agent/` directory and evaluate the active plan checklist. Select STRICTLY the single next uncompleted atomic task from the plan. Execute exclusively that specific micro-task utilizing the defined 2026 stack and architectural constraints. Implement absolute resource cleanup and thread-safe operations. Update the `.agent/` memory files to reflect task progress. Flush all updates to disk, execute `git add .` and `git commit -m 'feat: complete [Task Name]'`, and formally terminate this session immediately to preserve the context window for the subsequent task."
