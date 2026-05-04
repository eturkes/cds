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
    if [ -x "{{ justfile_directory() }}/.bin/.hfs/hfs" ]; then
        echo "  .bin/.hfs/ present (Phase 1 FHIR R5 server staged)"
    else
        echo "  .bin/.hfs/ empty (run: just fetch-fhir — Phase 1 FHIR axis only)"
    fi
    cloud_missing=()
    for tool in kind kubectl helm; do
        if [ -x "{{ justfile_directory() }}/.bin/$tool" ]; then
            :
        else
            cloud_missing+=("$tool")
        fi
    done
    if [ "${#cloud_missing[@]}" -eq 0 ]; then
        echo "  .bin/{kind,kubectl,helm} present (Phase 1 cloud axis staged)"
    else
        printf "  .bin/ missing cloud tools: %s (run: just fetch-cloud — Phase 1 cloud axis only)\n" "${cloud_missing[*]}"
    fi
    if command -v docker >/dev/null 2>&1; then
        echo "  docker present ($(docker --version 2>&1 | head -1))"
    elif command -v podman >/dev/null 2>&1; then
        echo "  podman present ($(podman --version 2>&1 | head -1)) — set DOCKER=podman for cloud-build"
    else
        echo "  docker/podman missing (Phase 1 cloud-build only — install host-side or set DOCKER=<tool>)"
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
# FHIR R5 — Helios FHIR Server (Phase 1, Task 10.1)
# =============================================================================
# Per ADR-025: Rust-native HeliosSoftware/hfs v0.1.47 staged under
# .bin/.hfs/. Embedded SQLite under target/hfs-state/. Bound at
# 127.0.0.1:8080; FHIR base = http://127.0.0.1:8080/fhir/R5/. The
# 770MB tarball is heavy — `fetch-fhir` is NOT in `bootstrap` (mirrors
# `fetch-lean`'s opt-in precedent). Operators run `just fetch-fhir`
# explicitly when they need a live FHIR server.

FHIR_VERSION          := env_var_or_default('FHIR_VERSION', '0.1.47')
FHIR_OS               := env_var_or_default('FHIR_OS',      'unknown-linux-gnu')
FHIR_ARCH             := env_var_or_default('FHIR_ARCH',    'x86_64')
FHIR_PORT             := env_var_or_default('FHIR_PORT',    '8080')
FHIR_INSTALL_DIR      := justfile_directory() + "/.bin/.hfs"
FHIR_BIN              := FHIR_INSTALL_DIR + "/hfs"
FHIR_STATE_DIR        := justfile_directory() + "/target/hfs-state"
FHIR_PIDFILE          := justfile_directory() + "/target/hfs.pid"
FHIR_LOGFILE          := justfile_directory() + "/target/hfs.log"
# sha256 of hfs-0.1.47-x86_64-unknown-linux-gnu.tar.gz (pinned at decision time)
FHIR_SHA256           := env_var_or_default('FHIR_SHA256',  'ce0558056ed50ce7b7e029ce1b5cd3f22c4faef7e78995c0e4fda3453ea37a18')

# Idempotently stage the Helios FHIR R5 server binary under .bin/.hfs/.
# Verifies sha256 against the pinned digest. Skips if already present.
fetch-fhir:
    #!/usr/bin/env bash
    set -euo pipefail
    mkdir -p "{{FHIR_INSTALL_DIR}}"
    if [ -x "{{FHIR_BIN}}" ]; then
        echo "hfs already present in .bin/.hfs/"
        "{{FHIR_BIN}}" --version 2>&1 | head -1 || true
        exit 0
    fi
    asset="hfs-{{FHIR_VERSION}}-{{FHIR_ARCH}}-{{FHIR_OS}}.tar.gz"
    url="https://github.com/HeliosSoftware/hfs/releases/download/v{{FHIR_VERSION}}/${asset}"
    echo "→ fetching Helios FHIR Server v{{FHIR_VERSION}} ({{FHIR_ARCH}}-{{FHIR_OS}})"
    tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
    curl -fsSL "$url" -o "$tmp/$asset"
    actual_sha=$(sha256sum "$tmp/$asset" | awk '{print $1}')
    if [ "$actual_sha" != "{{FHIR_SHA256}}" ]; then
        echo "sha256 mismatch for $asset"
        echo "  expected: {{FHIR_SHA256}}"
        echo "  actual:   $actual_sha"
        exit 1
    fi
    tar -xzf "$tmp/$asset" -C "$tmp"
    bin_path=$(find "$tmp" -type f -name hfs -perm -u+x | head -1)
    [ -n "$bin_path" ] || { echo "no executable 'hfs' in tarball"; exit 1; }
    install -m 0755 "$bin_path" "{{FHIR_BIN}}"
    "{{FHIR_BIN}}" --version 2>&1 | head -1 || true

# Print FHIR server status: pid, port, log, capability statement summary.
fhir-status:
    #!/usr/bin/env bash
    set -euo pipefail
    if [ ! -x "{{FHIR_BIN}}" ]; then
        echo "hfs binary missing — run \`just fetch-fhir\`"
        exit 0
    fi
    if [ -f "{{FHIR_PIDFILE}}" ] && kill -0 "$(cat "{{FHIR_PIDFILE}}")" 2>/dev/null; then
        pid=$(cat "{{FHIR_PIDFILE}}")
        echo "hfs up: pid=$pid port={{FHIR_PORT}} log={{FHIR_LOGFILE}}"
        meta_url="http://127.0.0.1:{{FHIR_PORT}}/fhir/R5/metadata"
        if curl -fsS "$meta_url" -o /dev/null 2>/dev/null; then
            echo "  metadata: $meta_url ✓"
        else
            echo "  metadata: $meta_url unreachable"
        fi
    else
        echo "hfs not running (no pid-file or stale)"
    fi
    echo "state: {{FHIR_STATE_DIR}}"

# Wipe FHIR runtime state (pid + log + embedded SQLite). Preserves .bin/.hfs/.
fhir-clean:
    rm -rf "{{FHIR_STATE_DIR}}" "{{FHIR_PIDFILE}}" "{{FHIR_LOGFILE}}"
    @echo "✓ fhir clean (run \`just fhir-server-up\` to repopulate state)"

