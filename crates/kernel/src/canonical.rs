//! Canonical vital-key allowlist (Rust mirror of
//! `cds_harness.ingest.canonical.CANONICAL_VITALS`).
//!
//! The Phase 0 namespace is intentionally tiny so that the deductive engine
//! can address scalars by predictable name (ADR-011) and the wire format
//! stays byte-stable across Rust ↔ Python (ADR-010). The slice is pinned in
//! lexicographic order to mirror the `BTreeMap<String, f64>` serialization
//! convention; the unit test below is the tripwire.
//!
//! Adding a new canonical vital is a coordinated edit across the Python
//! ingest constant, the translator (Task 4), this slice (Task 5), and the
//! Z3/cvc5 wiring (Task 6); treat as ADR-grade per ADR-011.

/// Canonical vital observation names recognised by the Phase 0 kernel.
/// Lexicographically sorted; identical set to the Python frozenset.
pub const CANONICAL_VITALS: [&str; 6] = [
    "diastolic_mmhg",
    "heart_rate_bpm",
    "respiratory_rate_bpm",
    "spo2_percent",
    "systolic_mmhg",
    "temp_celsius",
];

/// Returns `true` iff `name` belongs to the Phase 0 canonical-vital allowlist.
#[must_use]
pub fn is_canonical_vital(name: &str) -> bool {
    CANONICAL_VITALS.contains(&name)
}

/// Position of `name` in `CANONICAL_VITALS`, or `None` for non-canonical names.
#[must_use]
pub fn vital_index(name: &str) -> Option<usize> {
    CANONICAL_VITALS.iter().position(|v| *v == name)
}

#[cfg(test)]
mod tests {
    use super::{CANONICAL_VITALS, is_canonical_vital, vital_index};

    #[test]
    fn canonical_vitals_are_lexicographic() {
        let mut sorted = CANONICAL_VITALS;
        sorted.sort_unstable();
        assert_eq!(sorted, CANONICAL_VITALS);
    }

    #[test]
    fn membership_is_exact() {
        assert!(is_canonical_vital("heart_rate_bpm"));
        assert!(is_canonical_vital("spo2_percent"));
        assert!(!is_canonical_vital("HEART_RATE_BPM"));
        assert!(!is_canonical_vital("glucose_mgdl"));
        assert!(!is_canonical_vital(""));
    }

    #[test]
    fn vital_indices_are_stable() {
        assert_eq!(vital_index("diastolic_mmhg"), Some(0));
        assert_eq!(vital_index("temp_celsius"), Some(5));
        assert_eq!(vital_index("unknown"), None);
    }
}
