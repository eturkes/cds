"""Foundation tests for the Phase 1 ZK kernel scaffold (Task 12.1, ADR-032).

Validates:
- The `crates/zk_kernel/` directory carries the expected manifest +
  module hierarchy (lib.rs, errors.rs, witness.rs, prove.rs, verify.rs).
- The Cargo workspace registers `crates/zk_kernel` alongside
  `crates/kernel`.
- The crate manifest declares the locked `zk-kernel` package name +
  the description references Risc0 + Phase 1 / Task 12.1.
- The `zk-kernel` crate has NO `risc0-zkvm` dep at Task 12.1 (per
  ADR-032 §3 + §8: heavy dep deferred to first kernel-side consumer
  at Task 12.2).
- The library declares the locked toolchain constants (`ZK_TOOLCHAIN
  = "risc0"`, `ZK_TOOLCHAIN_VERSION` on the v3.x line, `PHASE = 1`).
- The Justfile registers the new `fetch-zk` / `zk-status` /
  `zk-stub-check` recipes + the `ZK_TOOLCHAIN` / `ZK_TOOLCHAIN_VERSION`
  constants + the `env-verify` line for `.bin/.zk/`.
- ADR-032 is present in the Architecture Decision Log + carries the
  expected section headings.
- `Plan.md` row 12.1 is marked DONE + carries the ADR-032 cross-ref.
- `README.md` row 12.1 is marked DONE + carries the ADR-032 cross-ref.
- `Memory_Scratchpad.md` active-task pointer is advanced to "Task
  12.2 next up".

This is a pure offline test — no Risc0 / rzup / SP1 / cargo
toolchain calls. The cargo gate (`just zk-stub-check`) is the
companion live gate — runs `cargo check --package zk-kernel` +
`cargo test --package zk-kernel --lib` (13 inline unit tests).
"""

from __future__ import annotations

import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ZK_KERNEL_DIR = REPO_ROOT / "crates" / "zk_kernel"
ZK_KERNEL_CARGO_TOML = ZK_KERNEL_DIR / "Cargo.toml"
ZK_KERNEL_LIB_RS = ZK_KERNEL_DIR / "src" / "lib.rs"
ZK_KERNEL_ERRORS_RS = ZK_KERNEL_DIR / "src" / "errors.rs"
ZK_KERNEL_WITNESS_RS = ZK_KERNEL_DIR / "src" / "witness.rs"
ZK_KERNEL_PROVE_RS = ZK_KERNEL_DIR / "src" / "prove.rs"
ZK_KERNEL_VERIFY_RS = ZK_KERNEL_DIR / "src" / "verify.rs"
WORKSPACE_CARGO_TOML = REPO_ROOT / "Cargo.toml"
JUSTFILE = REPO_ROOT / "Justfile"
PLAN_PATH = REPO_ROOT / ".agent" / "Plan.md"
ADL_PATH = REPO_ROOT / ".agent" / "Architecture_Decision_Log.md"
SCRATCHPAD_PATH = REPO_ROOT / ".agent" / "Memory_Scratchpad.md"
README_PATH = REPO_ROOT / "README.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# -----------------------------------------------------------------------------
# Crate scaffolding
# -----------------------------------------------------------------------------


def test_zk_kernel_directory_layout_is_complete() -> None:
    assert ZK_KERNEL_DIR.is_dir(), f"missing {ZK_KERNEL_DIR}"
    for path in (
        ZK_KERNEL_CARGO_TOML,
        ZK_KERNEL_LIB_RS,
        ZK_KERNEL_ERRORS_RS,
        ZK_KERNEL_WITNESS_RS,
        ZK_KERNEL_PROVE_RS,
        ZK_KERNEL_VERIFY_RS,
    ):
        assert path.is_file(), f"missing {path}"


def test_workspace_registers_zk_kernel_member() -> None:
    text = _read(WORKSPACE_CARGO_TOML)
    assert 'members = ["crates/kernel", "crates/zk_kernel"]' in text, (
        "Cargo workspace must list both crates/kernel and crates/zk_kernel"
    )


def test_zk_kernel_cargo_toml_locks_package_name_and_description() -> None:
    text = _read(ZK_KERNEL_CARGO_TOML)
    assert 'name         = "zk-kernel"' in text, (
        "package name must be 'zk-kernel' (kebab-case crate / snake_case lib)"
    )
    assert "Risc0" in text, "manifest description must reference Risc0 (ADR-032 §1 lock)"
    assert "Task 12.1" in text, "manifest description must reference Task 12.1 (foundation)"


