# =============================================================================
# Neurosymbolic CDS — Polyglot Task Runner (Phase 0)
# =============================================================================
# Unified entrypoint for Rust + Python (uv) + TypeScript (bun) + external
# solver binaries (cvc5, Z3, Lean 4) staged under .bin/.
#
# Discover everything: `just --list`
# =============================================================================

set shell := ["bash", "-eu", "-o", "pipefail", "-c"]
set dotenv-load := false
set positional-arguments := true

# Project-local binaries (.bin/) take precedence on PATH for every recipe.
export PATH := justfile_directory() / ".bin:" + env_var_or_default('PATH', '')

# Pinned external binary releases (override per-invocation: `just Z3_VERSION=4.13.4 fetch-z3`)
Z3_VERSION   := env_var_or_default('Z3_VERSION',   'latest')
CVC5_VERSION := env_var_or_default('CVC5_VERSION', 'latest')
LEAN_VERSION := env_var_or_default('LEAN_VERSION', 'stable')

# -----------------------------------------------------------------------------
# Default recipe — list everything
# -----------------------------------------------------------------------------
default:
    @just --list --unsorted

# =============================================================================
# Environment verification
# =============================================================================

# Audit host toolchain + .bin/ wiring. Exits non-zero on missing required tools.
env-verify:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "::: CDS Phase 0 environment verification :::"
    fail=0
    check() {
      local name="$1"; shift
      if command -v "$name" >/dev/null 2>&1; then
        printf "  ✓ %-7s %s\n" "$name" "$("$@" 2>&1 | head -1)"
      else
        printf "  ✗ %-7s MISSING\n" "$name"; fail=1
      fi
    }
    check uv     uv --version
    check cargo  cargo --version
    check rustc  rustc --version
    check bun    bun --version
    check just   just --version
    check git    git --version
    check curl   curl --version
    echo "  PATH-prefixed .bin/ = {{ justfile_directory() }}/.bin"
    if [ -d "{{ justfile_directory() }}/.bin" ] && \
       find "{{ justfile_directory() }}/.bin" -mindepth 1 -not -name '.gitkeep' | grep -q .; then
        echo "  .bin/ populated"
    else
        echo "  .bin/ empty (run: just fetch-bins)"
    fi
    [ "$fail" = "0" ] || { echo "Required tooling missing — see above."; exit 1; }
    echo "✓ environment verified"

# =============================================================================
# Bootstrap — full provisioning for a fresh checkout
# =============================================================================

# Verify env, sync Python venv, prefetch Rust deps, fetch external solver binaries.
bootstrap: env-verify py-sync rs-fetch fetch-bins
    @echo "✓ bootstrap complete"

# =============================================================================
# External solver binary fetcher (Z3, cvc5, Lean 4) → .bin/
# =============================================================================

fetch-bins: fetch-z3 fetch-cvc5 fetch-lean
    @echo "✓ external solver binaries staged under .bin/"