# Idempotently background-spawn the Helios FHIR R5 server.
# Pid → target/hfs.pid; log → target/hfs.log; state → target/hfs-state/.
# Liveness probe: GET /fhir/R5/metadata (FHIR CapabilityStatement).
fhir-server-up:
    #!/usr/bin/env bash
    set -euo pipefail
    mkdir -p "{{ justfile_directory() }}/target" "{{FHIR_STATE_DIR}}"
    if [ -f "{{FHIR_PIDFILE}}" ] && kill -0 "$(cat "{{FHIR_PIDFILE}}")" 2>/dev/null; then
        echo "hfs already up: pid=$(cat "{{FHIR_PIDFILE}}") port={{FHIR_PORT}}"
        exit 0
    fi
    [ -x "{{FHIR_BIN}}" ] || { echo "hfs missing — run \`just fetch-fhir\`"; exit 1; }
    rm -f "{{FHIR_PIDFILE}}"
    nohup "{{FHIR_BIN}}" \
        --port {{FHIR_PORT}} \
        --bind 127.0.0.1 \
        --data-dir "{{FHIR_STATE_DIR}}" \
        > "{{FHIR_LOGFILE}}" 2>&1 < /dev/null &
    pid=$!
    echo $pid > "{{FHIR_PIDFILE}}"
    # Liveness probe — server should accept a metadata GET within 5s.
    meta_url="http://127.0.0.1:{{FHIR_PORT}}/fhir/R5/metadata"
    for _ in $(seq 1 50); do
        if ! kill -0 "$pid" 2>/dev/null; then
            echo "hfs failed to start — see {{FHIR_LOGFILE}}"
            rm -f "{{FHIR_PIDFILE}}"
            tail -20 "{{FHIR_LOGFILE}}" || true
            exit 1
        fi
        if curl -fsS "$meta_url" -o /dev/null 2>/dev/null; then
            echo "✓ hfs up: pid=$pid port={{FHIR_PORT}} metadata=$meta_url log={{FHIR_LOGFILE}}"
            exit 0
        fi
        sleep 0.1
    done
    echo "hfs started but metadata endpoint never responded — see {{FHIR_LOGFILE}}"
    tail -20 "{{FHIR_LOGFILE}}" || true
    exit 1

# Stop the FHIR server (SIGTERM-then-grace-then-SIGKILL).
fhir-server-down:
    #!/usr/bin/env bash
    set -euo pipefail
    if [ ! -f "{{FHIR_PIDFILE}}" ]; then
        echo "hfs not running (no pid-file)"
        exit 0
    fi
    pid=$(cat "{{FHIR_PIDFILE}}")
    if ! kill -0 "$pid" 2>/dev/null; then
        echo "hfs not running (stale pid $pid)"
        rm -f "{{FHIR_PIDFILE}}"
        exit 0
    fi
    kill -TERM "$pid" 2>/dev/null || true
    for _ in $(seq 1 30); do
        kill -0 "$pid" 2>/dev/null || break
        sleep 0.1
    done
    if kill -0 "$pid" 2>/dev/null; then
        echo "hfs ignored SIGTERM — escalating to SIGKILL"
        kill -KILL "$pid" 2>/dev/null || true
        for _ in $(seq 1 20); do
            kill -0 "$pid" 2>/dev/null || break
            sleep 0.1
        done
    fi
    rm -f "{{FHIR_PIDFILE}}"
    echo "✓ hfs down (pid=$pid)"

# End-to-end FHIR foundation smoke (Task 10.1 close-out gate).
# Brings hfs up, POSTs the canonical icu-monitor-02 Observation Bundle
# to /fhir/R5/Observation (one entry at a time), GETs each back, asserts
# round-trip, tears the server down. Gated on .bin/.hfs/hfs presence —
# skips with informational message if absent (mirrors rs-solver's
# .bin/z3 gate). The `bash -lc` frame keeps `set -e` and trap-based
# teardown coherent across the up/POST/GET/down cycle.
fhir-smoke:
    #!/usr/bin/env bash
    set -euo pipefail
    if [ ! -x "{{FHIR_BIN}}" ]; then
        echo "skip: hfs not staged at {{FHIR_BIN}} (run \`just fetch-fhir\` first)"
        exit 0
    fi
    just fhir-server-up
    cleanup() { just fhir-server-down >/dev/null 2>&1 || true; }
    trap cleanup EXIT
    base="http://127.0.0.1:{{FHIR_PORT}}/fhir/R5"
    fixture="{{ justfile_directory() }}/data/fhir/icu-monitor-02.observations.json"
    [ -f "$fixture" ] || { echo "fixture missing: $fixture"; exit 1; }
    # Round-trip every entry: POST → capture server-assigned id → GET → assert.
    n=$(uv run python -c "import json; print(len(json.load(open('$fixture'))['entry']))")
    echo "→ smoke: round-tripping $n Observations through $base"
    for i in $(seq 0 $((n-1))); do
        obs=$(uv run python -c "import json; print(json.dumps(json.load(open('$fixture'))['entry'][$i]['resource']))")
        loc=$(curl -fsS -o /dev/null -w '%{redirect_url}\n' \
            -X POST "$base/Observation" \
            -H 'Content-Type: application/fhir+json' \
            -H 'Accept: application/fhir+json' \
            --data "$obs" || true)
        # Some servers reply with a 201 + Location header; others embed the
        # assigned id in the response body. Fall back to a body-id parse.
        if [ -z "$loc" ]; then
            body=$(curl -fsS -X POST "$base/Observation" \
                -H 'Content-Type: application/fhir+json' \
                -H 'Accept: application/fhir+json' \
                --data "$obs")
            assigned=$(printf '%s' "$body" | uv run python -c \
                "import json, sys; print(json.loads(sys.stdin.read()).get('id', ''))")
            [ -n "$assigned" ] || { echo "smoke fail: server did not assign an id"; exit 1; }
            curl -fsS "$base/Observation/$assigned" -o /dev/null \
                -H 'Accept: application/fhir+json' || \
                { echo "smoke fail: GET /Observation/$assigned"; exit 1; }
            echo "  ✓ entry $i → id=$assigned"
        else
            assigned=$(echo "$loc" | sed 's|.*/Observation/\([^/]*\)/.*|\1|')
            curl -fsS "$base/Observation/$assigned" -o /dev/null \
                -H 'Accept: application/fhir+json' || \
                { echo "smoke fail: GET $loc"; exit 1; }
            echo "  ✓ entry $i → id=$assigned"
        fi
    done
    echo "✓ fhir-smoke: $n Observations round-tripped through $base"

