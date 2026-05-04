"""Prove + verify body-fill tests for Task 12.3b1 (ADR-035).

Validates the Phase 1 ZK axis Task 12.3b1 deliverables — the dep + body
half of the further-split Task 12.3b (12.3b2 lands the smoke recipe +
canonical round-trip integration test):

- `risc0-zkvm = "=3.0.5"` + `bincode = "1"` are now in the root
  `[workspace.dependencies]`. The host crate `crates/zk_kernel/Cargo.toml`
  pulls `risc0-zkvm = { workspace = true, features = ["prove"] }` +
  `bincode = { workspace = true }`. The guest crate
  `crates/zk_kernel/guest/Cargo.toml` declares its own
  `risc0-zkvm = { version = "=3.0.5", default-features = false,
  features = ["std"] }` + `serde` + `serde_json` (direct deps because
  the guest is workspace-excluded — ADR-034 §3 + ADR-035 §6).
- Host `prove(witness, guest_elf)` returns `ZkProof(bincode::serialize
  (&receipt))` on success, `ZkError::Risc0ProveFailed(_)` on failure.
- Host `verify(proof, image_id)` returns `Ok(())` / `ZkError::
  Risc0VerifyFailed(_)`.
- Guest `main.rs` body (under `#[cfg(target_os = "zkvm")]`) reads the
  witness via `env::read::<Vec<u8>>()`, validates the ZKSM header,
  decodes via `serde_json::from_slice::<SmtTrace>`, runs a minimal
  Alethe replay subset checker, and `env::commit`s the
  `(theory_signature, muc_labels)` verdict to the receipt journal.
- `ZkError` gains `Risc0ProveFailed(String)` + `Risc0VerifyFailed
  (String)` variants (per ADR-035 §7).
- Justfile `fetch-zk` recipe is bumped to cargo-risczero v3.0.5
  (the new sha256 lands per ADR-035 §2; the v3.0.1 → v3.0.5 bump was
  forced by the `risc0-circuit-rv32im 4.0.4` dyn-compat regression on
  rustc 1.95.0 — see ADR-035 §Context).
- ADR-035 is appended to the Architecture Decision Log.
- `Plan.md` row 12.3b is split into 12.3b1 (DONE) + 12.3b2 (TODO).
- `README.md` row 12.3b is split into 12.3b1 (DONE) + 12.3b2 (PLANNED).
- `Memory_Scratchpad.md` active-task pointer advances to Task 12.3b2.

Pure offline test — no Risc0 / cargo-risczero / SP1 / cargo toolchain
calls. The cargo gate (`just zk-stub-check`) is the companion live
gate, running the 37 inline tests inside `crates/zk_kernel`.
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
ZK_KERNEL_ERRORS_RS = ZK_KERNEL_DIR / "src" / "errors.rs"
ZK_GUEST_DIR = ZK_KERNEL_DIR / "guest"
ZK_GUEST_CARGO_TOML = ZK_GUEST_DIR / "Cargo.toml"
ZK_GUEST_MAIN_RS = ZK_GUEST_DIR / "src" / "main.rs"
ZK_GUEST_README = ZK_GUEST_DIR / "README.md"
JUSTFILE = REPO_ROOT / "Justfile"
PLAN_PATH = REPO_ROOT / ".agent" / "Plan.md"
ADL_PATH = REPO_ROOT / ".agent" / "Architecture_Decision_Log.md"
SCRATCHPAD_PATH = REPO_ROOT / ".agent" / "Memory_Scratchpad.md"
README_PATH = REPO_ROOT / "README.md"

ZK_TARBALL_SHA256_V3_0_5 = (
    "936ef988b78f20e3bd9f80e375f3adc934b13addc6ae2680f2e5fc0bcc966158"
)


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


def test_guest_cargo_toml_pulls_risc0_zkvm_at_task_12_3b1() -> None:
    """ADR-035 §3: guest `risc0-zkvm` dep lands at Task 12.3b1.

    The guest crate is workspace-excluded so it cannot use `workspace =
    true`; it pins `risc0-zkvm = "=3.0.5"` directly with `default-
    features = false` + `std` (per the v3.0.5 guest guidance — host-
    only `client` / `bonsai` features must NOT be enabled for guest
    builds; `std` is enabled so the guest can heap-allocate `Vec<u8>` /
    `String`).
    """
    parsed = tomllib.loads(_read(ZK_GUEST_CARGO_TOML))
    deps = parsed.get("dependencies", {})
    assert "risc0-zkvm" in deps, (
        "guest Cargo.toml must declare `risc0-zkvm` at Task 12.3b1 (ADR-035 §3)"
    )
    risc0_dep = deps["risc0-zkvm"]
    assert isinstance(risc0_dep, dict), (
        "guest `risc0-zkvm` dep must be a table (version + default-features + features)"
    )
    assert risc0_dep.get("version") == "=3.0.5", (
        "guest `risc0-zkvm` must pin `=3.0.5` per ADR-035 §2 coordinated bump"
    )
    assert risc0_dep.get("default-features") is False, (
        "guest `risc0-zkvm` must set `default-features = false` (ADR-035 §4)"
    )
    features = risc0_dep.get("features", [])
    assert "std" in features, (
        "guest `risc0-zkvm` must enable `std` so the guest can use Vec<u8> / String"
    )
    assert "serde" in deps, "guest must pull `serde` for SmtTrace round-trip"
    assert "serde_json" in deps, "guest must pull `serde_json` for SmtTrace JSON decode"


def test_guest_main_rs_is_no_main_under_zkvm_target() -> None:
    text = _read(ZK_GUEST_MAIN_RS)
    assert '#![cfg_attr(target_os = "zkvm", no_main)]' in text, (
        "guest must be #![no_main] under target_os = \"zkvm\" (Risc0 guest convention)"
    )
    assert "#![forbid(unsafe_code)]" in text, (
        "guest must inherit the workspace-wide unsafe_code prohibition"
    )
    assert "risc0_zkvm::guest::entry!(main)" in text, (
        "guest must register its entrypoint via `risc0_zkvm::guest::entry!(main)` (Task 12.3b1)"
    )


def test_guest_main_rs_body_uses_env_read_and_commit_at_task_12_3b1() -> None:
    """ADR-035 §3 deliverable 6: guest body lands at Task 12.3b1.

    The 12.3a `unreachable!()` placeholder is replaced by:
    `env::read()` → header validation → `serde_json::from_slice::
    <SmtTrace>` → minimal Alethe replay → `env::commit(&(theory_
    signature, muc_labels))`.
    """
    text = _read(ZK_GUEST_MAIN_RS)
    assert "unreachable!(" not in text, (
        "guest body must no longer be `unreachable!()` at Task 12.3b1 (body fill landed)"
    )
    assert "env::read" in text, (
        "guest must call `env::read` to receive the witness blob from the host"
    )
    assert "env::commit" in text, (
        "guest must call `env::commit` to bind the verdict into the receipt journal"
    )
    assert 'b"ZKSM"' in text, (
        "guest must validate the ZKSM magic prefix on the witness header"
    )
    assert "serde_json::from_slice" in text, (
        "guest must JSON-decode the post-header SmtTrace payload"
    )
    assert "alethe_proof" in text, (
        "guest must reference the SmtTrace.alethe_proof field for the Alethe replay check"
    )


def test_guest_readme_documents_12_3b1_vs_12_3b2_boundary() -> None:
    text = _read(ZK_GUEST_README)
    assert "Task 12.3b1" in text, "guest README must reference Task 12.3b1 (body fills)"
    assert "Task 12.3b2" in text, "guest README must reference Task 12.3b2 (smoke + round-trip)"
    assert "ADR-035" in text, "guest README must cross-ref ADR-035"


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
# Host-side prove / verify body fills (12.3b1)
# -----------------------------------------------------------------------------


def test_prove_and_verify_have_body_fills_at_task_12_3b1() -> None:
    """ADR-035 §3 deliverables 4 + 5: prove + verify body fills land at 12.3b1.

    Inverts the 12.3a `NotYetImplemented(3)` stub assertion: the bodies
    now call into Risc0 directly. Failures surface as
    `Risc0ProveFailed` / `Risc0VerifyFailed`.
    """
    prove_text = _read(ZK_KERNEL_PROVE_RS)
    verify_text = _read(ZK_KERNEL_VERIFY_RS)

    assert "ZkError::NotYetImplemented(3)" not in prove_text, (
        "prove body must no longer return NotYetImplemented(3) at Task 12.3b1"
    )
    assert "ZkError::NotYetImplemented(3)" not in verify_text, (
        "verify body must no longer return NotYetImplemented(3) at Task 12.3b1"
    )

    assert "Risc0ProveFailed" in prove_text, (
        "prove body must surface failures as ZkError::Risc0ProveFailed (ADR-035 §7)"
    )
    assert "default_prover()" in prove_text, (
        "prove body must call risc0_zkvm::default_prover() (ADR-035 §3 deliverable 4)"
    )
    assert "ExecutorEnv::builder()" in prove_text, (
        "prove body must build a risc0_zkvm::ExecutorEnv (ADR-035 §3 deliverable 4)"
    )
    assert "bincode::serialize" in prove_text, (
        "prove body must bincode-serialize the receipt into the ZkProof byte payload"
    )

    assert "Risc0VerifyFailed" in verify_text, (
        "verify body must surface failures as ZkError::Risc0VerifyFailed (ADR-035 §7)"
    )
    assert "bincode::deserialize" in verify_text, (
        "verify body must bincode-deserialize the ZkProof bytes back into a Receipt"
    )
    assert "receipt" in verify_text, (
        "verify body must hold the deserialized Receipt local (ADR-035 §3 deliverable 5)"
    )
    assert ".verify(" in verify_text, (
        "verify body must call Receipt::verify(image_id) (ADR-035 §3 deliverable 5)"
    )
    assert "image_id_from_elf" in verify_text, (
        "verify module must expose the image_id_from_elf helper (ADR-035 §3 deliverable 5)"
    )
    assert "compute_image_id" in verify_text, (
        "image_id_from_elf must wrap risc0_zkvm::compute_image_id (ADR-035 §3 deliverable 5)"
    )


def test_zk_error_gains_risc0_variants_at_task_12_3b1() -> None:
    """ADR-035 §7: `ZkError` surface gains Risc0ProveFailed + Risc0VerifyFailed."""
    text = _read(ZK_KERNEL_ERRORS_RS)
    assert "Risc0ProveFailed(String)" in text, (
        "ZkError must declare `Risc0ProveFailed(String)` variant (ADR-035 §7)"
    )
    assert "Risc0VerifyFailed(String)" in text, (
        "ZkError must declare `Risc0VerifyFailed(String)` variant (ADR-035 §7)"
    )
    assert "NotYetImplemented(u8)" in text, (
        "ZkError must retain the foundation-stub NotYetImplemented(u8) variant"
    )


def test_zk_kernel_pulls_risc0_zkvm_at_task_12_3b1() -> None:
    """ADR-035 §3 deliverables 1 + 2: workspace + host risc0-zkvm + bincode deps."""
    workspace_parsed = tomllib.loads(_read(WORKSPACE_CARGO_TOML))
    workspace_deps = workspace_parsed.get("workspace", {}).get("dependencies", {})
    assert "risc0-zkvm" in workspace_deps, (
        "[workspace.dependencies] must declare `risc0-zkvm` at Task 12.3b1 (ADR-035 §3)"
    )
    risc0 = workspace_deps["risc0-zkvm"]
    if isinstance(risc0, dict):
        assert risc0.get("version") == "=3.0.5", (
            "workspace `risc0-zkvm` must pin `=3.0.5` (ADR-035 §2 coordinated bump)"
        )
        assert risc0.get("default-features") is False, (
            "workspace `risc0-zkvm` must set `default-features = false` "
            "(host crates opt into prove/client features individually)"
        )
    else:
        # Bare-string version — exact pin string still required.
        assert risc0 == "=3.0.5", "workspace `risc0-zkvm` must pin `=3.0.5`"
    assert "bincode" in workspace_deps, (
        "[workspace.dependencies] must declare `bincode` at Task 12.3b1 "
        "(ADR-035 §8 — Receipt serialization)"
    )

    parsed = tomllib.loads(_read(ZK_KERNEL_CARGO_TOML))
    deps = parsed.get("dependencies", {})
    assert "risc0-zkvm" in deps, (
        "crates/zk_kernel/Cargo.toml must declare `risc0-zkvm` at Task 12.3b1"
    )
    host_risc0 = deps["risc0-zkvm"]
    assert isinstance(host_risc0, dict), "host `risc0-zkvm` dep must be a table"
    assert host_risc0.get("workspace") is True, (
        "host `risc0-zkvm` must use `workspace = true` to inherit the version pin"
    )
    features = host_risc0.get("features", [])
    assert "prove" in features, (
        "host `risc0-zkvm` must enable the `prove` feature (ADR-035 §3 — gives "
        "default_prover + ExecutorEnv + Receipt::verify + compute_image_id in one pull)"
    )
    assert "bincode" in deps, (
        "crates/zk_kernel/Cargo.toml must declare `bincode` at Task 12.3b1 (ADR-035 §8)"
    )


# -----------------------------------------------------------------------------
# Justfile — sha-pinned fetch-zk + zk-status updates
# -----------------------------------------------------------------------------


def test_justfile_fetch_zk_is_sha_pinned_to_v3_0_5_at_task_12_3b1() -> None:
    """ADR-035 §2: `fetch-zk` is bumped to cargo-risczero v3.0.5 (new sha256).

    The v3.0.1 → v3.0.5 bump was forced by the `risc0-circuit-rv32im
    4.0.4` dyn-compat regression on rustc 1.95.0 (E0038 +
    E0599 — see ADR-035 §Context #3).
    """
    text = _read(JUSTFILE)
    assert "fetch-zk:" in text, "fetch-zk recipe must remain registered"
    assert "Task 12.2 deliverable" not in text, (
        "fetch-zk must no longer carry the Task 12.1 / 12.2 stub message"
    )
    assert 'ZK_SHA256             := env_var_or_default(' in text, (
        "fetch-zk must declare a sha-pinned tarball digest (ZK_SHA256)"
    )
    assert ZK_TARBALL_SHA256_V3_0_5 in text, (
        f"fetch-zk must pin the cargo-risczero v3.0.5 Linux x86_64 sha256 "
        f"(ADR-035 §2): {ZK_TARBALL_SHA256_V3_0_5}"
    )
    # The stale v3.0.1 sha256 must NOT be the bound ZK_SHA256 value
    # (drift protection — a doc-comment supersession reference is fine
    # since ADR-035 §2 explicitly cites the prior pin for traceability).
    stale_v3_0_1_sha = "4e42c49d5e9d8ef85e10b5b8ee6fd9cac8abaccf1685aeb800550febdd77f069"
    stale_bind = (
        f"ZK_SHA256             := env_var_or_default('ZK_SHA256',  '{stale_v3_0_1_sha}')"
    )
    assert stale_bind not in text, (
        "ZK_SHA256 must NOT bind the stale cargo-risczero v3.0.1 sha256 (ADR-035 §2 bump)"
    )
    assert "cargo-risczero-{{ZK_ARCH}}-{{ZK_OS}}.tgz" in text, (
        "fetch-zk must resolve the cargo-risczero asset by ARCH/OS"
    )
    assert "github.com/risc0/risc0/releases/download/v{{ZK_TOOLCHAIN_VERSION}}" in text, (
        "fetch-zk must download from the pinned Risc0 GitHub release tag"
    )
    assert "sha256sum" in text, "fetch-zk must verify the tarball digest before installing"
    assert "ZK_TOOLCHAIN_VERSION  := env_var_or_default('ZK_TOOLCHAIN_VERSION', '3.0.5')" in text, (
        "Justfile ZK_TOOLCHAIN_VERSION must be bumped to '3.0.5' (ADR-035 §2)"
    )


def test_justfile_fetch_zk_does_not_curl_pipe_bash_unverified() -> None:
    """Continues the ADR-033 §4 invariant: no unbounded `curl|bash`.

    `fetch-zk` must NEVER execute the upstream `curl https://risczero
    .com/install | bash` installer — that's the supply-chain hazard
    ADR-032 §6 + ADR-033 §4 + ADR-034 §2 + ADR-035 all explicitly
    reject.
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
    """Sticky check: ADR-034 (12.3a) stays in the ADL after the 12.3b1 commit."""
    text = _read(ADL_PATH)
    assert "## ADR-034 — " in text, "ADR-034 must remain in the decision log"
    assert "Task 12.3a" in text, "ADR-034 must reference Task 12.3a"
    assert "cargo-risczero" in text, "ADR-034 must document the cargo-risczero pin"


def test_adr_035_is_present_in_decision_log() -> None:
    text = _read(ADL_PATH)
    assert "## ADR-035 — " in text, "ADR-035 must be appended to the decision log"
    assert "Task 12.3b1" in text, "ADR-035 must reference Task 12.3b1 (this commit)"
    assert "Task 12.3b2" in text, "ADR-035 must reference Task 12.3b2 (the deferred half)"
    assert "Risc0ProveFailed" in text, (
        "ADR-035 must document the new Risc0ProveFailed ZkError variant"
    )
    assert "Risc0VerifyFailed" in text, (
        "ADR-035 must document the new Risc0VerifyFailed ZkError variant"
    )
    assert "3.0.5" in text, (
        "ADR-035 must record the v3.0.1 → v3.0.5 coordinated cargo-risczero bump"
    )
    assert ZK_TARBALL_SHA256_V3_0_5 in text, (
        f"ADR-035 must record the new sha-pinned tarball digest: {ZK_TARBALL_SHA256_V3_0_5}"
    )


def test_plan_splits_task_12_3b_into_12_3b1_and_12_3b2() -> None:
    text = _read(PLAN_PATH)
    plan_lines = text.splitlines()
    row_a = next(
        (line for line in plan_lines if line.lstrip().startswith("| 12.3a")),
        None,
    )
    row_b1 = next(
        (line for line in plan_lines if line.lstrip().startswith("| 12.3b1")),
        None,
    )
    row_b2 = next(
        (line for line in plan_lines if line.lstrip().startswith("| 12.3b2")),
        None,
    )
    assert row_a is not None, "Plan §8.2 must carry a row for Task 12.3a (split per ADR-034)"
    assert row_b1 is not None, "Plan §8.2 must carry a row for Task 12.3b1 (split per ADR-035)"
    assert row_b2 is not None, "Plan §8.2 must carry a row for Task 12.3b2 (split per ADR-035)"
    assert "DONE" in row_a, "Task 12.3a row must remain DONE"
    assert "DONE" in row_b1, "Task 12.3b1 row must be flipped to DONE"
    assert "ADR-035" in row_b1, "Task 12.3b1 row must cross-ref ADR-035"
    assert "TODO" in row_b2, "Task 12.3b2 row must remain TODO"
    assert "feat: complete Task 12.3b1" in text, (
        "Plan must record the Task 12.3b1 commit message"
    )


def test_readme_splits_task_12_3b_into_12_3b1_and_12_3b2() -> None:
    text = _read(README_PATH)
    readme_lines = text.splitlines()
    row_a = next(
        (line for line in readme_lines if line.lstrip().startswith("| 12.3a")),
        None,
    )
    row_b1 = next(
        (line for line in readme_lines if line.lstrip().startswith("| 12.3b1")),
        None,
    )
    row_b2 = next(
        (line for line in readme_lines if line.lstrip().startswith("| 12.3b2")),
        None,
    )
    assert row_a is not None, "README §7.2 must carry a row for Task 12.3a (split per ADR-034)"
    assert row_b1 is not None, "README §7.2 must carry a row for Task 12.3b1 (split per ADR-035)"
    assert row_b2 is not None, "README §7.2 must carry a row for Task 12.3b2 (split per ADR-035)"
    assert "DONE" in row_a, "README Task 12.3a row must remain DONE"
    assert "DONE" in row_b1, "README Task 12.3b1 row must be flipped to DONE"
    assert "ADR-035" in row_b1, "README Task 12.3b1 row must cross-ref ADR-035"
    assert "PLANNED" in row_b2, "README Task 12.3b2 row must remain PLANNED"


def test_scratchpad_advances_active_pointer_to_task_12_3b2() -> None:
    text = _read(SCRATCHPAD_PATH)
    assert "Last completed:** Task 12.3b1" in text, (
        "scratchpad must record 12.3b1 as last completed"
    )
    assert "Next up:** **Task 12.3b2" in text, (
        "scratchpad must point at Task 12.3b2 as next up"
    )