# Stage the Z3 SMT solver into .bin/z3 (skips if already present).
fetch-z3:
    #!/usr/bin/env bash
    set -euo pipefail
    mkdir -p "{{ justfile_directory() }}/.bin"
    if [ -x "{{ justfile_directory() }}/.bin/z3" ]; then
        echo "z3 already present in .bin/"
        exit 0
    fi
    echo "→ fetching Z3 ({{Z3_VERSION}})"
    if [ "{{Z3_VERSION}}" = "latest" ]; then
        url=$(curl -sL "https://api.github.com/repos/Z3Prover/z3/releases/latest" \
            | grep -oE '"browser_download_url": "[^"]+x64-glibc[^"]+\.zip"' \
            | head -1 | sed 's/.*"\(https.*\)".*/\1/')
    else
        url=$(curl -sL "https://api.github.com/repos/Z3Prover/z3/releases/tags/z3-{{Z3_VERSION}}" \
            | grep -oE '"browser_download_url": "[^"]+x64-glibc[^"]+\.zip"' \
            | head -1 | sed 's/.*"\(https.*\)".*/\1/')
    fi
    [ -n "${url:-}" ] || { echo "could not resolve Z3 download URL"; exit 1; }
    tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
    curl -fsSL "$url" -o "$tmp/z3.zip"
    (cd "$tmp" && unzip -q z3.zip)
    cp "$tmp"/*/bin/z3 "{{ justfile_directory() }}/.bin/z3"
    chmod +x "{{ justfile_directory() }}/.bin/z3"
    "{{ justfile_directory() }}/.bin/z3" --version

# Stage the cvc5 SMT solver into .bin/cvc5 (skips if already present).
fetch-cvc5:
    #!/usr/bin/env bash
    set -euo pipefail
    mkdir -p "{{ justfile_directory() }}/.bin"
    if [ -x "{{ justfile_directory() }}/.bin/cvc5" ]; then
        echo "cvc5 already present in .bin/"
        exit 0
    fi
    echo "→ fetching cvc5 ({{CVC5_VERSION}})"
    if [ "{{CVC5_VERSION}}" = "latest" ]; then
        api_url="https://api.github.com/repos/cvc5/cvc5/releases/latest"
    else
        api_url="https://api.github.com/repos/cvc5/cvc5/releases/tags/cvc5-{{CVC5_VERSION}}"
    fi
    url=$(curl -sL "$api_url" \
        | grep -oE '"browser_download_url": "[^"]+Linux-x86_64-static[^"]*"' \
        | grep -v '\.asc' | head -1 | sed 's/.*"\(https.*\)".*/\1/')
    [ -n "${url:-}" ] || { echo "could not resolve cvc5 download URL"; exit 1; }
    tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
    case "$url" in
        *.zip)     curl -fsSL "$url" -o "$tmp/cvc5.zip" && (cd "$tmp" && unzip -q cvc5.zip) ;;
        *.tar.gz)  curl -fsSL "$url" -o "$tmp/cvc5.tgz" && (cd "$tmp" && tar -xzf cvc5.tgz) ;;
        *)         curl -fsSL "$url" -o "$tmp/cvc5.bin" ;;
    esac
    if [ -f "$tmp/cvc5.bin" ]; then
        cp "$tmp/cvc5.bin" "{{ justfile_directory() }}/.bin/cvc5"
    else
        bin_path=$(find "$tmp" -type f \( -name cvc5 -o -name 'cvc5*' \) -perm -u+x | head -1)
        [ -n "$bin_path" ] || bin_path=$(find "$tmp" -type f -name cvc5 | head -1)
        cp "$bin_path" "{{ justfile_directory() }}/.bin/cvc5"
    fi
    chmod +x "{{ justfile_directory() }}/.bin/cvc5"
    "{{ justfile_directory() }}/.bin/cvc5" --version | head -1

# Stage Lean 4 toolchain (via elan) into .bin/lean and .bin/lake (skips if present).
fetch-lean:
    #!/usr/bin/env bash
    set -euo pipefail
    mkdir -p "{{ justfile_directory() }}/.bin"
    if [ -x "{{ justfile_directory() }}/.bin/lean" ]; then
        echo "lean already present in .bin/"
        exit 0
    fi
    echo "→ provisioning Lean 4 toolchain via elan ({{LEAN_VERSION}})"
    export ELAN_HOME="{{ justfile_directory() }}/.bin/.elan"
    export CARGO_HOME="$ELAN_HOME"  # keep elan from polluting ~/.cargo
    curl -fsSL "https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh" \
        | bash -s -- -y --no-modify-path --default-toolchain {{LEAN_VERSION}}
    ln -sf "$ELAN_HOME/bin/lean" "{{ justfile_directory() }}/.bin/lean"
    ln -sf "$ELAN_HOME/bin/lake" "{{ justfile_directory() }}/.bin/lake"
    "{{ justfile_directory() }}/.bin/lean" --version

