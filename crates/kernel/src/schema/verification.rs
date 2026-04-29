//! `Formal_Verification_Trace` — outcome of one SMT + ITP verification cycle.
//!
//! On `sat = false`, `muc` enumerates the textual node identifiers (matching
//! `LabelledAssertion::label` and projecting back to `OnionLNode::Atom::source_span`)
//! that participate in a Minimal Unsatisfiable Core. `alethe_proof` carries
//! the cvc5-emitted Alethe certificate as a Lean-4-ingestible string, ready
//! to be re-checked by the Kimina headless server (Task 7).

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct FormalVerificationTrace {
    pub schema_version: String,
    /// SMT verdict: `true` = consistent, `false` = contradiction found.
    pub sat: bool,
    /// Minimal Unsatisfiable Core: assertion labels (== `OnionL` atom ids).
    /// Empty when `sat = true`.
    pub muc: Vec<String>,
    /// Alethe / LFSC proof text. `None` while sat or before cvc5 emits one.
    pub alethe_proof: Option<String>,
}

#[cfg(test)]
mod tests {
    use super::*;

    fn unsat_fixture() -> FormalVerificationTrace {
        FormalVerificationTrace {
            schema_version: "0.1.0".to_string(),
            sat: false,
            muc: vec![
                "atom:guideline-001:31-60".to_string(),
                "atom:guideline-002:0-30".to_string(),
            ],
            alethe_proof: Some("(proof (anchor :step t1) (step t1 ...))".to_string()),
        }
    }

    fn sat_fixture() -> FormalVerificationTrace {
        FormalVerificationTrace {
            schema_version: "0.1.0".to_string(),
            sat: true,
            muc: vec![],
            alethe_proof: None,
        }
    }

    #[test]
    fn round_trip_json_unsat() {
        let original = unsat_fixture();
        let serialized = serde_json::to_string(&original).expect("serialize");
        let deserialized: FormalVerificationTrace =
            serde_json::from_str(&serialized).expect("deserialize");
        assert_eq!(original, deserialized);
    }

    #[test]
    fn round_trip_json_sat() {
        let original = sat_fixture();
        let serialized = serde_json::to_string(&original).expect("serialize");
        let deserialized: FormalVerificationTrace =
            serde_json::from_str(&serialized).expect("deserialize");
        assert_eq!(original, deserialized);
    }

    #[test]
    fn sat_carries_empty_muc() {
        let trace = sat_fixture();
        assert!(trace.muc.is_empty(), "sat verdict must have empty MUC");
        assert!(trace.alethe_proof.is_none(), "sat verdict carries no proof");
    }
}
