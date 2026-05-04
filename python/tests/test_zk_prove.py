"""Prove + verify scaffold tests for Task 12.3a (ADR-034).

Validates the Phase 1 ZK axis Task 12.3a deliverables — the split-out
"install plumbing + guest crate scaffold" half of the original Task
12.3:

- `crates/zk_kernel/guest/` exists as a standalone package with a
  declared `[[bin]]`, `target_os = "zkvm"` cfg-gated `#![no_main]` /
  `#![no_std]` skeleton, and a doc-only README spelling out the 12.3a
  vs. 12.3b boundary.
- The root `Cargo.toml` `[workspace]` table EXCLUDES the guest crate
  (so `cargo check --workspace` keeps the host build toolchain-
  agnostic) and the guest crate is NOT in `[workspace] members`.
- The `risc0-zkvm` workspace dep is STILL not pulled in (deferred to
  Task 12.3b per ADR-034 §3 — first kernel-side host consumer is
  `prove`).
- The host-side `prove` / `verify` stubs STILL return
  `NotYetImplemented(3)` (body fills land at Task 12.3b alongside
  the dep + guest body + canonical fixture round-trip).
- Justfile `fetch-zk` recipe is now wired with the actual sha-pinned
  cargo-risczero v3.0.1 download (no longer the Task 12.1 / 12.2 stub).
- ADR-034 is appended to the Architecture Decision Log.
- `Plan.md` row 12.3 is split into 12.3a (DONE) + 12.3b (TODO).
- `README.md` row 12.3 is split into 12.3a (DONE) + 12.3b (PLANNED).
- `Memory_Scratchpad.md` active-task pointer advances to Task 12.3b.

Pure offline test — no Risc0 / cargo-risczero / SP1 / cargo toolchain
calls. The cargo gate (`just zk-stub-check`) is the companion live
gate, running the 35 inline tests inside `crates/zk_kernel`.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_CARGO_TOML = REPO_ROOT / "Cargo.toml"
ZK_KERNEL_DIR = REPO_ROOT / "crates" / "zk_kernel"
ZK_KERNEL_CARGO_TOML = ZK_KERNEL_DIR / "Cargo.toml"
ZK_KERNEL_PROVE_RS = ZK_KERNEL_DIR / "src" / "prove.rs"
ZK_KERNEL_VERIFY_RS = ZK_KERNEL_DIR / "src" / "verify.rs"
ZK_GUEST_DIR = ZK_KERNEL_DIR / "guest"
ZK_GUEST_CARGO_TOML = ZK_GUEST_DIR / "Cargo.toml"
ZK_GUEST_MAIN_RS = ZK_GUEST_DIR / "src" / "main.rs"
ZK_GUEST_README = ZK_GUEST_DIR / "README.md"
JUSTFILE = REPO_ROOT / "Justfile"
PLAN_PATH = REPO_ROOT / ".agent" / "Plan.md"
ADL_PATH = REPO_ROOT / ".agent" / "Architecture_Decision_Log.md"
SCRATCHPAD_PATH = REPO_ROOT / ".agent" / "Memory_Scratchpad.md"
README_PATH = REPO_ROOT / "README.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# -----------------------------------------------------------------------------
# Guest crate scaffold (Cargo.toml + src/main.rs + README)
# -----------------------------------------------------------------------------


def test_guest_crate_directory_exists() -> None:
    assert ZK_GUEST_DIR.is_dir(), "crates/zk_kernel/guest/ must exist (ADR-034 §3)"
    assert ZK_GUEST_CARGO_TOML.is_file(), "guest crate must declare a Cargo.toml"
    assert ZK_GUEST_MAIN_RS.is_file(), "guest crate must declare a src/main.rs entrypoint"
    assert ZK_GUEST_README.is_file(), "guest crate must carry a README documenting the boundary"


def test_guest_cargo_toml_declares_zk_kernel_guest_package() -> None:
    parsed = tomllib.loads(_read(ZK_GUEST_CARGO_TOML))
    package = parsed.get("package", {})
    assert package.get("name") == "zk-kernel-guest", "guest package name must be `zk-kernel-guest`"
    assert package.get("edition") == "2024", "guest package must use Rust edition 2024"
    bin_section = parsed.get("bin", [])
    assert isinstance(bin_section, list), "guest Cargo.toml must declare a [[bin]] section"
    assert bin_section, "guest crate must declare at least one [[bin]] target"
    bin_entry = bin_section[0]
    assert bin_entry.get("name") == "zk-kernel-guest"
    assert bin_entry.get("path") == "src/main.rs"


def test_guest_cargo_toml_has_no_risc0_zkvm_dep_at_task_12_3a() -> None:
    """ADR-034 §3: heavy `risc0-zkvm` guest dep deferred to Task 12.3b.

    The guest crate scaffold exists at 12.3a so the file structure +
    workspace exclusion is committed; the actual guest body + the
    `risc0-zkvm` guest dep land together at 12.3b.
    """
    parsed = tomllib.loads(_read(ZK_GUEST_CARGO_TOML))
    deps = parsed.get("dependencies", {})
    forbidden = {"risc0-zkvm", "risc0-zkvm-platform", "risc0-zkp"}
    found = forbidden.intersection(deps.keys())
    assert not found, (
        f"Task 12.3a guest scaffold must NOT pull in Risc0 crates yet (deferred per ADR-034 §3); "
        f"found: {sorted(found)}"
    )


def test_guest_main_rs_is_no_main_no_std_under_zkvm_target() -> None:
    text = _read(ZK_GUEST_MAIN_RS)
    assert '#![cfg_attr(target_os = "zkvm", no_main)]' in text, (
        "guest must be #![no_main] under target_os = \"zkvm\" (Risc0 guest convention)"
    )
    assert '#![cfg_attr(target_os = "zkvm", no_std)]' in text, (
        "guest must be #![no_std] under target_os = \"zkvm\" (Risc0 guest convention)"
    )
    assert "#![forbid(unsafe_code)]" in text, (
        "guest must inherit the workspace-wide unsafe_code prohibition"
    )


def test_guest_main_rs_body_is_unreachable_at_task_12_3a() -> None:
    """ADR-034 §3: guest body lands at Task 12.3b; 12.3a scaffold is fail-loud."""
    text = _read(ZK_GUEST_MAIN_RS)
    assert "unreachable!(" in text, (
        "guest body must be `unreachable!(..)` at 12.3a — fails loud if the guest "
        "is compiled + run before Task 12.3b lands the real implementation"
    )


def test_guest_readme_documents_12_3a_vs_12_3b_boundary() -> None:
    text = _read(ZK_GUEST_README)
    assert "Task 12.3a" in text, "guest README must reference Task 12.3a"
    assert "Task 12.3b" in text, "guest README must reference Task 12.3b"
    assert "ADR-034" in text, "guest README must cross-ref ADR-034"


# -----------------------------------------------------------------------------
# Workspace exclusion of the guest crate
# -----------------------------------------------------------------------------


def test_workspace_excludes_guest_crate() -> None:
    parsed = tomllib.loads(_read(WORKSPACE_CARGO_TOML))
    workspace = parsed.get("workspace", {})
    members = workspace.get("members", [])
    excludes = workspace.get("exclude", [])
    assert "crates/zk_kernel/guest" not in members, (
        "guest crate must NOT be in [workspace] members (ADR-034 §3)"
    )
    assert "crates/zk_kernel/guest" in excludes, (
        "guest crate must be in [workspace] exclude so `cargo check --workspace` "
        "stays toolchain-agnostic (ADR-034 §3)"
    )


# -----------------------------------------------------------------------------
# Host-side prove / verify stubs (still NotYetImplemented at 12.3a)
# -----------------------------------------------------------------------------


def test_prove_and_verify_still_return_not_yet_implemented_at_task_12_3a() -> None:
    """ADR-034 §3: prove + verify body fills land at Task 12.3b.

    Task 12.3a deliberately keeps the `NotYetImplemented(3)` stubs so
    the foundation/usage split is honest: dep + body fills land
    together at the first concrete consumer session (12.3b).
    """
    prove_text = _read(ZK_KERNEL_PROVE_RS)
    verify_text = _read(ZK_KERNEL_VERIFY_RS)
    assert "ZkError::NotYetImplemented(3)" in prove_text, (
        "prove must remain a NotYetImplemented(3) stub at Task 12.3a (lands at 12.3b)"
    )
    assert "ZkError::NotYetImplemented(3)" in verify_text, (
        "verify must remain a NotYetImplemented(3) stub at Task 12.3a (lands at 12.3b)"
    )


def test_zk_kernel_still_has_no_risc0_zkvm_workspace_dep_at_task_12_3a() -> None:
    """ADR-034 §3: `risc0-zkvm` workspace dep lands at Task 12.3b.

    Mirrors test_zk_kernel_still_has_no_risc0_zkvm_dep_at_task_12_2 in
    `test_zk_witness.py` — the deferral pattern continues from 12.2 →
    12.3a → 12.3b.
    """
    parsed = tomllib.loads(_read(ZK_KERNEL_CARGO_TOML))
    deps = parsed.get("dependencies", {})
    forbidden = {"risc0-zkvm", "risc0-zkvm-platform", "risc0-zkp", "cargo-risczero"}
    found = forbidden.intersection(deps.keys())
    assert not found, (
        f"crates/zk_kernel/Cargo.toml must NOT pull in Risc0 crates at Task 12.3a "
        f"(deferred to Task 12.3b per ADR-034 §3); found: {sorted(found)}"
    )

    workspace_parsed = tomllib.loads(_read(WORKSPACE_CARGO_TOML))
    workspace_deps = workspace_parsed.get("workspace", {}).get("dependencies", {})
    workspace_found = forbidden.intersection(workspace_deps.keys())
    assert not workspace_found, (
        f"workspace `[workspace.dependencies]` must NOT declare Risc0 crates at "
        f"Task 12.3a (deferred to Task 12.3b per ADR-034 §3); found: "
        f"{sorted(workspace_found)}"
    )


# -----------------------------------------------------------------------------
# Justfile — sha-pinned fetch-zk + zk-status updates
# -----------------------------------------------------------------------------


def test_justfile_fetch_zk_is_sha_pinned_at_task_12_3a() -> None:
    """ADR-034 §2: `fetch-zk` mirrors `fetch-fhir`'s sha256-verified pattern."""
    text = _read(JUSTFILE)
    assert "fetch-zk:" in text, "fetch-zk recipe must remain registered"
    # The Task 12.1 + 12.2 stub message is GONE.
    assert "Task 12.2 deliverable" not in text, (
        "fetch-zk must no longer carry the Task 12.1 / 12.2 stub message"
    )
    # The sha-pinned download is wired up.
    assert 'ZK_SHA256             := env_var_or_default(' in text, (
        "fetch-zk must declare a sha-pinned tarball digest (ZK_SHA256)"
    )
    assert "4e42c49d5e9d8ef85e10b5b8ee6fd9cac8abaccf1685aeb800550febdd77f069" in text, (
        "fetch-zk must pin the cargo-risczero v3.0.1 Linux x86_64 sha256 (ADR-034 §2)"
    )
    assert "cargo-risczero-{{ZK_ARCH}}-{{ZK_OS}}.tgz" in text, (
        "fetch-zk must resolve the cargo-risczero asset by ARCH/OS"
    )
    assert "github.com/risc0/risc0/releases/download/v{{ZK_TOOLCHAIN_VERSION}}" in text, (
        "fetch-zk must download from the pinned Risc0 GitHub release tag"
    )
    assert "sha256sum" in text, "fetch-zk must verify the tarball digest before installing"


