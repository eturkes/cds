# Memory Scratchpad

> Ephemeral working memory between sessions. Append at top; prune aggressively. Authoritative state lives in `Plan.md` + `Architecture_Decision_Log.md`.

---

## Active task pointer

- **Last completed:** Task 2 — Core conceptual schemas (Rust + Pydantic v2) (2026-04-29).
- **Next up:** Task 3 — Live genuine data ingestion (local CSV/JSON parser → Python harness → `ClinicalTelemetryPayload`).

## Session 2026-04-29 — Task 2 close-out

Authored the four canonical wire-format schemas in Rust + Python with byte-stable JSON round-trip:

| Schema                       | Rust file                                          | Python file                                       |
| ---------------------------- | -------------------------------------------------- | ------------------------------------------------- |
| `ClinicalTelemetryPayload`   | `crates/kernel/src/schema/telemetry.rs`            | `python/cds_harness/schema/telemetry.py`          |
| `OnionLIRTree`               | `crates/kernel/src/schema/onionl.rs`               | `python/cds_harness/schema/onionl.py`             |
| `SmtConstraintMatrix`        | `crates/kernel/src/schema/smt.rs`                  | `python/cds_harness/schema/smt.py`                |
| `FormalVerificationTrace`    | `crates/kernel/src/schema/verification.rs`         | `python/cds_harness/schema/verification.py`       |

Cross-language fixtures live in `tests/golden/*.json` and are loaded by both
`crates/kernel/tests/golden_roundtrip.rs` (5 tests) and
`python/tests/test_schema_roundtrip.py` (9 tests).

Final gate (all green):
- `cargo test --workspace` → 18 pass (13 lib + 5 integration)
- `cargo clippy --workspace --all-targets -- -D warnings` → clean
- `uv run ruff check .` → clean
- `uv run pytest` → 12 pass (3 smoke + 9 schema)

`SCHEMA_VERSION = "0.1.0"` is published from both
`cds_kernel::schema::SCHEMA_VERSION` and `cds_harness.schema.SCHEMA_VERSION`;
they MUST move together. Decisions captured in **ADR-010**.

## Open notes for Task 3

- Source data format: locked as local CSV/JSON in `data/` (constraint C1).
  No HTTP fetchers, no FHIR live streaming in Phase 0.
- Ingestion pipeline target: produce a stream of `TelemetrySample` rows
  yielding a `ClinicalTelemetryPayload` envelope per source.
- Decide ingestion duplicate policy: **rejected** if `monotonic_ns` repeats
  within a single payload (as documented in `telemetry.rs`). Implement as
  a hard error on parse, surfaced through Python ingestion CLI.
- Vitals key normalization: pick a canonical lower-snake-case namespace
  (e.g. `heart_rate_bpm`, `spo2_percent`, `systolic_mmhg`,
  `diastolic_mmhg`, `temp_celsius`, `respiratory_rate_bpm`). Reject
  unknown columns or coerce them to a `data` blob inside `DiscreteEvent`.
- Wall-clock validation: ingestion must reject non-RFC-3339 / non-UTC
  timestamps. Use Python `datetime.fromisoformat` + an explicit `Z`
  suffix check; emit canonical microsecond UTC strings.
- File enumeration: a `data/manifest.toml` catalog vs. directory-walk?
  Lean toward directory-walk over `data/` (simpler, no extra index file).
- Test fixture: ship a tiny `data/sample/icu-monitor-01.csv` (~10 rows)
  so the ingestion test can hit a real file.

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
  task once Task 3+ stabilizes — non-blocking warning today.
- `schemars` JSON-Schema export for the SvelteKit frontend (Task 9). Not
  needed until then; revisit when wiring the BFF.

## Hazards / known caveats

- **Wire format is now load-bearing.** Any change to a schema field or to
  the `kind` discriminator value MUST bump `SCHEMA_VERSION` in both Rust
  and Python and update the golden fixtures. Both languages re-run the
  goldens in CI, so a divergence will fail the build.
- **Subprocess hygiene** is non-negotiable (ADR-004). Any new
  `Command::spawn` site MUST go through the warden and carry
  `.kill_on_drop(true)` + timeout. Reject PRs that bypass.
- **C6 (JSON-over-TCP / MCP only)** — when adding any new IPC, double-check;
  gRPC / shared-mem / FFI across services are forbidden.
- **C5 (one atomic task per session)** — under no circumstance pre-emptively
  start the *next* task. Update memory + commit + terminate.

## Re-Entry Prompt (verbatim copy — see `Plan.md §9`)

> "Initialize session. Execute the Environment Verification Protocol, utilizing `sudo` if necessary. Ingest the persistent memory files located within the `.agent/` directory and evaluate the active plan checklist. Select STRICTLY the single next uncompleted atomic task from the plan. Execute exclusively that specific micro-task utilizing the defined 2026 stack and architectural constraints. Implement absolute resource cleanup and thread-safe operations. Update the `.agent/` memory files to reflect task progress. Flush all updates to disk, execute `git add .` and `git commit -m 'feat: complete [Task Name]'`, and formally terminate this session immediately to preserve the context window for the subsequent task."
