# Memory Scratchpad

> Ephemeral working memory between sessions. Append at top; prune aggressively. Authoritative state lives in `Plan.md` + `Architecture_Decision_Log.md`.

---

## Active task pointer

- **Last completed:** Task 1 — Foundational scaffolding & env provisioning (2026-04-29).
- **Next up:** Task 2 — Core conceptual schemas (Rust structs + Pydantic v2 models for the 4 schemas).

## Session 2026-04-29 — Task 1 close-out

Verified host toolchain (Debian 13 trixie, kernel 6.19.12-1-default):

| Tool   | Version           | Path                                     |
| ------ | ----------------- | ---------------------------------------- |
| uv     | 0.11.8            | `~/.local/bin/uv`                         |
| cargo  | 1.95.0            | `~/.cargo/bin/cargo` (Edition 2024 ✅)    |
| rustc  | 1.95.0            | `~/.cargo/bin/rustc`                      |
| bun    | 1.3.13            | `~/.bun/bin/bun`                          |
| just   | 1.50.0            | `~/.cargo/bin/just`                       |
| git    | 2.47.3            | `/usr/bin/git`                            |
| curl   | 8.14.1            | `/usr/bin/curl`                           |

`$PATH` already wires `~/.local/bin`, `~/.cargo/bin`, `~/.bun/bin`. No `sudo` was needed for Task 1.

Files written:
- `.gitignore`, `LICENSE` (Apache 2.0 + LLVM exceptions), `README.md`
- `.agent/{Plan.md,Architecture_Decision_Log.md,Memory_Scratchpad.md}`
- `Justfile` (env-verify, bootstrap, fetch-bins, lint, test, run, clean)
- `Cargo.toml` (workspace), `crates/kernel/{Cargo.toml, src/lib.rs}` (placeholder)
- `pyproject.toml` (uv + ruff), `ruff.toml`, `python/cds_harness/__init__.py` (placeholder)
- `rust-toolchain.toml`, `.editorconfig`
- `.bin/.gitkeep`, `frontend/.gitkeep`, `tests/.gitkeep`, `data/.gitkeep`, `proofs/.gitkeep`

## Open notes for Task 2

- Pydantic v2 is the locked Python schema lib (validate at v2 syntax: `model_config = ConfigDict(...)`, `Field(...)`, discriminated unions for `OnionL_IR_Tree` variants).
- Rust schema lib: `serde` + `serde_json` for round-trip; consider `schemars` for JSON-Schema export so the SvelteKit frontend can typecheck the wire payload.
- `OnionL_IR_Tree` JSON schema must be **identical** between Rust and Python — author once (e.g., as a JSON Schema) and code-gen / hand-mirror with golden round-trip tests.
- `source_span` field on `Atom` is mandatory (constraint C4 — MUC traceback). Spec it with `{ start: usize, end: usize, doc_id: str }`.
- Time fields on `ClinicalTelemetryPayload`: ISO-8601 UTC for wall clock + `monotonic_ns: u64` for ordering. Decide if duplicate sample timestamps are coalesced or rejected.

## Open questions deferred

- HNN MUC heuristic — pretrained weights or train at provision time? Defer to Task 6.
- Kimina headless server packaging on Linux — official binary release vs build-from-source? Defer to Task 7; check `just fetch-bins` recipe shape closer to deadline.
- Dapr local-mode topology — single placement service per dev box? Defer to Task 8.

## Hazards / known caveats

- **Subprocess hygiene** is non-negotiable (ADR-004). Any new `Command::spawn` site MUST go through the warden and carry `.kill_on_drop(true)` + timeout. Reject PRs that bypass.
- **C6 (JSON-over-TCP / MCP only)** — when adding any new IPC, double-check; gRPC / shared-mem / FFI across services are forbidden.
- **C5 (one atomic task per session)** — under no circumstance pre-emptively start the *next* task. Update memory + commit + terminate.

## Re-Entry Prompt (verbatim copy — see `Plan.md §9`)

> "Initialize session. Execute the Environment Verification Protocol, utilizing `sudo` if necessary. Ingest the persistent memory files located within the `.agent/` directory and evaluate the active plan checklist. Select STRICTLY the single next uncompleted atomic task from the plan. Execute exclusively that specific micro-task utilizing the defined 2026 stack and architectural constraints. Implement absolute resource cleanup and thread-safe operations. Update the `.agent/` memory files to reflect task progress. Flush all updates to disk, execute `git add .` and `git commit -m 'feat: complete [Task Name]'`, and formally terminate this session immediately to preserve the context window for the subsequent task."