# End-to-end FHIR R5 Subscription notification → harness ingest smoke
# (Task 10.2 close-out gate). Boots the standalone Python harness
# service in the background, POSTs the canonical icu-monitor-02
# Bundle wrapped as a FHIR R5 Subscriptions Backport
# `subscription-notification` Bundle (entry[0] = SubscriptionStatus)
# to /v1/fhir/notification, and asserts the projected
# ClinicalTelemetryPayload matches the locked LOINC / UCUM contract
# (ADR-025 §4). Decoupled from hfs's actual subscription delivery —
# v0.1.47's R5 Subscription support is unverified, so the smoke
# exercises the harness side end-to-end and treats the live FHIR
# server delivery as 10.4 close-out scope. No external binaries
# required (python is always present per env-verify).
fhir-pipeline-smoke:
    #!/usr/bin/env bash
    set -euo pipefail
    repo="{{ justfile_directory() }}"
    fixture="$repo/data/fhir/icu-monitor-02.observations.json"
    [ -f "$fixture" ] || { echo "fixture missing: $fixture"; exit 1; }
    mkdir -p target
    pid_file="$repo/target/cds-harness-fhir-smoke.pid"
    log_file="$repo/target/cds-harness-fhir-smoke.log"
    pick_port() { python3 -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1]);s.close()'; }
    port=$(pick_port)
    cleanup() {
        if [ -f "$pid_file" ]; then
            pid=$(cat "$pid_file")
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
            rm -f "$pid_file"
        fi
    }
    trap cleanup EXIT INT TERM
    CDS_HARNESS_HOST=127.0.0.1 CDS_HARNESS_PORT=$port \
        nohup uv run python -m cds_harness.service \
        > "$log_file" 2>&1 < /dev/null &
    echo $! > "$pid_file"
    echo "→ harness boot: pid=$(cat "$pid_file") port=$port log=$log_file"
    healthz="http://127.0.0.1:$port/healthz"
    notify="http://127.0.0.1:$port/v1/fhir/notification"
    for _ in $(seq 1 80); do
        if curl -sf "$healthz" >/dev/null; then break; fi
        sleep 0.25
    done
    if ! curl -sf "$healthz" >/dev/null; then
        echo "smoke fail: harness /healthz never came up"
        tail -40 "$log_file" || true
        exit 1
    fi
    # Wrap the canonical collection Bundle as a subscription-notification.
    smoke_runner="$repo/python/scripts/fhir_pipeline_smoke.py"
    [ -f "$smoke_runner" ] || { echo "missing $smoke_runner"; exit 1; }
    uv run python "$smoke_runner" "$fixture" "$notify"

# End-to-end FHIRcast STU3 collaborative-session events → harness session
# registry smoke (Task 10.3 close-out gate). Boots the standalone Python
# harness service in the background, POSTs a synthetic patient-open
# followed by patient-close (raw FHIRcast notification shape, not
# CloudEvents-wrapped — the route accepts both per ADR-026 §7), and
# asserts that GET /v1/fhircast/sessions reflects the registry
# transitions. Decoupled from a live FHIRcast Hub + Dapr cluster — the
# harness-side end-to-end exercise is sufficient for 10.3; live Hub →
# Dapr → harness delivery is 10.4 / 11.4 close-out scope (ADR-026 §11).
# No external binaries required (python is always present per
# env-verify).
fhircast-smoke:
    #!/usr/bin/env bash
    set -euo pipefail
    repo="{{ justfile_directory() }}"
    mkdir -p target
    pid_file="$repo/target/cds-harness-fhircast-smoke.pid"
    log_file="$repo/target/cds-harness-fhircast-smoke.log"
    pick_port() { python3 -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1]);s.close()'; }
    port=$(pick_port)
    cleanup() {
        if [ -f "$pid_file" ]; then
            pid=$(cat "$pid_file")
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
            rm -f "$pid_file"
        fi
    }
    trap cleanup EXIT INT TERM
    CDS_HARNESS_HOST=127.0.0.1 CDS_HARNESS_PORT=$port \
        nohup uv run python -m cds_harness.service \
        > "$log_file" 2>&1 < /dev/null &
    echo $! > "$pid_file"
    echo "→ harness boot: pid=$(cat "$pid_file") port=$port log=$log_file"
    healthz="http://127.0.0.1:$port/healthz"
    base="http://127.0.0.1:$port"
    for _ in $(seq 1 80); do
        if curl -sf "$healthz" >/dev/null; then break; fi
        sleep 0.25
    done
    if ! curl -sf "$healthz" >/dev/null; then
        echo "smoke fail: harness /healthz never came up"
        tail -40 "$log_file" || true
        exit 1
    fi
    smoke_runner="$repo/python/scripts/fhircast_smoke.py"
    [ -f "$smoke_runner" ] || { echo "missing $smoke_runner"; exit 1; }
    uv run python "$smoke_runner" "$base"

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
# Phase 1 cloud foundation (Task 11.1) — kind + kubectl + helm + Dapr helm chart
# =============================================================================
# Per ADR-028: kind v0.31.0 (defaults to kindest/node v1.35.0), kubectl
# v1.35.4 (matches the kindest/node minor; the upstream ±1 minor skew
# guarantee is preserved), helm v3.20.3 (parallel-stable v3 line —
# Helm 4.x exists but the Dapr 1.17 chart is a v3-format chart so we
# stay on the v3 line). Binaries staged under .bin/ via `fetch-cloud`;
# the recipe is opt-in (NOT in `bootstrap`) — mirrors `fetch-fhir`'s
# precedent for the heavy / cloud-specific tooling.
#
# Phase parity. The slim self-hosted recipes (`dapr-cluster-up`,
# `dapr-pipeline`, `fhir-axis-smoke`) stay as the fast local-dev path;
# the cloud axis is the *additional* deployment target. Container
# images + apply -f k8s/cds-*.yaml + an end-to-end cluster smoke land
# at Task 11.2.

KIND_VERSION         := env_var_or_default('KIND_VERSION',         'v0.31.0')
KUBECTL_VERSION      := env_var_or_default('KUBECTL_VERSION',      'v1.35.4')
HELM_VERSION         := env_var_or_default('HELM_VERSION',         'v3.20.3')
DAPR_HELM_VERSION    := env_var_or_default('DAPR_HELM_VERSION',    '1.17')
KIND_CLUSTER_NAME    := env_var_or_default('KIND_CLUSTER_NAME',    'cds')
K8S_DIR              := justfile_directory() + "/k8s"
KIND_CLUSTER_CONFIG  := K8S_DIR + "/kind-cluster.yaml"
KUBECTL_CONTEXT      := env_var_or_default('KUBECTL_CONTEXT',      'kind-' + KIND_CLUSTER_NAME)

# Composite — stages kind + kubectl + helm under .bin/. NOT in
# `bootstrap` (heavy + cloud-specific; mirrors `fetch-fhir`).
fetch-cloud: fetch-kind fetch-kubectl fetch-helm
    @echo "✓ kind + kubectl + helm staged under .bin/"

# Stage the kind binary into .bin/kind. Skips if already present.
fetch-kind:
    #!/usr/bin/env bash
    set -euo pipefail
    mkdir -p "{{ justfile_directory() }}/.bin"
    if [ -x "{{ justfile_directory() }}/.bin/kind" ]; then
        echo "kind already present in .bin/"
        "{{ justfile_directory() }}/.bin/kind" version | head -1
        exit 0
    fi
    echo "→ fetching kind {{KIND_VERSION}} (linux-amd64)"
    url="https://github.com/kubernetes-sigs/kind/releases/download/{{KIND_VERSION}}/kind-linux-amd64"
    tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
    curl -fsSL "$url" -o "$tmp/kind"
    install -m 0755 "$tmp/kind" "{{ justfile_directory() }}/.bin/kind"
    "{{ justfile_directory() }}/.bin/kind" version | head -1

