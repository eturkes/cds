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

# Verify env, sync Python venv, prefetch Rust deps, fetch external solver binaries + Dapr.
bootstrap: env-verify py-sync rs-fetch fetch-bins fetch-dapr
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
# Dapr 1.17 — slim self-hosted polyglot orchestration (Phase 0, Task 8)
# =============================================================================
# Per ADR-016: Dapr CLI + slim daprd/placement/scheduler binaries staged
# under .bin/.dapr/.dapr/. Phase 0 binds in-memory pub/sub + state store
# (dapr/components/) — durable backends land in Phase 1+. End-to-end
# Workflow lives in Task 8.4; foundation gate is `just dapr-smoke`.

DAPR_VERSION         := env_var_or_default('DAPR_VERSION', '1.17.0')
DAPR_OS              := env_var_or_default('DAPR_OS',      'linux')
DAPR_ARCH            := env_var_or_default('DAPR_ARCH',    'amd64')
DAPR_INSTALL_DIR     := justfile_directory() + "/.bin/.dapr"
DAPR_RUNTIME_DIR     := DAPR_INSTALL_DIR + "/.dapr"
DAPR_DAPRD           := DAPR_RUNTIME_DIR + "/bin/daprd"
DAPR_RESOURCES_PATH  := justfile_directory() + "/dapr/components"
DAPR_CONFIG_PATH     := justfile_directory() + "/dapr/config.yaml"

# Idempotently stage Dapr CLI + slim runtime under .bin/. Skips populated tree.
fetch-dapr:
    #!/usr/bin/env bash
    set -euo pipefail
    mkdir -p "{{ justfile_directory() }}/.bin"
    if [ -x "{{ justfile_directory() }}/.bin/dapr" ] && [ -x "{{DAPR_DAPRD}}" ]; then
        echo "dapr CLI + slim runtime already present"
        "{{ justfile_directory() }}/.bin/dapr" --version | head -1
        "{{DAPR_DAPRD}}" --version | sed 's/^/daprd /'
        exit 0
    fi
    if [ ! -x "{{ justfile_directory() }}/.bin/dapr" ]; then
        echo "→ fetching dapr CLI v{{DAPR_VERSION}} ({{DAPR_OS}}/{{DAPR_ARCH}})"
        url="https://github.com/dapr/cli/releases/download/v{{DAPR_VERSION}}/dapr_{{DAPR_OS}}_{{DAPR_ARCH}}.tar.gz"
        tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
        curl -fsSL "$url" -o "$tmp/dapr.tgz"
        tar -xzf "$tmp/dapr.tgz" -C "$tmp"
        install -m 0755 "$tmp/dapr" "{{ justfile_directory() }}/.bin/dapr"
    fi
    if [ ! -x "{{DAPR_DAPRD}}" ]; then
        echo "→ initializing slim Dapr runtime under {{DAPR_INSTALL_DIR}}/"
        rm -rf "{{DAPR_INSTALL_DIR}}"
        mkdir -p "{{DAPR_INSTALL_DIR}}"
        "{{ justfile_directory() }}/.bin/dapr" init -s \
            --runtime-path "{{DAPR_INSTALL_DIR}}" \
            --runtime-version {{DAPR_VERSION}}
    fi
    "{{ justfile_directory() }}/.bin/dapr" --version | head -1
    "{{DAPR_DAPRD}}" --version | sed 's/^/daprd /'

# Force re-init: wipe slim runtime and re-stage. Keeps the CLI binary.
dapr-init:
    rm -rf "{{DAPR_INSTALL_DIR}}"
    just fetch-dapr

# Print Dapr CLI/runtime versions + the slim binary inventory + components.
dapr-status:
    #!/usr/bin/env bash
    set -euo pipefail
    "{{ justfile_directory() }}/.bin/dapr" --version
    if [ -x "{{DAPR_DAPRD}}" ]; then
        echo "daprd: $({{DAPR_DAPRD}} --version)"
        echo "slim runtime: {{DAPR_RUNTIME_DIR}}"
        ls -1 "{{DAPR_RUNTIME_DIR}}/bin/" | sed 's|^|  |'
    else
        echo "slim runtime missing — run \`just fetch-dapr\`"
    fi
    echo "components: {{DAPR_RESOURCES_PATH}}"
    ls -1 "{{DAPR_RESOURCES_PATH}}" | sed 's|^|  |'
    echo "config:     {{DAPR_CONFIG_PATH}}"

# Wipe project-local Dapr install (CLI + slim runtime). Source/manifests untouched.
dapr-clean:
    rm -rf "{{DAPR_INSTALL_DIR}}" "{{ justfile_directory() }}/.bin/dapr"
    @echo "✓ dapr clean (run \`just fetch-dapr\` to repopulate)"