# =============================================================================
# Python (uv + ruff + pytest)
# =============================================================================

py-sync:
    uv sync --all-extras

py-lint:
    uv run ruff check .

py-format:
    uv run ruff format .
    uv run ruff check --fix .

py-test:
    uv run pytest

py-typecheck:
    @echo "(typecheck stub — pyright wired in Task 2 alongside Pydantic schemas)"

# Ingest local CSV/JSON telemetry under data/sample → ClinicalTelemetryPayload JSON.
# Override DATA_PATH for a different source: `just DATA_PATH=data/foo py-ingest`.
DATA_PATH := env_var_or_default('DATA_PATH', 'data/sample')

py-ingest:
    uv run python -m cds_harness.ingest {{DATA_PATH}} --pretty

# Translate clinical guidelines under data/guidelines → OnionL IR + SMT-LIBv2 matrix.
# Always runs the SMT sanity check (Task 4 gate). Override GUIDELINE_PATH to retarget.
GUIDELINE_PATH := env_var_or_default('GUIDELINE_PATH', 'data/guidelines')

py-translate:
    uv run python -m cds_harness.translate {{GUIDELINE_PATH}} --smt-check --pretty

# =============================================================================
# Rust (cargo + clippy + rustfmt + cargo-test)
# =============================================================================

rs-fetch:
    cargo fetch --locked || cargo fetch

rs-build:
    cargo build --workspace

rs-lint:
    cargo clippy --workspace --all-targets -- -D warnings

rs-format:
    cargo fmt --all

rs-test:
    cargo test --workspace

# =============================================================================
# Frontend (bun + Vite + SvelteKit) — placeholder until Task 9
# =============================================================================

ts-install:
    @if [ -f frontend/package.json ]; then cd frontend && bun install; \
     else echo "frontend not yet scaffolded — Task 9"; fi

ts-dev:
    @if [ -f frontend/package.json ]; then cd frontend && bun run dev; \
     else echo "frontend not yet scaffolded — Task 9"; fi

ts-build:
    @if [ -f frontend/package.json ]; then cd frontend && bun run build; \
     else echo "frontend not yet scaffolded — Task 9"; fi

ts-lint:
    @if [ -f frontend/package.json ]; then cd frontend && bun run lint; \
     else echo "frontend not yet scaffolded — Task 9"; fi

ts-test:
    @if [ -f frontend/package.json ]; then cd frontend && bun test; \
     else echo "frontend not yet scaffolded — Task 9"; fi

# =============================================================================
# Aggregates
# =============================================================================

# Lint every ecosystem (Rust + Python + TS).
lint: rs-lint py-lint ts-lint

# Format every ecosystem.
format: rs-format py-format

# Run every test suite.
test: rs-test py-test ts-test

# Build every artifact.
build: rs-build ts-build

# CI-equivalent gate.
ci: env-verify lint test

# Wipe all build/lint caches and external binaries (keeps source).
clean:
    cargo clean || true
    rm -rf .venv .ruff_cache .pytest_cache .mypy_cache target
    rm -rf frontend/node_modules frontend/.svelte-kit frontend/build frontend/dist
    @echo "✓ clean complete (source preserved)"

# Wipe everything + the .bin/ binary cache.
distclean: clean
    rm -rf "{{ justfile_directory() }}/.bin"/!(.gitkeep)
    @echo "✓ distclean complete"

# =============================================================================
# Run targets (Phase 0 placeholders — wired in Task 8 via Dapr)
# =============================================================================

run-kernel:
    @echo "(kernel binary lands in Task 5)"

run-harness: py-ingest

run-frontend: ts-dev

# Convenience: print the active Re-Entry Prompt for the human operator.
re-entry-prompt:
    @cat .agent/Plan.md | awk '/## 9\. Context-Governed Re-Entry Prompt/{flag=1} /## 10\./{flag=0} flag'