def test_zk_kernel_has_no_risc0_zkvm_dep_at_task_12_1() -> None:
    """ADR-032 §3 + §8: `risc0-zkvm` workspace dep deferred to Task 12.2.

    Only inspects the actual [dependencies] / [dev-dependencies] tables —
    explanatory comments are allowed to mention the deferred crates by name.
    """
    with ZK_KERNEL_CARGO_TOML.open("rb") as fh:
        manifest = tomllib.load(fh)
    forbidden = {"risc0-zkvm", "cargo-risczero", "rzup", "sp1-zkvm", "halo2", "plonky2", "plonky3"}
    declared: set[str] = set()
    for table_name in ("dependencies", "dev-dependencies", "build-dependencies"):
        declared.update(manifest.get(table_name, {}).keys())
    offenders = sorted(declared & forbidden)
    detail = (
        "Task 12.1 foundation must NOT pull in zkVM crates yet (deferred per ADR-032 §3 + §8); "
        f"found: {offenders}"
    )
    assert not offenders, detail


def test_zk_kernel_module_hierarchy_declared_in_lib_rs() -> None:
    text = _read(ZK_KERNEL_LIB_RS)
    for module_decl in (
        "pub mod errors;",
        "pub mod prove;",
        "pub mod verify;",
        "pub mod witness;",
    ):
        assert module_decl in text, f"missing module declaration: {module_decl}"


def test_zk_kernel_lib_rs_declares_locked_constants() -> None:
    text = _read(ZK_KERNEL_LIB_RS)
    assert 'pub const ZK_KERNEL_ID: &str = "zk-kernel";' in text
    assert "pub const PHASE: u8 = 1;" in text, (
        "PHASE stays at 1 across Phase 1; flip 1 → 2 at Task 12.4 (ADR-024 §4)"
    )
    assert 'pub const ZK_TOOLCHAIN: &str = "risc0";' in text, "ADR-032 §1 locks Risc0"
    assert 'pub const ZK_TOOLCHAIN_VERSION: &str = "3.0.1";' in text, (
        "ADR-032 §1 pins v3.0.1 (2026 Risc0 latest stable at decision time)"
    )


def test_zk_kernel_post_quantum_invariant_helper_present() -> None:
    text = _read(ZK_KERNEL_LIB_RS)
    assert "fn zk_toolchain_is_post_quantum" in text, (
        "post-quantum invariant must be a queryable helper (ADR-032 §1)"
    )


def test_zk_kernel_unsafe_code_forbidden() -> None:
    text = _read(ZK_KERNEL_LIB_RS)
    assert "#![forbid(unsafe_code)]" in text, "kernel discipline mirrors crates/kernel"


def test_zk_kernel_stubs_return_not_yet_implemented_with_subtask_marker() -> None:
    """Each pending stub's NotYetImplemented arg points at the sub-task that lands the impl.

    Task 12.2 (witness) has now landed (see `test_zk_witness.py` — the
    body returns real bytes, NOT `NotYetImplemented(2)`). Tasks 12.3
    (prove + verify) remain pending; their stubs still carry the
    sub-task-3 marker so downstream callers stay fail-loud.
    """
    prove_text = _read(ZK_KERNEL_PROVE_RS)
    verify_text = _read(ZK_KERNEL_VERIFY_RS)
    assert "ZkError::NotYetImplemented(3)" in prove_text, "prove lands at Task 12.3"
    assert "ZkError::NotYetImplemented(3)" in verify_text, "verify lands at Task 12.3"


# -----------------------------------------------------------------------------
# Justfile registration
# -----------------------------------------------------------------------------


def test_justfile_registers_zk_constants() -> None:
    text = _read(JUSTFILE)
    assert "ZK_TOOLCHAIN          := env_var_or_default('ZK_TOOLCHAIN',         'risc0')" in text
    assert (
        "ZK_TOOLCHAIN_VERSION  := env_var_or_default('ZK_TOOLCHAIN_VERSION', '3.0.1')" in text
    )
    assert 'ZK_INSTALL_DIR        := justfile_directory() + "/.bin/.zk"' in text
    # ADR-034 §2: at Task 12.3a the toolchain entrypoint becomes the
    # sha-pinned `cargo-risczero` binary (the modern Risc0 install
    # surface — `rzup` is still the upstream installer wrapper, but the
    # pinned-tarball pattern targets `cargo-risczero` directly).
    assert 'ZK_CARGO_RISCZERO_BIN := ZK_INSTALL_DIR + "/cargo-risczero"' in text


def test_justfile_registers_zk_recipes() -> None:
    text = _read(JUSTFILE)
    for recipe in ("\nfetch-zk:\n", "\nzk-status:\n", "\nzk-stub-check:\n"):
        assert recipe in text, f"missing Justfile recipe: {recipe.strip()}"