def test_justfile_fetch_zk_does_not_curl_pipe_bash_unverified() -> None:
    """Continues the ADR-033 §4 invariant: no unbounded `curl|bash`.

    `fetch-zk` is now wired (12.3a) but MUST NOT execute the upstream
    `curl https://risczero.com/install | bash` installer — that's the
    supply-chain hazard ADR-032 §6 + ADR-033 §4 + ADR-034 §2 all
    explicitly reject.
    """
    text = _read(JUSTFILE)
    assert "curl https://risczero.com/install | bash" not in text, (
        "fetch-zk must use sha-pinned tarball download, not unverified curl|bash"
    )


def test_justfile_zk_status_mentions_cargo_risczero_and_guest_crate() -> None:
    text = _read(JUSTFILE)
    assert "guest crate:" in text, (
        "zk-status must report the excluded guest crate path (operator-facing)"
    )
    assert "cargo-risczero:" in text, (
        "zk-status must report the cargo-risczero install state (operator-facing)"
    )


# -----------------------------------------------------------------------------
# ADR / Plan / Scratchpad / README cross-checks
# -----------------------------------------------------------------------------


def test_adr_034_is_present_in_decision_log() -> None:
    text = _read(ADL_PATH)
    assert "## ADR-034 — " in text, "ADR-034 must be appended to the decision log"
    assert "Task 12.3a" in text, "ADR-034 must reference Task 12.3a"
    assert "Task 12.3b" in text, "ADR-034 must reference Task 12.3b (the deferred half)"
    assert "cargo-risczero" in text, "ADR-034 must document the cargo-risczero pin"
    assert "4e42c49d5e9d8ef85e10b5b8ee6fd9cac8abaccf1685aeb800550febdd77f069" in text, (
        "ADR-034 must record the sha-pinned tarball digest"
    )


