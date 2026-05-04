//! Risc0 zkVM guest program — body fill (Phase 1, Task 12.3b1 — ADR-035).
//!
//! Per ADR-035: this binary is the guest program that Risc0's
//! `default_prover().prove(env, GUEST_ELF)` (host call site:
//! `crates/zk_kernel/src/prove.rs::prove`) executes inside the zkVM.
//!
//! # Wire contract (Task 12.3b1 — this body)
//!
//! 1. `let bytes: Vec<u8> = risc0_zkvm::guest::env::read();` — reads
//!    the host-supplied witness blob written by `ExecutorEnv::builder()
//!    .write(&witness.0)` (bincode-serialized `Vec<u8>` round-trip).
//! 2. Validate the witness header: `WITNESS_MAGIC` ("ZKSM") +
//!    `WITNESS_VERSION` (= 1) + `payload_len` matches the post-header
//!    actual byte count. Fail loud (`panic!`) on any mismatch — the
//!    Risc0 receipt then carries the Halted(non-zero) exit code that
//!    `Receipt::verify` rejects.
//! 3. `serde_json::from_slice::<SmtTrace>` over the post-header bytes
//!    (mirrors `zk_kernel::witness::SmtTrace`).
//! 4. Run a minimal Alethe replay subset checker against the recovered
//!    `SmtTrace` (canonical `contradictory-bound` shape: proof text
//!    starts with "unsat" and references every MUC label). Broader
//!    Alethe coverage is a Task 12.4 deliverable per ADR-033 §context.
//! 5. `risc0_zkvm::guest::env::commit(&(theory_signature, muc_labels))`
//!    — commits the public verdict (theory signature + MUC label set)
//!    to the receipt's journal so the host-side verifier can re-bind
//!    the proof to the original `SmtTrace` UNSAT outcome.
//!
//! # Schema duplication (host ↔ guest)
//!
//! `SmtTrace` + the `WITNESS_*` constants are duplicated from
//! `crates/zk_kernel/src/witness.rs` because the guest crate is
//! workspace-excluded (root `Cargo.toml` `[workspace] exclude` —
//! ADR-034 §3) and cannot depend on the host `zk-kernel` crate (which
//! pulls in `risc0-zkvm/prove`, a host-only feature). The duplication
//! is bounded by ADR-033's wire-format invariant: any change to
//! `SmtTrace` or the header layout requires coordinated edits to BOTH
//! sites + a fresh ADR. Future ADR-?? may extract a tiny `witness-
//! schema` shared crate if drift becomes a maintenance burden.

#![forbid(unsafe_code)]
#![deny(clippy::all)]
#![cfg_attr(target_os = "zkvm", no_main)]

#[cfg(target_os = "zkvm")]
risc0_zkvm::guest::entry!(main);

#[cfg(target_os = "zkvm")]
fn main() {
    use risc0_zkvm::guest::env;
    use serde::{Deserialize, Serialize};

    /// Mirrors `zk_kernel::witness::WITNESS_HEADER_BYTES` (12).
    /// Sync'd manually — see module-doc "Schema duplication" notice.
    const WITNESS_HEADER_BYTES: usize = 12;
    /// Mirrors `zk_kernel::witness::WITNESS_MAGIC` (`*b"ZKSM"`).
    const WITNESS_MAGIC: [u8; 4] = *b"ZKSM";
    /// Mirrors `zk_kernel::witness::WITNESS_VERSION` (1).
    const WITNESS_VERSION: u8 = 1;

    /// Mirrors `zk_kernel::witness::SmtTrace`. Field names + types
    /// MUST match exactly so `serde_json` round-trips cleanly.
    #[derive(Serialize, Deserialize)]
    struct SmtTrace {
        theory_signature: Vec<String>,
        muc_labels: Vec<String>,
        alethe_proof: String,
    }

    let bytes: Vec<u8> = env::read();

    assert!(
        bytes.len() >= WITNESS_HEADER_BYTES,
        "witness blob shorter than 12-byte header"
    );
    assert_eq!(&bytes[..4], &WITNESS_MAGIC, "witness magic mismatch");
    assert_eq!(bytes[4], WITNESS_VERSION, "witness version unsupported");

    let payload_len_bytes: [u8; 4] = bytes[8..12]
        .try_into()
        .expect("slice covers exactly bytes 8..12 by construction");
    let advertised = u32::from_le_bytes(payload_len_bytes) as usize;
    let actual = bytes.len() - WITNESS_HEADER_BYTES;
    assert_eq!(
        advertised, actual,
        "witness payload length mismatch (advertised vs. actual)"
    );

    let trace: SmtTrace = serde_json::from_slice(&bytes[WITNESS_HEADER_BYTES..])
        .expect("witness payload must decode as SmtTrace JSON");

    // Minimal Alethe replay subset checker (ADR-033 §context — broader
    // coverage at Task 12.4): the canonical UNSAT proof text starts
    // with "unsat" and references every MUC label exactly. Anything
    // else fails loud, the guest exits non-zero, the host's
    // `Receipt::verify` rejects.
    assert!(
        trace.alethe_proof.starts_with("unsat"),
        "Alethe proof must start with 'unsat' (UNSAT outcome invariant)"
    );
    for label in &trace.muc_labels {
        assert!(
            trace.alethe_proof.contains(label.as_str()),
            "Alethe proof text must reference every MUC clause label"
        );
    }

    // Public output: theory signature + MUC label set, both bound into
    // the receipt's journal. The verifier reads `receipt.journal.bytes`
    // to extract this and pin the proof to the original SmtTrace UNSAT
    // outcome. The Alethe text itself is intentionally NOT committed
    // (it is the private witness, not the public verdict — keeps the
    // journal compact + bounded).
    env::commit(&(trace.theory_signature, trace.muc_labels));
}

#[cfg(not(target_os = "zkvm"))]
fn main() {
    // Host-side build is a sanity stub — the guest is never executed
    // outside the zkVM. Compiling it for the host target is supported
    // only so `cargo check` works ad-hoc on dev boxes that lack the
    // rzup-installed cross-compiler; the workspace excludes this crate
    // by default (root `Cargo.toml`).
    eprintln!(
        "zk-kernel-guest is a Risc0 zkVM guest program; host-side execution is not supported"
    );
}
