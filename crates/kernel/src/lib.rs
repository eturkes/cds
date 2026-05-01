//! `cds-kernel` — neurosymbolic CDS deductive kernel.
//!
//! Phase 0 home of:
//! - The four conceptual schema types ([`schema`], Task 2) that form the
//!   wire format between every pipeline stage.
//! - The canonical-vital allowlist ([`canonical`]) — Rust mirror of the
//!   Python `cds_harness.ingest.canonical.CANONICAL_VITALS` constant.
//! - The deductive evaluator ([`deduce`], Task 5): in-process Datalog
//!   (`ascent`) + Octagon abstract domain over canonical vitals.
//! - The mathematical-solver layer ([`solver`], Task 6): subprocess
//!   warden + Z3 unsat-core extraction + cvc5 Alethe proof emission +
//!   MUC ↔ source-span projection — produces a
//!   [`schema::FormalVerificationTrace`] from an
//!   [`schema::SmtConstraintMatrix`].
//! - The Lean 4 re-check bridge ([`lean`], Task 7): wraps the cvc5
//!   Alethe proof in a self-contained Lean snippet and POSTs it to a
//!   running Kimina headless server (REST), surfacing a
//!   [`lean::LeanRecheck`] outcome.
//! - The Phase 0 kernel HTTP service ([`service`], Task 8.3a): an
//!   `axum` router exposing `/healthz` (and, in 8.3b, `/v1/deduce`,
//!   `/v1/solve`, `/v1/recheck`) under a Dapr sidecar named
//!   `cds-kernel`. ADR-018 captures the contract.

#![forbid(unsafe_code)]
#![deny(clippy::all)]

pub mod canonical;
pub mod deduce;
pub mod lean;
pub mod schema;
pub mod service;
pub mod solver;

/// Stable identifier for this crate. Consumed by smoke tests + future trace logs.
pub const KERNEL_ID: &str = "cds-kernel";

/// Phase marker. Bumped 0 → 1 at Task 9.3 close-out, when the
/// stakeholder visualizer demonstrably round-trips the Phase 0 success
/// criterion (Plan §8 row 9: "UI shows live trace from real dataset;
/// verification flag round-trips"). Phase 1 scope per Plan §1: live
/// FHIR streaming, distributed cloud, ZKSMT.
pub const PHASE: u8 = 1;

/// Returns whether the kernel identifier is well-formed (ASCII, kebab-case).
#[must_use]
pub fn kernel_id_is_well_formed() -> bool {
    !KERNEL_ID.is_empty()
        && KERNEL_ID
            .chars()
            .all(|c| c.is_ascii() && (c.is_ascii_lowercase() || c == '-'))
}

#[cfg(test)]
mod tests {
    use super::{KERNEL_ID, PHASE, kernel_id_is_well_formed};

    #[test]
    fn kernel_id_is_stable() {
        assert_eq!(KERNEL_ID, "cds-kernel");
    }

    #[test]
    fn kernel_id_passes_well_formedness_check() {
        assert!(kernel_id_is_well_formed());
    }

    #[test]
    fn phase_one_is_active() {
        assert_eq!(
            PHASE, 1,
            "phase marker advances to 1 at Task 9.3 close-out (UI round-trip)"
        );
    }
}