# Stage the kubectl binary into .bin/kubectl. Skips if already present.
fetch-kubectl:
    #!/usr/bin/env bash
    set -euo pipefail
    mkdir -p "{{ justfile_directory() }}/.bin"
    if [ -x "{{ justfile_directory() }}/.bin/kubectl" ]; then
        echo "kubectl already present in .bin/"
        "{{ justfile_directory() }}/.bin/kubectl" version --client=true | head -1
        exit 0
    fi
    echo "→ fetching kubectl {{KUBECTL_VERSION}} (linux/amd64)"
    url="https://dl.k8s.io/release/{{KUBECTL_VERSION}}/bin/linux/amd64/kubectl"
    tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
    curl -fsSL "$url" -o "$tmp/kubectl"
    install -m 0755 "$tmp/kubectl" "{{ justfile_directory() }}/.bin/kubectl"
    "{{ justfile_directory() }}/.bin/kubectl" version --client=true | head -1

# Stage the helm binary into .bin/helm. Skips if already present.
fetch-helm:
    #!/usr/bin/env bash
    set -euo pipefail
    mkdir -p "{{ justfile_directory() }}/.bin"
    if [ -x "{{ justfile_directory() }}/.bin/helm" ]; then
        echo "helm already present in .bin/"
        "{{ justfile_directory() }}/.bin/helm" version --short
        exit 0
    fi
    echo "→ fetching helm {{HELM_VERSION}} (linux-amd64)"
    asset="helm-{{HELM_VERSION}}-linux-amd64.tar.gz"
    url="https://get.helm.sh/${asset}"
    tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
    curl -fsSL "$url" -o "$tmp/helm.tgz"
    tar -xzf "$tmp/helm.tgz" -C "$tmp"
    bin_path=$(find "$tmp" -type f -name helm -perm -u+x | head -1)
    [ -n "$bin_path" ] || { echo "no executable 'helm' in tarball"; exit 1; }
    install -m 0755 "$bin_path" "{{ justfile_directory() }}/.bin/helm"
    "{{ justfile_directory() }}/.bin/helm" version --short

# Spin up the kind cluster from k8s/kind-cluster.yaml. Idempotent —
# noop if the named cluster already exists.
kind-up:
    #!/usr/bin/env bash
    set -euo pipefail
    [ -x "{{ justfile_directory() }}/.bin/kind" ] || \
        { echo "kind missing — run \`just fetch-cloud\`"; exit 1; }
    if "{{ justfile_directory() }}/.bin/kind" get clusters 2>/dev/null | grep -qx "{{KIND_CLUSTER_NAME}}"; then
        echo "kind cluster '{{KIND_CLUSTER_NAME}}' already up"
        exit 0
    fi
    echo "→ creating kind cluster '{{KIND_CLUSTER_NAME}}'"
    "{{ justfile_directory() }}/.bin/kind" create cluster \
        --name {{KIND_CLUSTER_NAME}} \
        --config "{{KIND_CLUSTER_CONFIG}}" \
        --wait 5m
    echo "✓ kind cluster '{{KIND_CLUSTER_NAME}}' up"

# Tear down the kind cluster. Idempotent — noop if the named cluster
# is absent.
kind-down:
    #!/usr/bin/env bash
    set -euo pipefail
    [ -x "{{ justfile_directory() }}/.bin/kind" ] || \
        { echo "kind missing — nothing to tear down"; exit 0; }
    if ! "{{ justfile_directory() }}/.bin/kind" get clusters 2>/dev/null | grep -qx "{{KIND_CLUSTER_NAME}}"; then
        echo "kind cluster '{{KIND_CLUSTER_NAME}}' not present"
        exit 0
    fi
    "{{ justfile_directory() }}/.bin/kind" delete cluster --name {{KIND_CLUSTER_NAME}}
    echo "✓ kind cluster '{{KIND_CLUSTER_NAME}}' down"

# Print kind cluster + node + pod status. Skips loudly if no cluster.
kind-status:
    #!/usr/bin/env bash
    set -euo pipefail
    [ -x "{{ justfile_directory() }}/.bin/kind" ] || \
        { echo "kind missing — run \`just fetch-cloud\`"; exit 0; }
    [ -x "{{ justfile_directory() }}/.bin/kubectl" ] || \
        { echo "kubectl missing — run \`just fetch-cloud\`"; exit 0; }
    if ! "{{ justfile_directory() }}/.bin/kind" get clusters 2>/dev/null | grep -qx "{{KIND_CLUSTER_NAME}}"; then
        echo "kind cluster '{{KIND_CLUSTER_NAME}}' not present"
        exit 0
    fi
    echo "::: kind cluster '{{KIND_CLUSTER_NAME}}' :::"
    "{{ justfile_directory() }}/.bin/kubectl" \
        --context "{{KUBECTL_CONTEXT}}" \
        get nodes -o wide
    echo
    echo "::: pods (all namespaces) :::"
    "{{ justfile_directory() }}/.bin/kubectl" \
        --context "{{KUBECTL_CONTEXT}}" \
        get pods -A

# Install Dapr 1.17 control plane via helm. Idempotent — `--install`
# behaves as install or upgrade. Targets the kind cluster context;
# override KUBECTL_CONTEXT to retarget. Requires `kind-up` first.
dapr-helm-install:
    #!/usr/bin/env bash
    set -euo pipefail
    [ -x "{{ justfile_directory() }}/.bin/helm" ] || \
        { echo "helm missing — run \`just fetch-cloud\`"; exit 1; }
    [ -x "{{ justfile_directory() }}/.bin/kubectl" ] || \
        { echo "kubectl missing — run \`just fetch-cloud\`"; exit 1; }
    "{{ justfile_directory() }}/.bin/helm" repo add dapr https://dapr.github.io/helm-charts/ 2>/dev/null || true
    "{{ justfile_directory() }}/.bin/helm" repo update dapr
    "{{ justfile_directory() }}/.bin/helm" upgrade --install dapr dapr/dapr \
        --kube-context "{{KUBECTL_CONTEXT}}" \
        --version {{DAPR_HELM_VERSION}} \
        --namespace dapr-system \
        --create-namespace \
        --wait \
        --timeout 5m
    echo "✓ Dapr {{DAPR_HELM_VERSION}} installed under context {{KUBECTL_CONTEXT}}"
    "{{ justfile_directory() }}/.bin/kubectl" \
        --context "{{KUBECTL_CONTEXT}}" \
        -n dapr-system \
        get pods

