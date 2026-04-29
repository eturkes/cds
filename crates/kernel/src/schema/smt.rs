//! `SMT_Constraint_Matrix` — the SMT-LIBv2 program presented to Z3 / cvc5.
//!
//! `preamble` carries the static portion of the SMT-LIBv2 program: logic
//! declaration, theory imports, sort + function declarations. `assumptions`
//! carries the dynamic, retractable portion: each assertion is named and can
//! be toggled in or out of the `check-sat-assuming` set without re-emitting
//! the preamble. `provenance` traces an assumption back to the `OnionL`
//! atom id whose contradiction triggers it (constraint C4).

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SmtConstraintMatrix {
    pub schema_version: String,
    /// SMT-LIB logic identifier (e.g. `QF_LRA`, `QF_LIA`, `QF_AUFLIRA`).
    pub logic: String,
    /// Subset of SMT-LIB theories actively in use (e.g. `["LRA"]`).
    pub theories: Vec<String>,
    /// Static SMT-LIBv2 program text — declarations, sorts, function syms.
    pub preamble: String,
    /// Retractable named assertions; subject to `check-sat-assuming`.
    pub assumptions: Vec<LabelledAssertion>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct LabelledAssertion {
    /// Stable identifier passed to `check-sat-assuming`.
    pub label: String,
    /// SMT-LIBv2 boolean formula text.
    pub formula: String,
    /// Whether the assertion is currently active in the assumption set.
    pub enabled: bool,
    /// Trace back to the `OnionL` atom that produced this assertion. `None`
    /// only for assertions synthesized by the kernel (e.g. domain bounds).
    pub provenance: Option<String>,
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fixture() -> SmtConstraintMatrix {
        SmtConstraintMatrix {
            schema_version: "0.1.0".to_string(),
            logic: "QF_LRA".to_string(),
            theories: vec!["LRA".to_string()],
            preamble: "(set-logic QF_LRA)\n(declare-fun hba1c () Real)\n".to_string(),
            assumptions: vec![
                LabelledAssertion {
                    label: "guideline-1-bound".to_string(),
                    formula: "(< hba1c 7.0)".to_string(),
                    enabled: true,
                    provenance: Some("atom:guideline-001:31-60".to_string()),
                },
                LabelledAssertion {
                    label: "kernel-domain-bound".to_string(),
                    formula: "(>= hba1c 0.0)".to_string(),
                    enabled: true,
                    provenance: None,
                },
            ],
        }
    }

    #[test]
    fn round_trip_json() {
        let original = fixture();
        let serialized = serde_json::to_string(&original).expect("serialize");
        let deserialized: SmtConstraintMatrix =
            serde_json::from_str(&serialized).expect("deserialize");
        assert_eq!(original, deserialized);
    }

    #[test]
    fn provenance_is_optional() {
        let mut m = fixture();
        m.assumptions[1].provenance = None;
        let json = serde_json::to_string(&m).expect("serialize");
        let parsed: SmtConstraintMatrix = serde_json::from_str(&json).expect("deserialize");
        assert!(parsed.assumptions[1].provenance.is_none());
    }
}