# Boot daprd briefly with the project component manifests; assert both
# `cds-pubsub` and `cds-statestore` load and the Workflow engine starts.
# Placement/scheduler ports stay quiet until Task 8.4 — the streamed
# "connection refused" warnings on :50005 / :50006 are expected and ignored.
# Foundation smoke gate (Task 8.1).
dapr-smoke:
    #!/usr/bin/env bash
    set -euo pipefail
    [ -x "{{DAPR_DAPRD}}" ] || { echo "daprd missing — run \`just fetch-dapr\`"; exit 1; }
    log=$(mktemp); trap 'rm -f "$log"' EXIT
    timeout 8 "{{ justfile_directory() }}/.bin/dapr" run \
        --app-id cds-dapr-foundation-smoke \
        --runtime-path "{{DAPR_INSTALL_DIR}}" \
        --resources-path "{{DAPR_RESOURCES_PATH}}" \
        --config "{{DAPR_CONFIG_PATH}}" \
        --log-level info \
        -- sleep 2 \
        > "$log" 2>&1 || true
    grep -q 'Component loaded: cds-pubsub (pubsub.in-memory/v1)' "$log" || \
        { echo "smoke fail: cds-pubsub did not load"; cat "$log"; exit 1; }
    grep -q 'Component loaded: cds-statestore (state.in-memory/v1)' "$log" || \
        { echo "smoke fail: cds-statestore did not load"; cat "$log"; exit 1; }
    grep -q "Using 'cds-statestore' as actor state store" "$log" || \
        { echo "smoke fail: actorStateStore wiring not detected"; cat "$log"; exit 1; }
    grep -q 'Workflow engine started' "$log" || \
        { echo "smoke fail: workflow engine did not start"; cat "$log"; exit 1; }
    grep -q 'Exited Dapr successfully' "$log" || \
        { echo "smoke fail: dapr did not shut down cleanly"; cat "$log"; exit 1; }
    echo "✓ dapr-smoke: cds-pubsub + cds-statestore loaded; workflow engine up; clean shutdown"

# -----------------------------------------------------------------------------
# Dapr cluster bring-up (Task 8.4a) — long-running placement + scheduler.
# -----------------------------------------------------------------------------
# Per ADR-021 §2: foreground daprd ran without these in 8.1–8.3 (placement
# down meant `/v1.0/healthz` returned 500; the integration tests targeted
# `/v1.0/healthz/outbound` which returns 204 once the sidecar's outbound
# subsystem is reachable). Task 8.4a brings the cluster up so Workflow
# (8.4b) can schedule activities. Pid-files live under `target/` so
# `cargo clean` reclaims them; logs live alongside.
#
# Pinned bind ports avoid the 8080/9090 healthz/metrics collision that
# occurs when both binaries default-bind side-by-side on a dev host:
#   placement → gRPC :50005, healthz :50007, metrics :50008
#   scheduler → gRPC :50006, healthz :50009, metrics :50010
# Scheduler's embedded etcd writes under `target/dapr-scheduler-etcd/` —
# overrides the upstream `./data` default that would otherwise collide
# with this repo's genuine telemetry directory.

DAPR_PLACEMENT_BIN   := DAPR_RUNTIME_DIR + "/bin/placement"
DAPR_SCHEDULER_BIN   := DAPR_RUNTIME_DIR + "/bin/scheduler"
DAPR_CLUSTER_DIR     := justfile_directory() + "/target"
DAPR_PLACEMENT_PORT  := env_var_or_default('DAPR_PLACEMENT_PORT',  '50005')
DAPR_PLACEMENT_HZ    := env_var_or_default('DAPR_PLACEMENT_HZ',    '50007')
DAPR_PLACEMENT_MET   := env_var_or_default('DAPR_PLACEMENT_MET',   '50008')
DAPR_SCHEDULER_PORT  := env_var_or_default('DAPR_SCHEDULER_PORT',  '50006')
DAPR_SCHEDULER_HZ    := env_var_or_default('DAPR_SCHEDULER_HZ',    '50009')
DAPR_SCHEDULER_MET   := env_var_or_default('DAPR_SCHEDULER_MET',   '50010')

