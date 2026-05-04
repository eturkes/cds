"""Witness-encoding tests for Task 12.2 (ADR-033).

Validates the Phase 1 ZK axis witness-extraction deliverables:

- `crates/zk_kernel/src/witness.rs` declares the `SmtTrace` host-side
  struct + the length-prefixed binary encoding constants.
- `crates/zk_kernel/src/errors.rs` declares the new witness-specific
  `ZkError` variants (`TraceFieldOverflow`, `WitnessTooLarge`,
  `WitnessHeader…`, `WitnessPayload…`).
- The witness module no longer returns `NotYetImplemented(2)` (impl
  has landed) — the sub-task-3 markers in `prove.rs` / `verify.rs`
  remain (those land at Task 12.3).
- Justfile registers the `zk-witness-smoke` recipe.
- ADR-033 is appended to the Architecture Decision Log.
- `Plan.md` row 12.2 is flipped to DONE with the ADR-033 cross-ref.
- `README.md` row 12.2 is flipped to DONE with the ADR-033 cross-ref.
- `Memory_Scratchpad.md` active-task pointer advances to Task 12.3.
- `risc0-zkvm` workspace dep is still NOT pulled in (re-deferred to
  Task 12.3 per ADR-033 §3 — first kernel-side consumer is `prove`,
  not `extract_witness`).
- `fetch-zk` Justfile recipe still flags itself as a deferred install
  (re-deferred to Task 12.3 per ADR-033 §4 — rzup is needed only
  when compiling the guest ELF).

Pure offline test — no Risc0 / rzup / SP1 / cargo toolchain calls.
The cargo gate (`just zk-witness-smoke`) is the companion live gate,
running the 25 inline witness tests inside `crates/zk_kernel`.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ZK_KERNEL_DIR = REPO_ROOT / "crates" / "zk_kernel"
ZK_KERNEL_CARGO_TOML = ZK_KERNEL_DIR / "Cargo.toml"
ZK_KERNEL_WITNESS_RS = ZK_KERNEL_DIR / "src" / "witness.rs"
ZK_KERNEL_ERRORS_RS = ZK_KERNEL_DIR / "src" / "errors.rs"
JUSTFILE = REPO_ROOT / "Justfile"
PLAN_PATH = REPO_ROOT / ".agent" / "Plan.md"
ADL_PATH = REPO_ROOT / ".agent" / "Architecture_Decision_Log.md"
SCRATCHPAD_PATH = REPO_ROOT / ".agent" / "Memory_Scratchpad.md"
README_PATH = REPO_ROOT / "README.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# -----------------------------------------------------------------------------
# witness.rs — host-side trace shape + encoding constants
# -----------------------------------------------------------------------------


def test_witness_module_declares_smt_trace_struct() -> None:
    text = _read(ZK_KERNEL_WITNESS_RS)
    assert "pub struct SmtTrace" in text, "SmtTrace must be the public host-side input shape"
    for field in ("theory_signature", "muc_labels", "alethe_proof"):
        assert f"pub {field}" in text, f"SmtTrace must expose `{field}`"


def test_witness_module_declares_encoding_constants() -> None:
    text = _read(ZK_KERNEL_WITNESS_RS)
    for decl in (
        "pub const MAX_WITNESS_BYTES: usize = 1 << 20;",
        "pub const WITNESS_HEADER_BYTES: usize = 12;",
        "pub const WITNESS_MAGIC: [u8; 4] = *b\"ZKSM\";",
        "pub const WITNESS_VERSION: u8 = 1;",
        "pub const MAX_THEORIES: usize = 32;",
        "pub const MAX_MUC_LABELS: usize = 1024;",
        "pub const MAX_ALETHE_BYTES: usize = 768 * 1024;",
        "pub const MAX_LABEL_BYTES: usize = 256;",
    ):
        assert decl in text, f"missing encoding constant: {decl}"


def test_witness_module_declares_extract_and_parse_entrypoints() -> None:
    text = _read(ZK_KERNEL_WITNESS_RS)
    assert "pub fn extract_witness(trace: &SmtTrace) -> Result<WitnessBlob, ZkError>" in text, (
        "extract_witness signature must be the documented host entrypoint"
    )
    assert "pub fn parse_witness(blob: &WitnessBlob) -> Result<SmtTrace, ZkError>" in text, (
        "parse_witness signature is required for host-side round-trip + Task 12.3 host glue"
    )


def test_witness_module_no_longer_returns_not_yet_implemented_two() -> None:
    """Task 12.2 has landed; the witness body must NOT carry the foundation stub marker."""
    text = _read(ZK_KERNEL_WITNESS_RS)
    assert "NotYetImplemented(2)" not in text, (
        "witness impl landed at Task 12.2 — the sub-task-2 stub marker must be gone"
    )


def test_witness_module_uses_serde_json_not_risc0_zkvm() -> None:
    """Encoding is a pure-Rust serde_json deliverable; risc0-zkvm deferred to 12.3 (ADR-033 §3)."""
    text = _read(ZK_KERNEL_WITNESS_RS)
    assert "serde_json::to_vec" in text, "extract_witness must use serde_json for the payload"
    assert "use risc0_zkvm" not in text, (
        "risc0-zkvm dep is re-deferred to Task 12.3 (ADR-033 §3 — first kernel-side consumer "
        "is `prove`, not `extract_witness`)"
    )


# -----------------------------------------------------------------------------
# errors.rs — new ZkError variants
# -----------------------------------------------------------------------------


def test_errors_module_declares_witness_variants() -> None:
    text = _read(ZK_KERNEL_ERRORS_RS)
    for variant in (
        "TraceFieldOverflow",
        "WitnessTooLarge",
        "WitnessHeaderTruncated",
        "WitnessHeaderMagicMismatch",
        "WitnessVersionUnsupported",
        "WitnessPayloadLengthMismatch",
        "WitnessPayloadEncode",
        "WitnessPayloadDecode",
    ):
        assert variant in text, f"ZkError variant `{variant}` missing from errors.rs"


# -----------------------------------------------------------------------------
# Cargo.toml — risc0-zkvm dep STILL re-deferred at Task 12.2
# -----------------------------------------------------------------------------


def test_zk_kernel_still_has_no_risc0_zkvm_dep_at_task_12_2() -> None:
    """ADR-033 §3 re-defers the heavy `risc0-zkvm` dep to Task 12.3.

    Reasoning: `extract_witness` produces host-side bytes (`Vec<u8>`)
    via plain `serde_json`; the first kernel-side consumer of
    `risc0-zkvm` is `prove` (Task 12.3), not `extract_witness` (Task
    12.2). Mirrors the FHIR-axis `fhirbolt` deferral pattern (ADR-025
    §3 + §8) and the Task 12.1 deferral (ADR-032 §5).
    """
    with ZK_KERNEL_CARGO_TOML.open("rb") as fh:
        manifest = tomllib.load(fh)
    forbidden = {"risc0-zkvm", "cargo-risczero", "rzup", "sp1-zkvm", "halo2", "plonky2", "plonky3"}
    declared: set[str] = set()
    for table_name in ("dependencies", "dev-dependencies", "build-dependencies"):
        declared.update(manifest.get(table_name, {}).keys())
    offenders = sorted(declared & forbidden)
    detail = (
        "Task 12.2 must NOT pull in zkVM crates yet (re-deferred per ADR-033 §3); "
        f"found: {offenders}"
    )
    assert not offenders, detail


# -----------------------------------------------------------------------------
# Justfile — zk-witness-smoke + fetch-zk re-deferral
# -----------------------------------------------------------------------------


def test_justfile_registers_zk_witness_smoke_recipe() -> None:
    text = _read(JUSTFILE)
    assert "\nzk-witness-smoke:\n" in text, "Justfile must register the zk-witness-smoke recipe"
    assert "cargo test --package zk-kernel --lib witness" in text, (
        "zk-witness-smoke recipe must filter cargo test to the witness module"
    )


def test_justfile_fetch_zk_install_logic_still_deferred() -> None:
    """ADR-033 §4 re-defers the actual install logic to Task 12.3.

    Reasoning: rzup is needed only to compile the guest ELF (Task
    12.3); Task 12.2 produces host-side bytes via pure serde_json with
    no toolchain dep. The stub messaging continues to honestly flag
    the deferral so operators get a clear notice instead of an
    unbounded `curl | bash` from the web.
    """
    text = _read(JUSTFILE)
    assert "fetch-zk:" in text, "fetch-zk recipe must remain registered"
    assert (
        "curl https://risczero.com/install | bash" not in text
    ), "fetch-zk must NOT execute an unverified curl|bash at Task 12.2 (re-deferred to 12.3)"


# -----------------------------------------------------------------------------
# ADR / Plan / Scratchpad / README cross-checks
# -----------------------------------------------------------------------------


def test_adr_033_is_present_in_decision_log() -> None:
    text = _read(ADL_PATH)
    assert "## ADR-033 — " in text, "ADR-033 must be appended to the decision log"
    assert "Task 12.2" in text, "ADR-033 must reference Task 12.2"
    assert "ZKSM" in text, "ADR-033 must document the ZKSM magic prefix"


def test_plan_marks_task_12_2_done_with_adr_033() -> None:
    text = _read(PLAN_PATH)
    assert "feat: complete Task 12.2 ZKSMT witness gen" in text
    plan_lines = text.splitlines()
    row = next(
        (line for line in plan_lines if line.lstrip().startswith("| 12.2")),
        None,
    )
    assert row is not None, "Plan §8.2 must carry a row for Task 12.2"
    assert "DONE" in row, "Task 12.2 row must be flipped to DONE"
    assert "ADR-033" in row, "Task 12.2 row must cross-ref ADR-033 (sequential-by-task)"


def test_readme_marks_task_12_2_done_with_adr_033() -> None:
    text = _read(README_PATH)
    readme_lines = text.splitlines()
    row = next(
        (line for line in readme_lines if line.lstrip().startswith("| 12.2")),
        None,
    )
    assert row is not None, "README §7.2 must carry a row for Task 12.2"
    assert "DONE" in row, "README Task 12.2 row must be flipped to DONE"
    assert "ADR-033" in row, "README Task 12.2 row must cross-ref ADR-033"


def test_scratchpad_advances_active_pointer_to_task_12_3() -> None:
    text = _read(SCRATCHPAD_PATH)
    assert "Last completed:** Task 12.2" in text, "scratchpad must record 12.2 as last completed"
    assert "Next up:** **Task 12.3" in text, "scratchpad must point at Task 12.3 as next up"