def test_plan_splits_task_12_3_into_12_3a_and_12_3b() -> None:
    text = _read(PLAN_PATH)
    plan_lines = text.splitlines()
    row_a = next(
        (line for line in plan_lines if line.lstrip().startswith("| 12.3a")),
        None,
    )
    row_b = next(
        (line for line in plan_lines if line.lstrip().startswith("| 12.3b")),
        None,
    )
    assert row_a is not None, "Plan §8.2 must carry a row for Task 12.3a (split per ADR-034)"
    assert row_b is not None, "Plan §8.2 must carry a row for Task 12.3b (split per ADR-034)"
    assert "DONE" in row_a, "Task 12.3a row must be flipped to DONE"
    assert "ADR-034" in row_a, "Task 12.3a row must cross-ref ADR-034"
    assert "TODO" in row_b, "Task 12.3b row must remain TODO"
    assert "feat: complete Task 12.3a" in text, (
        "Plan must record the Task 12.3a commit message"
    )


def test_readme_splits_task_12_3_into_12_3a_and_12_3b() -> None:
    text = _read(README_PATH)
    readme_lines = text.splitlines()
    row_a = next(
        (line for line in readme_lines if line.lstrip().startswith("| 12.3a")),
        None,
    )
    row_b = next(
        (line for line in readme_lines if line.lstrip().startswith("| 12.3b")),
        None,
    )
    assert row_a is not None, "README §7.2 must carry a row for Task 12.3a (split per ADR-034)"
    assert row_b is not None, "README §7.2 must carry a row for Task 12.3b (split per ADR-034)"
    assert "DONE" in row_a, "README Task 12.3a row must be flipped to DONE"
    assert "ADR-034" in row_a, "README Task 12.3a row must cross-ref ADR-034"
    assert "PLANNED" in row_b, "README Task 12.3b row must remain PLANNED"


def test_scratchpad_advances_active_pointer_to_task_12_3b() -> None:
    text = _read(SCRATCHPAD_PATH)
    assert "Last completed:** Task 12.3a" in text, (
        "scratchpad must record 12.3a as last completed"
    )
    assert "Next up:** **Task 12.3b" in text, (
        "scratchpad must point at Task 12.3b as next up"
    )