# Validate every k8s/*.yaml manifest with `kubectl apply --dry-run=client`.
# Pure offline check (no live cluster needed). Foundation gate (Task 11.1).
k8s-validate:
    #!/usr/bin/env bash
    set -euo pipefail
    [ -x "{{ justfile_directory() }}/.bin/kubectl" ] || \
        { echo "kubectl missing — run \`just fetch-cloud\`"; exit 1; }
    fail=0
    while IFS= read -r -d '' f; do
        if "{{ justfile_directory() }}/.bin/kubectl" apply --dry-run=client \
            --validate=false -f "$f" >/dev/null 2>&1; then
            echo "  ✓ $f"
        else
            echo "  ✗ $f" >&2
            "{{ justfile_directory() }}/.bin/kubectl" apply --dry-run=client \
                --validate=false -f "$f" || true
            fail=1
        fi
    done < <(find "{{K8S_DIR}}" -type f -name '*.yaml' -print0 | sort -z)
    [ "$fail" = "0" ] || { echo "k8s manifest validation FAILED"; exit 1; }
    echo "✓ k8s manifests valid (client-side dry-run)"

# Alias for kind-down — tears down the cluster (helm install vanishes
# with it). Provided for naming parity with `dapr-clean` / `fhir-clean`.
cloud-clean: kind-down
    @echo "✓ cloud clean"

# =============================================================================
# Phase 1 cloud service deployment (Task 11.2) — image build + load + apply
# =============================================================================
# Per ADR-029. Five recipes form the lifecycle:
#   - cloud-build  : build all three cds-* container images locally
#   - cloud-load   : `kind load docker-image` for the three images
#   - cloud-up     : kubectl apply -f k8s/{namespaces, dapr-config,
#                    dapr-components/, cds-*.yaml}; wait for rollout
#   - cloud-down   : delete the workloads + components + config + namespace
#                    (cluster preserved — use `kind-down` to destroy it)
#   - cloud-status : kubectl get pods/svc -n cds
#   - cloud-smoke  : in-cluster `kubectl run` of curlimages/curl probing
#                    /healthz on cds-{harness,kernel} + / on cds-frontend
#                    via in-cluster Service DNS. Foundation gate (Task 11.2);
#                    end-to-end `contradictory-bound` UNSAT lands at 11.4.
#
# Each recipe is gated on its required tool ($DOCKER for build; .bin/kind
# for load; .bin/kubectl for up/down/status/smoke) and exits cleanly with a
# loud notice if the tool is missing — same precedent as `dapr-helm-install`
# / `kind-up` (Task 11.1). $DOCKER defaults to `docker`; override `DOCKER=podman`
# when podman is preferred (the build / load surface is identical between them).

DOCKER_DIR              := justfile_directory() + "/docker"
CDS_HARNESS_IMAGE       := env_var_or_default('CDS_HARNESS_IMAGE',  'cds-harness:dev')
CDS_KERNEL_IMAGE        := env_var_or_default('CDS_KERNEL_IMAGE',   'cds-kernel:dev')
CDS_FRONTEND_IMAGE      := env_var_or_default('CDS_FRONTEND_IMAGE', 'cds-frontend:dev')
CDS_NAMESPACE           := env_var_or_default('CDS_NAMESPACE',      'cds')
DOCKER                  := env_var_or_default('DOCKER',             'docker')

# Build all three cds-* images. Gated on $DOCKER (default `docker`).
# Requires .bin/{z3,cvc5} for the cds-kernel image's solver layer
# (`just fetch-bins` if missing).
cloud-build:
    #!/usr/bin/env bash
    set -euo pipefail
    if ! command -v "{{DOCKER}}" >/dev/null 2>&1; then
        echo "{{DOCKER}} missing — install Docker or podman (alias DOCKER=podman) and re-run"
        exit 1
    fi
    if [ ! -x "{{ justfile_directory() }}/.bin/z3" ] || [ ! -x "{{ justfile_directory() }}/.bin/cvc5" ]; then
        echo ".bin/z3 + .bin/cvc5 missing — run \`just fetch-bins\` (cds-kernel image needs them)"
        exit 1
    fi
    echo "→ building {{CDS_HARNESS_IMAGE}}"
    "{{DOCKER}}" build -t "{{CDS_HARNESS_IMAGE}}" \
        -f "{{DOCKER_DIR}}/cds-harness.Dockerfile" \
        "{{ justfile_directory() }}"
    echo "→ building {{CDS_KERNEL_IMAGE}}"
    "{{DOCKER}}" build -t "{{CDS_KERNEL_IMAGE}}" \
        -f "{{DOCKER_DIR}}/cds-kernel.Dockerfile" \
        "{{ justfile_directory() }}"
    echo "→ building {{CDS_FRONTEND_IMAGE}}"
    "{{DOCKER}}" build -t "{{CDS_FRONTEND_IMAGE}}" \
        -f "{{DOCKER_DIR}}/cds-frontend.Dockerfile" \
        "{{ justfile_directory() }}"
    echo "✓ images built: {{CDS_HARNESS_IMAGE}} {{CDS_KERNEL_IMAGE}} {{CDS_FRONTEND_IMAGE}}"

# Load the three locally-built images into the kind cluster. Idempotent —
# kind load is a no-op if the digest already matches. Requires `kind-up` first.
cloud-load:
    #!/usr/bin/env bash
    set -euo pipefail
    [ -x "{{ justfile_directory() }}/.bin/kind" ] || \
        { echo "kind missing — run \`just fetch-cloud\`"; exit 1; }
    if ! "{{ justfile_directory() }}/.bin/kind" get clusters 2>/dev/null | grep -qx "{{KIND_CLUSTER_NAME}}"; then
        echo "kind cluster '{{KIND_CLUSTER_NAME}}' not present — run \`just kind-up\`"
        exit 1
    fi
    for img in "{{CDS_HARNESS_IMAGE}}" "{{CDS_KERNEL_IMAGE}}" "{{CDS_FRONTEND_IMAGE}}"; do
        echo "→ kind load docker-image $img"
        "{{ justfile_directory() }}/.bin/kind" load docker-image \
            --name "{{KIND_CLUSTER_NAME}}" "$img"
    done
    echo "✓ images loaded into kind cluster '{{KIND_CLUSTER_NAME}}'"

