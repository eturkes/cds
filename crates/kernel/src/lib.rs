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

#![forbid(unsafe_code)]
#![deny(clippy::all)]

pub mod canonical;
pub mod deduce;
pub mod lean;
pub mod schema;
pub mod solver;

/// Stable identifier for this crate. Consumed by smoke tests + future trace logs.
pub const KERNEL_ID: &str = "cds-kernel";

/// Phase 0 marker. Bumped to 1 when the SMT layer lands.
pub const PHASE: u8 = 0;

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
    fn phase_zero_is_active() {
        assert_eq!(PHASE, 0, "phase marker must be 0 until SMT integration");
    }
}
