//! `zk-kernel` — Phase 1 ZKSMT post-quantum proof attestation kernel.
//!
//! Foundation declared at Task 12.1 (ADR-032). Witness gen wired at
//! Task 12.2 (ADR-033). Install plumbing + guest crate scaffold at
//! Task 12.3a (ADR-034). Prove + verify body fills + `risc0-zkvm`
//! workspace + host + guest deps at Task 12.3b1 (ADR-035 — this
//! commit). The matching `zk-prove-smoke` Justfile recipe + the
//! canonical `extract → prove → verify` round-trip integration test
//! at Task 12.3b2 (deferred).
//!
//! # Toolchain lock (ADR-032 + ADR-035)
//!
//! - **zkVM:** [Risc0](https://github.com/risc0/risc0) v3.0.1 — zk-STARK
//!   proving via Plonky3-style FRI over collision-resistant hashes →
//!   post-quantum secure (Plan §1's "ZKSMT post-quantum" requirement).
//!   Cargo dep `=3.0.5` in lockstep with the sha-pinned cargo-risczero
//!   tarball staged by `just fetch-zk` (ADR-035 §2 supersedes ADR-034
//!   §2's v3.0.1 pin — v3.0.1's transitive `risc0-circuit-rv32im 4.0.4`
//!   fails to compile on rustc 1.95.0; v3.0.5 fixes it). Bumping
//!   requires a coordinated change: new sha256 + new
//!   `ZK_TOOLCHAIN_VERSION` + new ADR.
//! - **Candidate:** [SP1](https://github.com/succinctlabs/sp1) — locked
//!   as the alternative if Risc0 prove latency proves binding at
//!   Task 12.3b2's smoke. Same STARK-family security properties.
//! - **Rejected:** Halo2 / PLONK — circuit-based (not zkVM), pairing-
//!   friendly elliptic-curve dependency breaks the post-quantum
//!   invariant.

#![forbid(unsafe_code)]
#![deny(clippy::all)]

pub mod errors;
pub mod prove;
pub mod verify;
pub mod witness;

/// Stable identifier for this crate. Consumed by smoke tests + future trace logs.
pub const ZK_KERNEL_ID: &str = "zk-kernel";

/// Phase marker. Stays at 1 across all Phase 1 sub-tasks (10.x / 11.x /
/// 12.x). Flips 1 → 2 at Task 12.4 close-out per ADR-024 §4.
pub const PHASE: u8 = 1;

/// Locked zkVM toolchain identifier (ADR-032 §1). Override via
/// `ZK_TOOLCHAIN` env var if a future ADR amends the lock.
pub const ZK_TOOLCHAIN: &str = "risc0";

/// Pinned major-line version for the locked toolchain (ADR-032 §1).
/// Risc0 v3.0.1 is the 2026 latest stable as of the Task 12.1 web-search;
/// Task 12.2 may bump within the v3.x line when adding `risc0-zkvm`.
pub const ZK_TOOLCHAIN_VERSION: &str = "3.0.1";

/// Returns whether the kernel identifier is well-formed (ASCII, kebab-case).
#[must_use]
pub fn zk_kernel_id_is_well_formed() -> bool {
    !ZK_KERNEL_ID.is_empty()
        && ZK_KERNEL_ID
            .chars()
            .all(|c| c.is_ascii() && (c.is_ascii_lowercase() || c == '-'))
}

/// Returns whether the locked zkVM toolchain provides post-quantum
/// security guarantees per ADR-032 §1.
///
/// Risc0 + SP1 both rely on STARK-family proving (FRI over collision-
/// resistant hashes) → post-quantum. Halo2 / PLONK depend on pairing-
/// friendly elliptic curves → NOT post-quantum.
#[must_use]
pub fn zk_toolchain_is_post_quantum() -> bool {
    matches!(ZK_TOOLCHAIN, "risc0" | "sp1")
}

#[cfg(test)]
mod tests {
    use super::{
        PHASE, ZK_KERNEL_ID, ZK_TOOLCHAIN, ZK_TOOLCHAIN_VERSION, zk_kernel_id_is_well_formed,
        zk_toolchain_is_post_quantum,
    };

    #[test]
    fn zk_kernel_id_is_stable() {
        assert_eq!(ZK_KERNEL_ID, "zk-kernel");
    }

    #[test]
    fn zk_kernel_id_passes_well_formedness_check() {
        assert!(zk_kernel_id_is_well_formed());
    }

    #[test]
    fn phase_one_is_active() {
        assert_eq!(
            PHASE, 1,
            "PHASE stays at 1 across Phase 1; flip 1 → 2 at Task 12.4 close-out (ADR-024 §4)"
        );
    }

    #[test]
    fn zk_toolchain_is_locked_to_risc0() {
        assert_eq!(ZK_TOOLCHAIN, "risc0", "ADR-032 §1 locks Risc0 as the zkVM");
    }

    #[test]
    fn zk_toolchain_version_matches_v3_line() {
        assert!(
            ZK_TOOLCHAIN_VERSION.starts_with("3."),
            "ADR-032 §1 pins the v3.x major line; got {ZK_TOOLCHAIN_VERSION}"
        );
    }

    #[test]
    fn zk_toolchain_satisfies_post_quantum_invariant() {
        assert!(
            zk_toolchain_is_post_quantum(),
            "ADR-032 §1: locked toolchain must be post-quantum (STARK family)"
        );
    }
}