def test_justfile_env_verify_mentions_dot_bin_zk() -> None:
    text = _read(JUSTFILE)
    assert ".bin/.zk/ present (Phase 1 ZK toolchain staged)" in text
    assert ".bin/.zk/ empty (run: just fetch-zk — Phase 1 ZK axis only)" in text


def test_fetch_zk_install_logic_is_wired_at_task_12_3a() -> None:
    """ADR-034 §2 lands the sha-pinned cargo-risczero v3.0.1 download.

    Replaces the original Task 12.1 stub assertion. The fetch-zk
    recipe now mirrors `fetch-fhir`'s sha256-verified tarball pattern —
    the operator-facing "Task 12.2 deliverable" stub message is gone;
    the recipe instead resolves the GitHub release asset URL, verifies
    the pinned digest, extracts the tarball, and installs the
    `cargo-risczero` binary under `.bin/.zk/`. The cross-compiler
    install (`cargo-risczero install`) + guest-program build + prove /
    verify body fills are explicitly flagged as Task 12.3b deliverables
    inside the recipe's tail message.
    """
    text = _read(JUSTFILE)
    assert "Task 12.2 deliverable" not in text, (
        "fetch-zk must no longer carry the Task 12.1 stub message at Task 12.3a (ADR-034 §2)"
    )
    assert 'ZK_SHA256             := env_var_or_default(' in text, (
        "fetch-zk must declare ZK_SHA256 (sha-pinned tarball digest; ADR-034 §2)"
    )
    assert "cargo-risczero-{{ZK_ARCH}}-{{ZK_OS}}.tgz" in text, (
        "fetch-zk must resolve the cargo-risczero GitHub release asset by ARCH/OS"
    )
    assert "github.com/risc0/risc0/releases/download/v{{ZK_TOOLCHAIN_VERSION}}" in text, (
        "fetch-zk must download from the pinned Risc0 GitHub release tag"
    )
    assert "sha256sum" in text, "fetch-zk must verify the tarball digest before installing"
    assert "Task 12.3b" in text, (
        "fetch-zk tail must flag the cargo-risczero install + guest body as Task 12.3b deliverables"
    )


# -----------------------------------------------------------------------------
# ADR / Plan / Scratchpad / README cross-checks
# -----------------------------------------------------------------------------


def test_adr_032_is_present_in_decision_log() -> None:
    text = _read(ADL_PATH)
    assert "## ADR-032 — " in text, "ADR-032 must be appended to the decision log"
    assert "Risc0" in text, "ADR-032 must reference Risc0 (the locked toolchain)"
    assert "ADR-032" in text, "ADR-032 cross-ref required for downstream tracking"


def test_plan_marks_task_12_1_done_with_adr_032() -> None:
    text = _read(PLAN_PATH)
    assert "feat: complete Task 12.1 ZK toolchain selection" in text
    plan_lines = text.splitlines()
    row = next(
        (line for line in plan_lines if line.lstrip().startswith("| 12.1")),
        None,
    )
    assert row is not None, "Plan §8.2 must carry a row for Task 12.1"
    assert "DONE" in row, "Task 12.1 row must be flipped to DONE"
    assert "ADR-032" in row, "Task 12.1 row must cross-ref ADR-032 (sequential-by-task)"


def test_readme_marks_task_12_1_done_with_adr_032() -> None:
    text = _read(README_PATH)
    readme_lines = text.splitlines()
    row = next(
        (line for line in readme_lines if line.lstrip().startswith("| 12.1")),
        None,
    )
    assert row is not None, "README §7.2 must carry a row for Task 12.1"
    assert "DONE" in row, "README Task 12.1 row must be flipped to DONE"
    assert "ADR-032" in row, "README Task 12.1 row must cross-ref ADR-032"


def test_scratchpad_records_task_12_1_close_out_session() -> None:
    """At 12.1 close-out the active pointer recorded `Last completed:** Task 12.1`.

    Once Task 12.2 lands, that pointer advances. The historical fact —
    that Task 12.1 closed out and locked Risc0 at ADR-032 — survives
    in the session-log section. This foundation test asserts the
    durable record (session-log heading + ADR-032 reference) rather
    than the moving active pointer; the active pointer is asserted
    by the per-sub-task pointer tests in `test_zk_witness.py` etc.
    """
    text = _read(SCRATCHPAD_PATH)
    assert "Task 12.1 close-out (ADR-032)" in text, (
        "Memory_Scratchpad must preserve the Task 12.1 close-out session-log heading"
    )