# Idempotently background-spawn the slim placement service.
# Pid → target/dapr-placement.pid; log → target/dapr-placement.log.
placement-up:
    #!/usr/bin/env bash
    set -euo pipefail
    mkdir -p "{{DAPR_CLUSTER_DIR}}"
    pidfile="{{DAPR_CLUSTER_DIR}}/dapr-placement.pid"
    logfile="{{DAPR_CLUSTER_DIR}}/dapr-placement.log"
    if [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
        echo "placement already up: pid=$(cat "$pidfile") port={{DAPR_PLACEMENT_PORT}}"
        exit 0
    fi
    [ -x "{{DAPR_PLACEMENT_BIN}}" ] || \
        { echo "placement binary missing — run \`just fetch-dapr\`"; exit 1; }
    rm -f "$pidfile"
    nohup "{{DAPR_PLACEMENT_BIN}}" \
        --port {{DAPR_PLACEMENT_PORT}} \
        --healthz-port {{DAPR_PLACEMENT_HZ}} \
        --metrics-port {{DAPR_PLACEMENT_MET}} \
        --listen-address 127.0.0.1 \
        --healthz-listen-address 127.0.0.1 \
        --log-level info \
        > "$logfile" 2>&1 < /dev/null &
    pid=$!
    echo $pid > "$pidfile"
    # Liveness probe — placement should still be running after a beat.
    sleep 0.4
    if ! kill -0 "$pid" 2>/dev/null; then
        echo "placement failed to start — see $logfile"
        rm -f "$pidfile"
        tail -20 "$logfile" || true
        exit 1
    fi
    echo "✓ placement up: pid=$pid grpc={{DAPR_PLACEMENT_PORT}} healthz={{DAPR_PLACEMENT_HZ}} log=$logfile"

# Stop the placement service (SIGTERM-then-grace-then-SIGKILL).
placement-down:
    #!/usr/bin/env bash
    set -euo pipefail
    pidfile="{{DAPR_CLUSTER_DIR}}/dapr-placement.pid"
    if [ ! -f "$pidfile" ]; then
        echo "placement not running (no pid-file)"
        exit 0
    fi
    pid=$(cat "$pidfile")
    if ! kill -0 "$pid" 2>/dev/null; then
        echo "placement not running (stale pid $pid)"
        rm -f "$pidfile"
        exit 0
    fi
    kill -TERM "$pid" 2>/dev/null || true
    for _ in $(seq 1 30); do
        kill -0 "$pid" 2>/dev/null || break
        sleep 0.1
    done
    if kill -0 "$pid" 2>/dev/null; then
        echo "placement ignored SIGTERM — escalating to SIGKILL"
        kill -KILL "$pid" 2>/dev/null || true
        for _ in $(seq 1 20); do
            kill -0 "$pid" 2>/dev/null || break
            sleep 0.1
        done
    fi
    rm -f "$pidfile"
    echo "✓ placement down (pid=$pid)"

# Idempotently background-spawn the slim scheduler service.
# Pid → target/dapr-scheduler.pid; log → target/dapr-scheduler.log;
# embedded etcd data → target/dapr-scheduler-etcd/.
scheduler-up:
    #!/usr/bin/env bash
    set -euo pipefail
    mkdir -p "{{DAPR_CLUSTER_DIR}}"
    pidfile="{{DAPR_CLUSTER_DIR}}/dapr-scheduler.pid"
    logfile="{{DAPR_CLUSTER_DIR}}/dapr-scheduler.log"
    etcddir="{{DAPR_CLUSTER_DIR}}/dapr-scheduler-etcd"
    if [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
        echo "scheduler already up: pid=$(cat "$pidfile") port={{DAPR_SCHEDULER_PORT}}"
        exit 0
    fi
    [ -x "{{DAPR_SCHEDULER_BIN}}" ] || \
        { echo "scheduler binary missing — run \`just fetch-dapr\`"; exit 1; }
    rm -f "$pidfile"
    mkdir -p "$etcddir"
    nohup "{{DAPR_SCHEDULER_BIN}}" \
        --port {{DAPR_SCHEDULER_PORT}} \
        --healthz-port {{DAPR_SCHEDULER_HZ}} \
        --metrics-port {{DAPR_SCHEDULER_MET}} \
        --listen-address 127.0.0.1 \
        --healthz-listen-address 127.0.0.1 \
        --etcd-data-dir "$etcddir" \
        --log-level info \
        > "$logfile" 2>&1 < /dev/null &
    pid=$!
    echo $pid > "$pidfile"
    # Scheduler boots a touch slower than placement (etcd quorum); give
    # it a bit more headroom before declaring it live.
    sleep 1.0
    if ! kill -0 "$pid" 2>/dev/null; then
        echo "scheduler failed to start — see $logfile"
        rm -f "$pidfile"
        tail -30 "$logfile" || true
        exit 1
    fi
    echo "✓ scheduler up: pid=$pid grpc={{DAPR_SCHEDULER_PORT}} healthz={{DAPR_SCHEDULER_HZ}} log=$logfile"

# Stop the scheduler service (SIGTERM-then-grace-then-SIGKILL).
scheduler-down:
    #!/usr/bin/env bash
    set -euo pipefail
    pidfile="{{DAPR_CLUSTER_DIR}}/dapr-scheduler.pid"
    if [ ! -f "$pidfile" ]; then
        echo "scheduler not running (no pid-file)"
        exit 0
    fi
    pid=$(cat "$pidfile")
    if ! kill -0 "$pid" 2>/dev/null; then
        echo "scheduler not running (stale pid $pid)"
        rm -f "$pidfile"
        exit 0
    fi
    kill -TERM "$pid" 2>/dev/null || true
    for _ in $(seq 1 50); do
        kill -0 "$pid" 2>/dev/null || break
        sleep 0.1
    done
    if kill -0 "$pid" 2>/dev/null; then
        echo "scheduler ignored SIGTERM — escalating to SIGKILL"
        kill -KILL "$pid" 2>/dev/null || true
        for _ in $(seq 1 20); do
            kill -0 "$pid" 2>/dev/null || break
            sleep 0.1
        done
    fi
    rm -f "$pidfile"
    echo "✓ scheduler down (pid=$pid)"

# Bring up both placement + scheduler. Idempotent.
dapr-cluster-up: placement-up scheduler-up
    @echo "✓ dapr cluster up — see \`just dapr-cluster-status\`"

# Tear down both (reverse order).
dapr-cluster-down: scheduler-down placement-down
    @echo "✓ dapr cluster down"

# Print PIDs / ports / log paths for the placement + scheduler children.
dapr-cluster-status:
    #!/usr/bin/env bash
    set -euo pipefail
    print_one() {
        local name=$1 pidfile=$2 grpc=$3 hz=$4 logfile=$5
        if [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
            printf "  %-9s up   pid=%-7s grpc=%-5s healthz=%-5s log=%s\n" \
                "$name" "$(cat "$pidfile")" "$grpc" "$hz" "$logfile"
        elif [ -f "$pidfile" ]; then
            printf "  %-9s STALE (pid %s gone)  log=%s\n" \
                "$name" "$(cat "$pidfile")" "$logfile"
        else
            printf "  %-9s down\n" "$name"
        fi
    }
    echo "::: dapr cluster status :::"
    print_one placement \
        "{{DAPR_CLUSTER_DIR}}/dapr-placement.pid" \
        "{{DAPR_PLACEMENT_PORT}}" \
        "{{DAPR_PLACEMENT_HZ}}" \
        "{{DAPR_CLUSTER_DIR}}/dapr-placement.log"
    print_one scheduler \
        "{{DAPR_CLUSTER_DIR}}/dapr-scheduler.pid" \
        "{{DAPR_SCHEDULER_PORT}}" \
        "{{DAPR_SCHEDULER_HZ}}" \
        "{{DAPR_CLUSTER_DIR}}/dapr-scheduler.log"

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

CDS_HARNESS_HOST := env_var_or_default('CDS_HARNESS_HOST', '127.0.0.1')
CDS_HARNESS_PORT := env_var_or_default('CDS_HARNESS_PORT', '8081')

# Run the Python harness FastAPI service standalone (no Dapr sidecar).
# Defaults to 127.0.0.1:8081; override via CDS_HARNESS_HOST / CDS_HARNESS_PORT.
py-service:
    CDS_HARNESS_HOST={{CDS_HARNESS_HOST}} CDS_HARNESS_PORT={{CDS_HARNESS_PORT}} \
        uv run python -m cds_harness.service

# Run the Python harness service under a Dapr sidecar (Task 8.2 gate target).
# Service-invocation routes through daprd's `/v1.0/invoke/cds-harness/method/...`.
# Placement-bound features (Workflow, actors, pub/sub) come live in Task 8.4.
py-service-dapr:
    CDS_HARNESS_HOST={{CDS_HARNESS_HOST}} CDS_HARNESS_PORT={{CDS_HARNESS_PORT}} \
        "{{ justfile_directory() }}/.bin/dapr" run \
            --app-id cds-harness \
            --app-port {{CDS_HARNESS_PORT}} \
            --app-protocol http \
            --runtime-path "{{DAPR_INSTALL_DIR}}" \
            --resources-path "{{DAPR_RESOURCES_PATH}}" \
            --config "{{DAPR_CONFIG_PATH}}" \
            --log-level info \
            -- uv run python -m cds_harness.service

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

# Run the deductive engine smoke gate (Task 5): Datalog rule firing +
# Octagon hull tightening across the kernel test fixtures.
rs-deduce:
    cargo test --package cds-kernel --test deduce_smoke -- --nocapture

# Run the solver smoke gate (Task 6): warden + Z3 unsat-core + cvc5
# Alethe proof emission, projecting MUC labels back to source spans.
# Requires `.bin/z3` and `.bin/cvc5` (run `just fetch-bins` if missing).
rs-solver:
    cargo test --package cds-kernel --test solver_smoke -- --nocapture

# Run the Lean re-check smoke gate (Task 7): drives an end-to-end round-trip
# from contradictory matrix → cvc5 Alethe proof → Kimina headless server
# → Lean info-message probes parsed back through the bridge. Requires a
# Kimina daemon reachable at $CDS_KIMINA_URL (default skip is loud, not
# silent). Start one via `python -m server` from the project-numina
# kimina-lean-server checkout, then re-run with that URL exported.
CDS_KIMINA_URL := env_var_or_default('CDS_KIMINA_URL', '')

rs-lean:
    CDS_KIMINA_URL={{CDS_KIMINA_URL}} cargo test --package cds-kernel --test lean_smoke -- --nocapture

# Run the kernel service smoke gate (Task 8.3a + 8.3b2a): standalone
# HTTP + gated Dapr sidecar driving /healthz and /v1/deduce through
# service invocation. The sidecar halves skip with a loud notice if
# .bin/dapr / slim runtime are missing; run `just fetch-dapr` to populate.
rs-service-smoke:
    cargo test --package cds-kernel --test service_smoke -- --nocapture --test-threads=1

# Run the kernel pipeline smoke gate (Task 8.3b2b): gated Dapr sidecar
# driving /v1/solve and /v1/recheck through service invocation. The
# /v1/solve test skips loudly without `.bin/z3` + `.bin/cvc5` (run
# `just fetch-bins`); the /v1/recheck test additionally skips without
# `CDS_KIMINA_URL` set (start Kimina via `python -m server` from the
# project-numina/kimina-lean-server checkout, then re-run with the URL
# exported). Closes the 8.3b daprd round-trip — six Phase 0 endpoints
# (kernel /healthz + /v1/{deduce,solve,recheck}; harness /healthz +
# /v1/{ingest,translate}) under their respective sidecars.
rs-service-pipeline-smoke:
    CDS_KIMINA_URL={{CDS_KIMINA_URL}} cargo test --package cds-kernel --test service_pipeline_smoke -- --nocapture --test-threads=1

# Bind addresses for the Phase 0 kernel service (Task 8.3a). 8082 is
# the default — the harness service holds 8081 (ADR-017 §1) so both
# can run side-by-side under a single `just dapr-pipeline` (Task 8.4).
CDS_KERNEL_HOST := env_var_or_default('CDS_KERNEL_HOST', '127.0.0.1')
CDS_KERNEL_PORT := env_var_or_default('CDS_KERNEL_PORT', '8082')

# Run the Rust kernel HTTP service standalone (no Dapr sidecar).
# Builds first; honours CDS_KERNEL_HOST / CDS_KERNEL_PORT.
rs-service:
    cargo build --bin cds-kernel-service
    CDS_KERNEL_HOST={{CDS_KERNEL_HOST}} CDS_KERNEL_PORT={{CDS_KERNEL_PORT}} \
        cargo run --bin cds-kernel-service

# Run the kernel service under a Dapr sidecar (Task 8.3a gate target).
# Service-invocation routes through daprd's `/v1.0/invoke/cds-kernel/method/...`.
# Pre-builds the binary so daprd's app-discovery wait does not need to
# block on cargo. Placement-bound features (Workflow, actors) come live
# in Task 8.4.
rs-service-dapr:
    cargo build --bin cds-kernel-service
    CDS_KERNEL_HOST={{CDS_KERNEL_HOST}} CDS_KERNEL_PORT={{CDS_KERNEL_PORT}} \
        "{{ justfile_directory() }}/.bin/dapr" run \
            --app-id cds-kernel \
            --app-port {{CDS_KERNEL_PORT}} \
            --app-protocol http \
            --runtime-path "{{DAPR_INSTALL_DIR}}" \
            --resources-path "{{DAPR_RESOURCES_PATH}}" \
            --config "{{DAPR_CONFIG_PATH}}" \
            --log-level info \
            -- "{{ justfile_directory() }}/target/debug/cds-kernel-service"

# =============================================================================
# Dapr end-to-end Workflow pipeline (Task 8.4b)
# =============================================================================
# `just dapr-pipeline` brings up placement+scheduler, both Phase 0
# sidecars (cds-harness + cds-kernel), and a `cds-workflow` sidecar that
# hosts the Dapr Python SDK WorkflowRuntime. The orchestrator drives
# ingest → translate → deduce → solve → recheck against the canonical
# `data/guidelines/contradictory-bound.{txt,recorded.json}` fixture and
# asserts `trace.sat == false` + `recheck.ok == true`. Reverse teardown
# at exit. Per ADR-021 §3.

DAPR_PIPELINE_PAYLOAD   := env_var_or_default('DAPR_PIPELINE_PAYLOAD',   'data/sample/icu-monitor-02.json')
DAPR_PIPELINE_GUIDELINE := env_var_or_default('DAPR_PIPELINE_GUIDELINE', 'data/guidelines/contradictory-bound.txt')
DAPR_PIPELINE_DOC_ID    := env_var_or_default('DAPR_PIPELINE_DOC_ID',    'contradictory-bound')
DAPR_PIPELINE_ASSERT    := env_var_or_default('DAPR_PIPELINE_ASSERT',    '--assert-unsat')
DAPR_PIPELINE_TIMEOUT_S := env_var_or_default('DAPR_PIPELINE_TIMEOUT_S', '600')

# End-to-end Phase 0 Workflow run (Task 8.4b close-out). Requires .bin/dapr + slim runtime + .bin/{z3,cvc5} + reachable $CDS_KIMINA_URL.
dapr-pipeline:
    #!/usr/bin/env bash
    set -euo pipefail
    repo="{{ justfile_directory() }}"
    dapr_cli="$repo/.bin/dapr"
    daprd="{{DAPR_DAPRD}}"
    [ -x "$dapr_cli" ] && [ -x "$daprd" ] || \
        { echo "dapr CLI / slim runtime missing — run \`just fetch-dapr\`"; exit 1; }
    [ -x "$repo/.bin/z3" ] && [ -x "$repo/.bin/cvc5" ] || \
        { echo "Z3 / cvc5 missing — run \`just fetch-bins\`"; exit 1; }
    [ -n "${CDS_KIMINA_URL:-}" ] || \
        { echo "CDS_KIMINA_URL unset — start Kimina (\`python -m server\` from the project-numina/kimina-lean-server checkout) and re-run with that URL exported."; exit 1; }

    # Pre-build the kernel binary so the kernel sidecar starts fast.
    cargo build --bin cds-kernel-service

    mkdir -p target

    # Per-sidecar pid + log paths.
    py_pid="target/dapr-pipeline-harness.pid"
    py_log="target/dapr-pipeline-harness.log"
    rs_pid="target/dapr-pipeline-kernel.pid"
    rs_log="target/dapr-pipeline-kernel.log"
    wf_pid="target/dapr-pipeline-workflow.pid"
    wf_log="target/dapr-pipeline-workflow.log"

    # Reverse-order teardown — run on every exit path so we never leak.
    cleanup() {
        for pidfile in "$wf_pid" "$rs_pid" "$py_pid"; do
            if [ -f "$pidfile" ]; then
                pid=$(cat "$pidfile")
                if kill -0 "$pid" 2>/dev/null; then
                    kill -TERM "$pid" 2>/dev/null || true
                    for _ in $(seq 1 50); do
                        kill -0 "$pid" 2>/dev/null || break
                        sleep 0.1
                    done
                    if kill -0 "$pid" 2>/dev/null; then
                        kill -KILL "$pid" 2>/dev/null || true
                    fi
                fi
                rm -f "$pidfile"
            fi
        done
        just dapr-cluster-down >/dev/null 2>&1 || true
    }
    trap cleanup EXIT INT TERM

    # 1. Placement + scheduler.
    just dapr-cluster-up
    # Pre-flight the cluster's full readiness gate. Workflow can't
    # schedule activities until placement reports healthy.
    for _ in $(seq 1 60); do
        if curl -sf "http://127.0.0.1:{{DAPR_PLACEMENT_HZ}}/healthz" >/dev/null; then break; fi
        sleep 0.5
    done
    for _ in $(seq 1 60); do
        if curl -sf "http://127.0.0.1:{{DAPR_SCHEDULER_HZ}}/healthz" >/dev/null; then break; fi
        sleep 0.5
    done

    # Reserve four ports per sidecar (app + dapr-http + dapr-grpc + metrics).
    pick_port() { python3 -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1]);s.close()'; }
    py_app_port=$(pick_port); py_http=$(pick_port); py_grpc=$(pick_port); py_met=$(pick_port)
    rs_app_port=$(pick_port); rs_http=$(pick_port); rs_grpc=$(pick_port); rs_met=$(pick_port)
    wf_app_port=$(pick_port); wf_http=$(pick_port); wf_grpc=$(pick_port); wf_met=$(pick_port)

    # 2. Harness sidecar (cds-harness).
    CDS_HARNESS_HOST=127.0.0.1 CDS_HARNESS_PORT=$py_app_port \
    nohup "$dapr_cli" run \
        --app-id cds-harness \
        --app-port "$py_app_port" \
        --app-protocol http \
        --dapr-http-port "$py_http" \
        --dapr-grpc-port "$py_grpc" \
        --metrics-port "$py_met" \
        --runtime-path "{{DAPR_INSTALL_DIR}}" \
        --resources-path "{{DAPR_RESOURCES_PATH}}" \
        --config "{{DAPR_CONFIG_PATH}}" \
        --log-level info \
        -- uv run python -m cds_harness.service \
        > "$py_log" 2>&1 < /dev/null &
    echo $! > "$py_pid"

    # 3. Kernel sidecar (cds-kernel).
    CDS_KERNEL_HOST=127.0.0.1 CDS_KERNEL_PORT=$rs_app_port \
    nohup "$dapr_cli" run \
        --app-id cds-kernel \
        --app-port "$rs_app_port" \
        --app-protocol http \
        --dapr-http-port "$rs_http" \
        --dapr-grpc-port "$rs_grpc" \
        --metrics-port "$rs_met" \
        --runtime-path "{{DAPR_INSTALL_DIR}}" \
        --resources-path "{{DAPR_RESOURCES_PATH}}" \
        --config "{{DAPR_CONFIG_PATH}}" \
        --log-level info \
        -- "$repo/target/debug/cds-kernel-service" \
        > "$rs_log" 2>&1 < /dev/null &
    echo $! > "$rs_pid"

    # Wait for both /v1.0/healthz to flip ready (placement-bound).
    wait_ready() {
        local url=$1 budget=${2:-60}
        for _ in $(seq 1 $budget); do
            code=$(curl -s -o /dev/null -w '%{http_code}' "$url" || echo 000)
            if [ "$code" = "200" ] || [ "$code" = "204" ]; then return 0; fi
            sleep 0.5
        done
        echo "readiness wait timed out for $url"; return 1
    }
    wait_ready "http://127.0.0.1:${py_app_port}/healthz"
    wait_ready "http://127.0.0.1:${rs_app_port}/healthz"
    wait_ready "http://127.0.0.1:${py_http}/v1.0/healthz" 90
    wait_ready "http://127.0.0.1:${rs_http}/v1.0/healthz" 90

    # 4. Workflow sidecar (cds-workflow) — runs the orchestrator inside
    # `dapr run` so the SDK's WorkflowRuntime can find the gRPC port.
    nohup "$dapr_cli" run \
        --app-id cds-workflow \
        --dapr-http-port "$wf_http" \
        --dapr-grpc-port "$wf_grpc" \
        --metrics-port "$wf_met" \
        --runtime-path "{{DAPR_INSTALL_DIR}}" \
        --resources-path "{{DAPR_RESOURCES_PATH}}" \
        --config "{{DAPR_CONFIG_PATH}}" \
        --log-level info \
        -- uv run python -m cds_harness.workflow run-pipeline \
            --payload "{{DAPR_PIPELINE_PAYLOAD}}" \
            --guideline "{{DAPR_PIPELINE_GUIDELINE}}" \
            --doc-id "{{DAPR_PIPELINE_DOC_ID}}" \
            --kimina-url "$CDS_KIMINA_URL" \
            --z3-path "$repo/.bin/z3" \
            --cvc5-path "$repo/.bin/cvc5" \
            --timeout-s "{{DAPR_PIPELINE_TIMEOUT_S}}" \
            --assert-recheck-ok \
            {{DAPR_PIPELINE_ASSERT}} \
        > "$wf_log" 2>&1 < /dev/null &
    wf_runner=$!
    echo $wf_runner > "$wf_pid"

    # Block until the workflow runner exits; surface its status verbatim.
    if wait "$wf_runner"; then
        echo "✓ dapr-pipeline complete — see $wf_log for the aggregated envelope"
        exit 0
    else
        rc=$?
        echo "✗ dapr-pipeline failed (exit=$rc) — tail of $wf_log:"
        tail -40 "$wf_log" || true
        exit $rc
    fi

# =============================================================================
# Frontend (bun + Vite + SvelteKit 2 + Svelte 5 runes + Tailwind 4) — Task 9.1
# =============================================================================
# Per ADR-022 §2: scaffolded via `sv create --template minimal --types ts`
# with the official add-ons (eslint, prettier, tailwindcss, vitest, playwright).
# Every recipe shells out to `bun run <script>` against frontend/package.json.

# Install (or re-install) JS deps from frontend/bun.lock. CI sets
# BUN_CONFIG_FROZEN_LOCKFILE=true; local dev gets `bun install` semantics.
frontend-install:
    cd frontend && bun install

# Vite dev server with HMR (no auto-open). Bound to 127.0.0.1:5173 to match
# the BFF's daprd-port read convention in 9.2.
frontend-dev:
    cd frontend && bun run dev --host 127.0.0.1 --port 5173

# Production build via @sveltejs/adapter-node → frontend/build/.
frontend-build:
    cd frontend && bun run build

# Serve the production build on :4173. Used by the 9.3 Playwright E2E.
frontend-preview:
    cd frontend && bun run preview --host 127.0.0.1 --port 4173

# Prettier --check + ESLint flat config.
frontend-lint:
    cd frontend && bun run lint

# Prettier --write across the project.
frontend-format:
    cd frontend && bun run format

# svelte-check against tsconfig (strict + noUncheckedIndexedAccess).
frontend-typecheck:
    cd frontend && bun run check

# Vitest unit tests (tombstone in 9.1; parity tripwire in 9.2).
frontend-test:
    cd frontend && bun run test:unit

# Playwright E2E (tombstone in 9.1; live-cluster pipeline run in 9.3).
# Auto-installs Chromium under ~/.cache/ms-playwright/ on first run.
frontend-e2e:
    cd frontend && bun run test:e2e

# =============================================================================
# Frontend BFF canonical smoke (Task 9.2)
# =============================================================================
# `just frontend-bff-smoke` brings up placement+scheduler, both Phase 0
# daprd sidecars (cds-harness + cds-kernel) on freshly-allocated ports,
# plus the SvelteKit BFF as a compiled adapter-node server, then drives
# `/api/{ingest,translate,deduce,solve,recheck}` end-to-end against the
# canonical `data/guidelines/contradictory-bound.{txt,recorded.json}`
# fixture and asserts `trace.sat == false` + `recheck.ok == true`. Mirrors
# `dapr-pipeline` but exits the curl-on-BFF path rather than the headless
# Workflow path. Per ADR-022 §3.

DAPR_BFF_SMOKE_RECORDED := env_var_or_default('DAPR_BFF_SMOKE_RECORDED', 'data/guidelines/contradictory-bound.recorded.json')

# End-to-end Phase 0 BFF smoke (Task 9.2 close-out gate). Requires .bin/dapr + slim runtime + .bin/{z3,cvc5} + reachable $CDS_KIMINA_URL + bun in $PATH.
frontend-bff-smoke:
    #!/usr/bin/env bash
    set -euo pipefail
    repo="{{ justfile_directory() }}"
    dapr_cli="$repo/.bin/dapr"
    daprd="{{DAPR_DAPRD}}"
    [ -x "$dapr_cli" ] && [ -x "$daprd" ] || \
        { echo "dapr CLI / slim runtime missing — run \`just fetch-dapr\`"; exit 1; }
    [ -x "$repo/.bin/z3" ] && [ -x "$repo/.bin/cvc5" ] || \
        { echo "Z3 / cvc5 missing — run \`just fetch-bins\`"; exit 1; }
    [ -n "${CDS_KIMINA_URL:-}" ] || \
        { echo "CDS_KIMINA_URL unset — start Kimina (\`python -m server\` from the project-numina/kimina-lean-server checkout) and re-run with that URL exported."; exit 1; }
    command -v bun >/dev/null 2>&1 || \
        { echo "bun not found — install bun (https://bun.sh) before running this recipe."; exit 1; }

    # Pre-build kernel + frontend so both sidecars + BFF start fast.
    cargo build --bin cds-kernel-service
    ( cd "$repo/frontend" && bun install >/dev/null && bun run build >/dev/null )

    mkdir -p target

    py_pid="target/bff-smoke-harness.pid";  py_log="target/bff-smoke-harness.log"
    rs_pid="target/bff-smoke-kernel.pid";   rs_log="target/bff-smoke-kernel.log"
    bff_pid="target/bff-smoke-bff.pid";     bff_log="target/bff-smoke-bff.log"

    cleanup() {
        for pidfile in "$bff_pid" "$rs_pid" "$py_pid"; do
            if [ -f "$pidfile" ]; then
                pid=$(cat "$pidfile")
                if kill -0 "$pid" 2>/dev/null; then
                    kill -TERM "$pid" 2>/dev/null || true
                    for _ in $(seq 1 50); do kill -0 "$pid" 2>/dev/null || break; sleep 0.1; done
                    if kill -0 "$pid" 2>/dev/null; then kill -KILL "$pid" 2>/dev/null || true; fi
                fi
                rm -f "$pidfile"
            fi
        done
        just dapr-cluster-down >/dev/null 2>&1 || true
    }
    trap cleanup EXIT INT TERM

    # 1. Cluster (placement + scheduler).
    just dapr-cluster-up
    for _ in $(seq 1 60); do
        if curl -sf "http://127.0.0.1:{{DAPR_PLACEMENT_HZ}}/healthz" >/dev/null; then break; fi
        sleep 0.5
    done
    for _ in $(seq 1 60); do
        if curl -sf "http://127.0.0.1:{{DAPR_SCHEDULER_HZ}}/healthz" >/dev/null; then break; fi
        sleep 0.5
    done

    pick_port() { python3 -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1]);s.close()'; }
    py_app_port=$(pick_port); py_http=$(pick_port); py_grpc=$(pick_port); py_met=$(pick_port)
    rs_app_port=$(pick_port); rs_http=$(pick_port); rs_grpc=$(pick_port); rs_met=$(pick_port)
    bff_port=$(pick_port)

    # 2. Harness sidecar.
    CDS_HARNESS_HOST=127.0.0.1 CDS_HARNESS_PORT=$py_app_port \
    nohup "$dapr_cli" run \
        --app-id cds-harness \
        --app-port "$py_app_port" --app-protocol http \
        --dapr-http-port "$py_http" --dapr-grpc-port "$py_grpc" --metrics-port "$py_met" \
        --runtime-path "{{DAPR_INSTALL_DIR}}" --resources-path "{{DAPR_RESOURCES_PATH}}" \
        --config "{{DAPR_CONFIG_PATH}}" --log-level info \
        -- uv run python -m cds_harness.service \
        > "$py_log" 2>&1 < /dev/null &
    echo $! > "$py_pid"

    # 3. Kernel sidecar.
    CDS_KERNEL_HOST=127.0.0.1 CDS_KERNEL_PORT=$rs_app_port \
    nohup "$dapr_cli" run \
        --app-id cds-kernel \
        --app-port "$rs_app_port" --app-protocol http \
        --dapr-http-port "$rs_http" --dapr-grpc-port "$rs_grpc" --metrics-port "$rs_met" \
        --runtime-path "{{DAPR_INSTALL_DIR}}" --resources-path "{{DAPR_RESOURCES_PATH}}" \
        --config "{{DAPR_CONFIG_PATH}}" --log-level info \
        -- "$repo/target/debug/cds-kernel-service" \
        > "$rs_log" 2>&1 < /dev/null &
    echo $! > "$rs_pid"

    wait_ready() {
        local url=$1 budget=${2:-60}
        for _ in $(seq 1 $budget); do
            code=$(curl -s -o /dev/null -w '%{http_code}' "$url" || echo 000)
            if [ "$code" = "200" ] || [ "$code" = "204" ]; then return 0; fi
            sleep 0.5
        done
        echo "readiness wait timed out for $url"; return 1
    }
    wait_ready "http://127.0.0.1:${py_app_port}/healthz"
    wait_ready "http://127.0.0.1:${rs_app_port}/healthz"
    wait_ready "http://127.0.0.1:${py_http}/v1.0/healthz" 90
    wait_ready "http://127.0.0.1:${rs_http}/v1.0/healthz" 90

    # 4. SvelteKit BFF (production build via adapter-node). Reads
    # DAPR_HTTP_PORT_{HARNESS,KERNEL} at request time.
    DAPR_HTTP_PORT_HARNESS=$py_http DAPR_HTTP_PORT_KERNEL=$rs_http \
    PORT=$bff_port HOST=127.0.0.1 \
    nohup bun "$repo/frontend/build/index.js" > "$bff_log" 2>&1 < /dev/null &
    echo $! > "$bff_pid"
    wait_ready "http://127.0.0.1:${bff_port}/" 60

    # 5. Drive the canonical pipeline through the BFF.
    BFF_PORT=$bff_port \
    PAYLOAD_PATH="{{DAPR_PIPELINE_PAYLOAD}}" \
    GUIDELINE_PATH="{{DAPR_PIPELINE_GUIDELINE}}" \
    RECORDED_PATH="{{DAPR_BFF_SMOKE_RECORDED}}" \
    DOC_ID="{{DAPR_PIPELINE_DOC_ID}}" \
    Z3_PATH="$repo/.bin/z3" CVC5_PATH="$repo/.bin/cvc5" \
    KIMINA_URL="$CDS_KIMINA_URL" \
    python3 - <<'PY'
    import json, os, sys, urllib.request, urllib.error

    BFF = f"http://127.0.0.1:{os.environ['BFF_PORT']}"

    def post(path, body):
        url = f"{BFF}/{path}"
        data = json.dumps(body).encode()
        req = urllib.request.Request(url, method='POST', data=data,
                                      headers={'content-type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            sys.stderr.write(f"✗ {path}: HTTP {e.code} {e.read().decode()[:500]}\n")
            sys.exit(1)
        except Exception as e:
            sys.stderr.write(f"✗ {path}: {e}\n")
            sys.exit(1)

    envelope = json.load(open(os.environ['PAYLOAD_PATH']))
    text     = open(os.environ['GUIDELINE_PATH']).read()
    recorded = json.load(open(os.environ['RECORDED_PATH']))

    print(">>> /api/ingest",    file=sys.stderr)
    payload = post('api/ingest', {'format': 'json', 'envelope': envelope})
    assert isinstance(payload.get('samples'), list) and payload['samples'], 'ingest empty samples'

    print(">>> /api/translate", file=sys.stderr)
    translate = post('api/translate', {
        'doc_id': os.environ['DOC_ID'],
        'text':   text,
        'root':   recorded['root'],
        'logic':  'QF_LRA',
    })
    matrix = translate['matrix']
    assert matrix.get('logic') == 'QF_LRA', f"translate.matrix.logic={matrix.get('logic')}"

    print(">>> /api/deduce",    file=sys.stderr)
    verdict = post('api/deduce', {'payload': payload})
    assert isinstance(verdict.get('breach_summary'), dict), 'deduce missing breach_summary'

    print(">>> /api/solve",     file=sys.stderr)
    trace = post('api/solve', {
        'matrix':  matrix,
        'options': {
            'timeout_ms': 30000,
            'z3_path':    os.environ['Z3_PATH'],
            'cvc5_path':  os.environ['CVC5_PATH'],
        },
    })
    assert trace.get('sat') is False, f"trace.sat={trace.get('sat')}, expected False"
    assert isinstance(trace.get('muc'), list) and len(trace['muc']) >= 2, \
        f"expected >=2 MUC entries, got {trace.get('muc')}"

    print(">>> /api/recheck",   file=sys.stderr)
    recheck = post('api/recheck', {
        'trace':   trace,
        'options': {
            'kimina_url': os.environ['KIMINA_URL'],
            'timeout_ms': 60000,
            'custom_id':  'cds-bff-smoke',
        },
    })
    assert recheck.get('ok') is True, f"recheck.ok={recheck.get('ok')}, expected True"
    assert recheck.get('custom_id') == 'cds-bff-smoke'

    summary = {
        'payload_samples':     len(payload['samples']),
        'matrix_assumptions':  len(matrix['assumptions']),
        'trace_sat':           trace['sat'],
        'trace_muc':           trace['muc'],
        'recheck_ok':          recheck['ok'],
        'recheck_custom_id':   recheck['custom_id'],
    }
    print('\n✓ frontend-bff-smoke complete', file=sys.stderr)
    print(json.dumps(summary, indent=2))
    PY

# =============================================================================
# Aggregates
# =============================================================================

# Lint every ecosystem (Rust + Python + TS).
lint: rs-lint py-lint frontend-lint

# Format every ecosystem.
format: rs-format py-format

# Run every test suite.
test: rs-test py-test frontend-test

# Build every artifact.
build: rs-build frontend-build

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

run-frontend: frontend-dev

# Convenience: print the active Re-Entry Prompt for the human operator.
re-entry-prompt:
    @cat .agent/Plan.md | awk '/## 9\. Context-Governed Re-Entry Prompt/{flag=1} /## 10\./{flag=0} flag'