# Apply namespace + Dapr Configuration + Components + the three workload
# manifests. Waits for each Deployment to roll out (timeout 5m). Requires
# kubectl, an active kind cluster, and Dapr installed (`just dapr-helm-install`).
cloud-up:
    #!/usr/bin/env bash
    set -euo pipefail
    [ -x "{{ justfile_directory() }}/.bin/kubectl" ] || \
        { echo "kubectl missing — run \`just fetch-cloud\`"; exit 1; }
    KCTL=( "{{ justfile_directory() }}/.bin/kubectl" --context "{{KUBECTL_CONTEXT}}" )
    echo "→ applying namespace + Dapr config + components"
    "${KCTL[@]}" apply -f "{{K8S_DIR}}/namespaces.yaml"
    "${KCTL[@]}" apply -f "{{K8S_DIR}}/dapr-config.yaml"
    "${KCTL[@]}" apply -f "{{K8S_DIR}}/dapr-components/"
    echo "→ applying workloads"
    "${KCTL[@]}" apply -f "{{K8S_DIR}}/cds-harness.yaml"
    "${KCTL[@]}" apply -f "{{K8S_DIR}}/cds-kernel.yaml"
    "${KCTL[@]}" apply -f "{{K8S_DIR}}/cds-frontend.yaml"
    echo "→ waiting for rollouts (timeout 5m each)"
    for app in cds-harness cds-kernel cds-frontend; do
        "${KCTL[@]}" -n "{{CDS_NAMESPACE}}" rollout status \
            deployment/"$app" --timeout=5m
    done
    echo "✓ cloud up — three deployments ready in namespace '{{CDS_NAMESPACE}}'"

# Tear down workloads + components + Dapr config + namespace. Cluster
# preserved (use `just kind-down` to destroy the cluster itself).
cloud-down:
    #!/usr/bin/env bash
    set -euo pipefail
    [ -x "{{ justfile_directory() }}/.bin/kubectl" ] || \
        { echo "kubectl missing — nothing to tear down"; exit 0; }
    KCTL=( "{{ justfile_directory() }}/.bin/kubectl" --context "{{KUBECTL_CONTEXT}}" )
    for f in cds-frontend.yaml cds-kernel.yaml cds-harness.yaml; do
        "${KCTL[@]}" delete -f "{{K8S_DIR}}/$f" --ignore-not-found
    done
    "${KCTL[@]}" delete -f "{{K8S_DIR}}/dapr-components/" --ignore-not-found
    "${KCTL[@]}" delete -f "{{K8S_DIR}}/dapr-config.yaml" --ignore-not-found
    "${KCTL[@]}" delete -f "{{K8S_DIR}}/namespaces.yaml" --ignore-not-found
    echo "✓ cloud down — namespace + workloads removed (cluster preserved)"

# Print pod + service inventory in the cds namespace.
cloud-status:
    #!/usr/bin/env bash
    set -euo pipefail
    [ -x "{{ justfile_directory() }}/.bin/kubectl" ] || \
        { echo "kubectl missing — run \`just fetch-cloud\`"; exit 0; }
    KCTL=( "{{ justfile_directory() }}/.bin/kubectl" --context "{{KUBECTL_CONTEXT}}" )
    echo "::: pods in {{CDS_NAMESPACE}} :::"
    "${KCTL[@]}" -n "{{CDS_NAMESPACE}}" get pods -o wide || true
    echo
    echo "::: services in {{CDS_NAMESPACE}} :::"
    "${KCTL[@]}" -n "{{CDS_NAMESPACE}}" get svc || true

# Cluster-side smoke gate (Task 11.2): kubectl-run a transient curl pod
# against /healthz on cds-harness + cds-kernel and / on cds-frontend, all
# via in-cluster Service DNS. Returns non-zero on any probe failure.
# End-to-end `contradictory-bound` UNSAT smoke is Task 11.4's gate.
cloud-smoke:
    #!/usr/bin/env bash
    set -euo pipefail
    [ -x "{{ justfile_directory() }}/.bin/kubectl" ] || \
        { echo "kubectl missing — run \`just fetch-cloud\`"; exit 1; }
    KCTL=( "{{ justfile_directory() }}/.bin/kubectl" --context "{{KUBECTL_CONTEXT}}" )
    fail=0
    for entry in \
        "cds-harness:8081:/healthz" \
        "cds-kernel:8082:/healthz" \
        "cds-frontend:3000:/" ; do
        IFS=":" read -r app port path <<< "$entry"
        url="http://${app}.{{CDS_NAMESPACE}}.svc.cluster.local:${port}${path}"
        echo "→ probing $url"
        if "${KCTL[@]}" -n "{{CDS_NAMESPACE}}" run "cloud-smoke-${app}-$$" \
                --rm --image=curlimages/curl:latest \
                --restart=Never --quiet --attach \
                --command -- curl -fsS --max-time 10 "$url" >/dev/null 2>&1; then
            echo "  ✓ $app"
        else
            echo "  ✗ $app"
            fail=1
        fi
    done
    [ "$fail" = "0" ] || { echo "cloud smoke FAILED"; exit 1; }
    echo "✓ cloud smoke green — three /healthz endpoints responsive"

# =============================================================================
# Phase 1 cloud observability (Task 11.3) — OpenTelemetry Collector +
# kube-prometheus-stack + Dapr metrics scrape + Grafana dashboard
# =============================================================================
# Per ADR-030. Four recipes form the lifecycle:
#   - cloud-observability-up     : helm install otel-collector +
#                                  kube-prometheus-stack into the
#                                  cds-observability namespace, then
#                                  apply k8s/observability/{namespace,
#                                  dapr-podmonitor, grafana-dapr-
#                                  dashboard-cm}.yaml
#   - cloud-observability-down   : helm uninstall both releases,
#                                  delete the cds-observability namespace
#                                  (cluster + Dapr control-plane
#                                  preserved)
#   - cloud-observability-status : kubectl get pods/svc -n cds-observability
#   - cloud-observability-smoke  : in-cluster `kubectl run` of
#                                  curlimages/curl probing the OTel
#                                  Collector + Prometheus + Grafana
#                                  health endpoints via in-cluster
#                                  Service DNS. Foundation gate
#                                  (Task 11.3); end-to-end span
#                                  propagation lands at Task 11.4.
#
# Tooling gates: helm + kubectl from .bin/ (staged via `just fetch-cloud`).
# Helm chart pins are env-overridable for forward-compat.

OBSERVABILITY_DIR             := K8S_DIR + "/observability"
OBSERVABILITY_NAMESPACE       := env_var_or_default('OBSERVABILITY_NAMESPACE',  'cds-observability')
OTEL_COLLECTOR_CHART_VERSION  := env_var_or_default('OTEL_COLLECTOR_CHART_VERSION',  '0.146.1')
KPS_CHART_VERSION             := env_var_or_default('KPS_CHART_VERSION',             '84.5.0')
OTEL_COLLECTOR_RELEASE        := env_var_or_default('OTEL_COLLECTOR_RELEASE',        'otel-collector')
KPS_RELEASE                   := env_var_or_default('KPS_RELEASE',                   'kube-prometheus-stack')

