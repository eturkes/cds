//! Render an [`SmtConstraintMatrix`] to a self-contained SMT-LIBv2 script.
//!
//! The matrix carries a static [`preamble`](SmtConstraintMatrix::preamble)
//! (logic + sort/function declarations) and a list of named, retractable
//! [`LabelledAssertion`]s. This module wraps the assertions in
//! `(assert (! <formula> :named <label>))` form so:
//!
//! - **Z3** can return the unsat core via `(get-unsat-core)` as a
//!   parenthesised list of those labels.
//! - **cvc5** can reference the same labels in its Alethe `(assume <label> …)`
//!   steps, keeping the proof artifact and the MUC label set on a single
//!   stable identifier scheme.
//!
//! The rendered script is the *only* thing the warden ever ships to a
//! solver child — preamble + assertions + a single mode-dependent tail.

use crate::schema::SmtConstraintMatrix;

/// Which SMT-LIB tail commands to append after `(check-sat)`.
///
/// The two modes correspond to the two solver paths in Task 6:
/// Z3 yields an unsat core; cvc5 emits the Alethe proof via the
/// `--dump-proofs` CLI flag and so needs no extra script tail.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RenderMode {
    /// Prepend `(set-option :produce-unsat-cores true)` and append
    /// `(get-unsat-core)`. Used by the Z3 driver.
    UnsatCore,
    /// Bare `(check-sat)` script — the cvc5 driver supplies
    /// `--dump-proofs --proof-format-mode=alethe` on the command line.
    Proof,
}

/// Render `matrix` as an SMT-LIBv2 script.
///
/// Disabled assumptions are silently dropped, mirroring the
/// `check-sat-assuming` retraction semantics of the schema.
#[must_use]
pub fn render(matrix: &SmtConstraintMatrix, mode: RenderMode) -> String {
    let mut out = String::new();

    if mode == RenderMode::UnsatCore {
        out.push_str("(set-option :produce-unsat-cores true)\n");
    }

    out.push_str(&matrix.preamble);
    if !matrix.preamble.ends_with('\n') {
        out.push('\n');
    }

    for assumption in &matrix.assumptions {
        if !assumption.enabled {
            continue;
        }
        out.push_str("(assert (! ");
        out.push_str(&assumption.formula);
        out.push_str(" :named ");
        out.push_str(&assumption.label);
        out.push_str("))\n");
    }

    out.push_str("(check-sat)\n");
    if mode == RenderMode::UnsatCore {
        out.push_str("(get-unsat-core)\n");
    }
    out
}

#[cfg(test)]
mod tests {
    use super::{RenderMode, render};
    use crate::schema::{LabelledAssertion, SmtConstraintMatrix};

    fn fixture() -> SmtConstraintMatrix {
        SmtConstraintMatrix {
            schema_version: "0.1.0".to_string(),
            logic: "QF_LRA".to_string(),
            theories: vec!["LRA".to_string()],
            preamble: "(set-logic QF_LRA)\n(declare-fun spo2 () Real)\n".to_string(),
            assumptions: vec![
                LabelledAssertion {
                    label: "clause_000".to_string(),
                    formula: "(> spo2 95.0)".to_string(),
                    enabled: true,
                    provenance: Some("atom:contradictory-bound:0-4".to_string()),
                },
                LabelledAssertion {
                    label: "clause_001".to_string(),
                    formula: "(< spo2 90.0)".to_string(),
                    enabled: true,
                    provenance: Some("atom:contradictory-bound:15-19".to_string()),
                },
                LabelledAssertion {
                    label: "clause_002".to_string(),
                    formula: "(= spo2 100.0)".to_string(),
                    enabled: false,
                    provenance: None,
                },
            ],
        }
    }

    #[test]
    fn unsat_core_mode_brackets_assertions_and_appends_get_unsat_core() {
        let s = render(&fixture(), RenderMode::UnsatCore);
        assert!(s.starts_with("(set-option :produce-unsat-cores true)\n"));
        assert!(s.contains("(declare-fun spo2 () Real)"));
        assert!(s.contains("(assert (! (> spo2 95.0) :named clause_000))"));
        assert!(s.contains("(assert (! (< spo2 90.0) :named clause_001))"));
        assert!(s.contains("(check-sat)\n"));
        assert!(s.trim_end().ends_with("(get-unsat-core)"));
    }

    #[test]
    fn proof_mode_omits_get_unsat_core_and_option() {
        let s = render(&fixture(), RenderMode::Proof);
        assert!(!s.contains("produce-unsat-cores"));
        assert!(!s.contains("get-unsat-core"));
        assert!(s.trim_end().ends_with("(check-sat)"));
    }

    #[test]
    fn disabled_assertions_are_skipped() {
        let s = render(&fixture(), RenderMode::UnsatCore);
        assert!(!s.contains("clause_002"));
    }
}
