//! Risc0 zkVM guest program — scaffold (Phase 1, Task 12.3a).
//!
//! Per ADR-034: this binary is the guest program that Risc0's
//! `default_prover().prove(env, GUEST_ELF)` will execute inside the
//! zkVM. At Task 12.3a only the file structure exists — the body is
//! a deliberate `unreachable!()` that fails loud if anyone compiles +
//! runs the guest before Task 12.3b lands the real implementation.
//!
//! # Wire contract (Task 12.3b lands this body)
//!
//! 1. `risc0_zkvm::guest::env::read_slice::<u8>()` — read the host-
//!    supplied witness blob produced by `zk_kernel::witness::extract_witness`
//!    (12-byte header + serde_json `SmtTrace` payload; ADR-033).
//! 2. Validate the [`zk_kernel::witness::WITNESS_MAGIC`] / version /
//!    `payload_len` header — fail loud (`panic!`) on any mismatch.
//! 3. `serde_json::from_slice::<SmtTrace>` over the post-header bytes.
//! 4. Run a minimal Alethe replay subset checker against the recovered
//!    `SmtTrace` (canonical `contradictory-bound` shape — broader Alethe
//!    coverage is a Task 12.4 deliverable per ADR-033 §context).
//! 5. `risc0_zkvm::guest::env::commit(&verdict_hash)` — commit the
//!    verdict + MUC label hash to the receipt journal so the host-
//!    side `verify` can re-bind the proof to the original `SmtTrace`.
//!
//! # Why the body is intentionally empty at Task 12.3a
//!
//! The guest program requires the `risc0-zkvm` guest API surface,
//! which in turn requires the rzup-installed RISC-V cross-compiler
//! (`riscv32im-risc0-zkvm-elf`). Both land at Task 12.3b; ADR-034 §3
//! amends the ADR-032 §5 / ADR-033 §3 "first-kernel-side-consumer"
//! deferral to recognize that the guest crate is itself a kernel-side
//! consumer of the workspace `risc0-zkvm` dep.
//!
//! Task 12.3a's deliverable is the scaffold (Cargo.toml + this file +
//! the workspace exclusion + the sha-pinned `fetch-zk` install
//! plumbing). Task 12.3b fills in the body + adds the dep + lands the
//! `extract → prove → verify` round-trip on the canonical fixture.
//!
//! # Cross-references
//!
//! - Host-side wire-format encoder: `crates/zk_kernel/src/witness.rs`
//!   ([`zk_kernel::witness::extract_witness`]).
//! - Host-side parser (used by 12.3b round-trip tests): same module's
//!   [`zk_kernel::witness::parse_witness`].
//! - Locked toolchain pin: ADR-032 §1 (Risc0 v3.0.1) — surfaces in
//!   `Justfile` as `ZK_TOOLCHAIN_VERSION` (env-overridable).
//! - Sha-pinned cargo-risczero tarball: ADR-034 §2 + Justfile
//!   `ZK_SHA256` constant.

#![forbid(unsafe_code)]
#![deny(clippy::all)]
#![cfg_attr(target_os = "zkvm", no_main)]
#![cfg_attr(target_os = "zkvm", no_std)]

#[cfg(target_os = "zkvm")]
fn main() {
    unreachable!(
        "zk-kernel-guest body lands at Task 12.3b (ADR-034 §3); the Task 12.3a scaffold has no executable path"
    );
}

#[cfg(not(target_os = "zkvm"))]
fn main() {
    // Host-side build is a sanity stub — the guest is never executed
    // outside the zkVM. Compiling it for the host target is supported
    // only so `cargo check` works ad-hoc on dev boxes that lack rzup;
    // the workspace excludes this crate by default (root `Cargo.toml`).
    eprintln!(
        "zk-kernel-guest is a Risc0 zkVM guest program; host-side execution is not supported (Task 12.3a scaffold)"
    );
}
