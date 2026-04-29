//! `cds-kernel` — neurosymbolic CDS deductive kernel.
//!
//! Phase 0 home of (a) the four conceptual schema types (`schema` module,
//! Task 2) that form the wire format between every pipeline stage, and
//! (b) — landing in Task 5 — the Nemo Datalog evaluator, Octagon
//! abstract-interpretation domain, and subprocess warden.

#![forbid(unsafe_code)]
#![deny(clippy::all)]

pub mod schema;

/// Stable identifier for this crate. Consumed by smoke tests + future trace logs.
pub const KERNEL_ID: &str = "cds-kernel";

/// Phase 0 marker. Bumped to 1 when Task 5 lands real kernel logic.
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
        assert_eq!(PHASE, 0, "phase marker must be 0 until Task 5 lands");
    }
}