# Helm install both releases + apply the PodMonitor / dashboard
# manifests. Idempotent — `helm upgrade --install` handles install or
# upgrade. Requires kubectl + helm + an active kind cluster + Dapr
# already installed.
cloud-observability-up:
    #!/usr/bin/env bash
    set -euo pipefail
    [ -x "{{ justfile_directory() }}/.bin/helm" ] || \
        { echo "helm missing — run \`just fetch-cloud\`"; exit 1; }
    [ -x "{{ justfile_directory() }}/.bin/kubectl" ] || \
        { echo "kubectl missing — run \`just fetch-cloud\`"; exit 1; }
    HELM=( "{{ justfile_directory() }}/.bin/helm" )
    KCTL=( "{{ justfile_directory() }}/.bin/kubectl" --context "{{KUBECTL_CONTEXT}}" )
    echo "→ applying cds-observability namespace"
    "${KCTL[@]}" apply -f "{{OBSERVABILITY_DIR}}/namespace.yaml"
    echo "→ helm repo refresh"
    "${HELM[@]}" repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts 2>/dev/null || true
    "${HELM[@]}" repo add prometheus-community https://prometheus-community.github.io/helm-charts 2>/dev/null || true
    "${HELM[@]}" repo update open-telemetry prometheus-community
    echo "→ helm upgrade --install {{OTEL_COLLECTOR_RELEASE}} (chart {{OTEL_COLLECTOR_CHART_VERSION}})"
    "${HELM[@]}" upgrade --install {{OTEL_COLLECTOR_RELEASE}} \
        open-telemetry/opentelemetry-collector \
        --kube-context "{{KUBECTL_CONTEXT}}" \
        --version {{OTEL_COLLECTOR_CHART_VERSION}} \
        --namespace {{OBSERVABILITY_NAMESPACE}} \
        --values "{{OBSERVABILITY_DIR}}/otel-collector-values.yaml" \
        --wait \
        --timeout 5m
    echo "→ helm upgrade --install {{KPS_RELEASE}} (chart {{KPS_CHART_VERSION}})"
    "${HELM[@]}" upgrade --install {{KPS_RELEASE}} \
        prometheus-community/kube-prometheus-stack \
        --kube-context "{{KUBECTL_CONTEXT}}" \
        --version {{KPS_CHART_VERSION}} \
        --namespace {{OBSERVABILITY_NAMESPACE}} \
        --values "{{OBSERVABILITY_DIR}}/kube-prometheus-stack-values.yaml" \
        --wait \
        --timeout 10m
    echo "→ applying PodMonitors + Grafana dashboard ConfigMap"
    "${KCTL[@]}" apply -f "{{OBSERVABILITY_DIR}}/dapr-podmonitor.yaml"
    "${KCTL[@]}" apply -f "{{OBSERVABILITY_DIR}}/grafana-dapr-dashboard-cm.yaml"
    echo "✓ cloud observability up — namespace {{OBSERVABILITY_NAMESPACE}}"

# Helm uninstall both releases + delete the namespace (clears any
# leftover PVCs + ConfigMaps). Cluster + Dapr control plane preserved.
cloud-observability-down:
    #!/usr/bin/env bash
    set -euo pipefail
    [ -x "{{ justfile_directory() }}/.bin/kubectl" ] || \
        { echo "kubectl missing — nothing to tear down"; exit 0; }
    HELM=( "{{ justfile_directory() }}/.bin/helm" )
    KCTL=( "{{ justfile_directory() }}/.bin/kubectl" --context "{{KUBECTL_CONTEXT}}" )
    if [ -x "{{ justfile_directory() }}/.bin/helm" ]; then
        "${HELM[@]}" uninstall {{KPS_RELEASE}} \
            --kube-context "{{KUBECTL_CONTEXT}}" \
            --namespace {{OBSERVABILITY_NAMESPACE}} \
            --ignore-not-found 2>/dev/null || true
        "${HELM[@]}" uninstall {{OTEL_COLLECTOR_RELEASE}} \
            --kube-context "{{KUBECTL_CONTEXT}}" \
            --namespace {{OBSERVABILITY_NAMESPACE}} \
            --ignore-not-found 2>/dev/null || true
    fi
    "${KCTL[@]}" delete -f "{{OBSERVABILITY_DIR}}/grafana-dapr-dashboard-cm.yaml" --ignore-not-found
    "${KCTL[@]}" delete -f "{{OBSERVABILITY_DIR}}/dapr-podmonitor.yaml" --ignore-not-found
    "${KCTL[@]}" delete -f "{{OBSERVABILITY_DIR}}/namespace.yaml" --ignore-not-found
    echo "✓ cloud observability down — namespace {{OBSERVABILITY_NAMESPACE}} removed"

# Print pod + service inventory in the cds-observability namespace.
cloud-observability-status:
    #!/usr/bin/env bash
    set -euo pipefail
    [ -x "{{ justfile_directory() }}/.bin/kubectl" ] || \
        { echo "kubectl missing — run \`just fetch-cloud\`"; exit 0; }
    KCTL=( "{{ justfile_directory() }}/.bin/kubectl" --context "{{KUBECTL_CONTEXT}}" )
    echo "::: pods in {{OBSERVABILITY_NAMESPACE}} :::"
    "${KCTL[@]}" -n "{{OBSERVABILITY_NAMESPACE}}" get pods -o wide || true
    echo
    echo "::: services in {{OBSERVABILITY_NAMESPACE}} :::"
    "${KCTL[@]}" -n "{{OBSERVABILITY_NAMESPACE}}" get svc || true

# In-cluster smoke (Task 11.3): kubectl-run a transient curl pod
# against /healthz on the OTel Collector + Prometheus + Grafana via
# in-cluster Service DNS. Returns non-zero on any probe failure.
# Live span propagation + dashboard query smoke is Task 11.4's gate.
cloud-observability-smoke:
    #!/usr/bin/env bash
    set -euo pipefail
    [ -x "{{ justfile_directory() }}/.bin/kubectl" ] || \
        { echo "kubectl missing — run \`just fetch-cloud\`"; exit 1; }
    KCTL=( "{{ justfile_directory() }}/.bin/kubectl" --context "{{KUBECTL_CONTEXT}}" )
    fail=0
    for entry in \
        "{{OTEL_COLLECTOR_RELEASE}}-opentelemetry-collector:13133:/" \
        "{{KPS_RELEASE}}-prometheus:9090:/-/healthy" \
        "{{KPS_RELEASE}}-grafana:80:/api/health" ; do
        IFS=":" read -r svc port path <<< "$entry"
        url="http://${svc}.{{OBSERVABILITY_NAMESPACE}}.svc.cluster.local:${port}${path}"
        echo "→ probing $url"
        if "${KCTL[@]}" -n "{{OBSERVABILITY_NAMESPACE}}" run "obs-smoke-${svc}-$$" \
                --rm --image=curlimages/curl:latest \
                --restart=Never --quiet --attach \
                --command -- curl -fsS --max-time 10 "$url" >/dev/null 2>&1; then
            echo "  ✓ $svc"
        else
            echo "  ✗ $svc"
            fail=1
        fi
    done
    [ "$fail" = "0" ] || { echo "cloud observability smoke FAILED"; exit 1; }
    echo "✓ cloud observability smoke green — collector + prometheus + grafana responsive"

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
# FHIR axis end-to-end smoke (Task 10.4 close-out)
# =============================================================================
# `just fhir-axis-smoke` brings up placement + scheduler + the cds-harness
# and cds-kernel daprd sidecars + a workflow runner sidecar, then drives
# the canonical `data/fhir/icu-monitor-02.observations.json` collection
# Bundle through the FHIR boundary:
#
#   1. POST `/v1/fhir/notification`  → ClinicalTelemetryPayload (10.2)
#   2. POST `/v1/fhircast/patient-open` → session registry (10.3)
#   3. Schedule the canonical Workflow (ingest→translate→deduce→solve→recheck)
#   4. Verify `trace.sat == false`, `recheck.ok == true`
#   5. Verify every `trace.muc` entry maps back to an Atom span (C4)
#   6. POST `/v1/fhircast/patient-close` → session registry teardown
#
# Mirrors `dapr-pipeline` topology; the only delta is that the workflow
# runner uses the `run-fhir-pipeline` subcommand, which routes through
# daprd's HTTP service-invocation port (`DAPR_HTTP_PORT`) rather than
# reading a pre-baked envelope from disk. Per ADR-027 §3-§5.

FHIR_AXIS_BUNDLE     := env_var_or_default('FHIR_AXIS_BUNDLE',     'data/fhir/icu-monitor-02.observations.json')
FHIR_AXIS_GUIDELINE  := env_var_or_default('FHIR_AXIS_GUIDELINE',  'data/guidelines/contradictory-bound.txt')
FHIR_AXIS_DOC_ID     := env_var_or_default('FHIR_AXIS_DOC_ID',     'contradictory-bound')
FHIR_AXIS_TIMEOUT_S  := env_var_or_default('FHIR_AXIS_TIMEOUT_S',  '600')

# End-to-end FHIR axis close-out (Task 10.4 close-out gate). Requires .bin/dapr + slim runtime + .bin/{z3,cvc5} + reachable $CDS_KIMINA_URL.
fhir-axis-smoke:
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
    py_pid="target/fhir-axis-harness.pid"
    py_log="target/fhir-axis-harness.log"
    rs_pid="target/fhir-axis-kernel.pid"
    rs_log="target/fhir-axis-kernel.log"
    wf_pid="target/fhir-axis-workflow.pid"
    wf_log="target/fhir-axis-workflow.log"

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

    # Wait for both /healthz + daprd /v1.0/healthz to flip ready.
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

    # 4. Workflow + FHIR-axis runner sidecar (cds-workflow). The
    # `run-fhir-pipeline` subcommand reads `DAPR_HTTP_PORT` to route
    # /v1/fhir/notification and /v1/fhircast/* through daprd to
    # cds-harness; the dapr SDK's WorkflowRuntime reads `DAPR_GRPC_PORT`.
    nohup "$dapr_cli" run \
        --app-id cds-workflow \
        --dapr-http-port "$wf_http" \
        --dapr-grpc-port "$wf_grpc" \
        --metrics-port "$wf_met" \
        --runtime-path "{{DAPR_INSTALL_DIR}}" \
        --resources-path "{{DAPR_RESOURCES_PATH}}" \
        --config "{{DAPR_CONFIG_PATH}}" \
        --log-level info \
        -- uv run python -m cds_harness.workflow run-fhir-pipeline \
            --fhir-bundle "{{FHIR_AXIS_BUNDLE}}" \
            --guideline "{{FHIR_AXIS_GUIDELINE}}" \
            --doc-id "{{FHIR_AXIS_DOC_ID}}" \
            --kimina-url "$CDS_KIMINA_URL" \
            --z3-path "$repo/.bin/z3" \
            --cvc5-path "$repo/.bin/cvc5" \
            --timeout-s "{{FHIR_AXIS_TIMEOUT_S}}" \
            --assert-unsat \
            --assert-recheck-ok \
        > "$wf_log" 2>&1 < /dev/null &
    wf_runner=$!
    echo $wf_runner > "$wf_pid"

    if wait "$wf_runner"; then
        echo "✓ fhir-axis-smoke complete — see $wf_log for the aggregated envelope"
        exit 0
    else
        rc=$?
        echo "✗ fhir-axis-smoke failed (exit=$rc) — tail of $wf_log:"
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
# Frontend pipeline E2E (Task 9.3)
# =============================================================================
# `just frontend-pipeline-smoke` is the Phase 0 close-out gate. Mirrors
# `frontend-bff-smoke` for cluster + sidecar + adapter-node BFF bring-up
# but exits the Playwright path: the canonical contradictory-bound flow
# is driven through the live UI (`+page.svelte` form → `Run pipeline`
# button), with Playwright asserting the unsat banner + ≥2 MUC entries
# + ≥2 AST nodes highlighted with `data-muc=true` + `recheck-pill`
# data-state == ok. Per ADR-022 §4.

# End-to-end Phase 0 visualizer + Playwright gate (Task 9.3 close-out). Requires .bin/dapr + slim runtime + .bin/{z3,cvc5} + reachable $CDS_KIMINA_URL + bun in $PATH.
frontend-pipeline-smoke:
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

    cargo build --bin cds-kernel-service
    ( cd "$repo/frontend" && bun install >/dev/null && bun run build >/dev/null )
    ( cd "$repo/frontend" && bunx playwright install chromium >/dev/null )

    mkdir -p target

    py_pid="target/pipeline-smoke-harness.pid"; py_log="target/pipeline-smoke-harness.log"
    rs_pid="target/pipeline-smoke-kernel.pid";  rs_log="target/pipeline-smoke-kernel.log"
    bff_pid="target/pipeline-smoke-bff.pid";    bff_log="target/pipeline-smoke-bff.log"

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

    DAPR_HTTP_PORT_HARNESS=$py_http DAPR_HTTP_PORT_KERNEL=$rs_http \
    PORT=$bff_port HOST=127.0.0.1 \
    nohup bun "$repo/frontend/build/index.js" > "$bff_log" 2>&1 < /dev/null &
    echo $! > "$bff_pid"
    wait_ready "http://127.0.0.1:${bff_port}/" 60

    echo "→ Driving Playwright pipeline E2E against http://127.0.0.1:${bff_port}"
    cd "$repo/frontend" && \
        CDS_E2E_BASE_URL="http://127.0.0.1:${bff_port}" \
        bunx playwright test e2e/pipeline.e2e.ts --reporter=list

    echo "✓ frontend-pipeline-smoke complete"

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
