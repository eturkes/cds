//! Mathematical-solver integration (Phase 0, Task 6).
//!
//! Verifies an [`SmtConstraintMatrix`] against external Z3 and cvc5
//! children supervised by the [`warden`] (per **ADR-004**) and emits a
//! [`FormalVerificationTrace`] populated with:
//!
//! - `sat` — overall verdict (Z3 is the primary engine; cvc5 must
//!   agree on `unsat` before a proof artifact is accepted).
//! - `muc` — minimal-unsatisfiable-core labels lifted from the unsat
//!   core through each [`LabelledAssertion::provenance`] string into
//!   `atom:<doc>:<start>-<end>` form, satisfying the C4 round-trip
//!   from contradiction back to the offending textual span.
//! - `alethe_proof` — verbatim Alethe S-expression emitted by cvc5,
//!   ready for Lean 4 / Kimina re-checking in Task 7.
//!
//! Submodules:
//!
//! | Module       | Responsibility                                                    |
//! | ------------ | ----------------------------------------------------------------- |
//! | [`warden`]   | tokio `Command` + `kill_on_drop(true)` + wall-clock timeout.       |
//! | [`script`]   | `SmtConstraintMatrix` → SMT-LIBv2 script with named assertions.   |
//! | [`z3`]       | Z3 driver: invokes `z3 -smt2 -in`, returns verdict + unsat core.  |
//! | [`cvc5`]     | cvc5 driver: invokes `cvc5 --dump-proofs ...`, captures Alethe.    |

pub mod cvc5;
pub mod script;
pub mod warden;
pub mod z3;

use std::collections::BTreeMap;
use std::path::PathBuf;
use std::time::Duration;

use crate::schema::{FormalVerificationTrace, SCHEMA_VERSION, SmtConstraintMatrix};

pub use cvc5::Cvc5Outcome;
pub use script::{RenderMode, render};
pub use warden::{RunOutcome, WardenError};
pub use z3::{Verdict, Z3Outcome};

/// Knobs for [`verify`].
///
/// Defaults: 30 s wall-clock per child; bare `z3` / `cvc5` resolved via
/// `$PATH` (Phase 0 convention: `.bin/` is `PATH`-prefixed by the
/// `Justfile`, see ADR-008).
#[derive(Debug, Clone)]
pub struct VerifyOptions {
    pub timeout: Duration,
    pub z3_path: PathBuf,
    pub cvc5_path: PathBuf,
}

impl Default for VerifyOptions {
    fn default() -> Self {
        Self {
            timeout: Duration::from_secs(30),
            z3_path: PathBuf::from("z3"),
            cvc5_path: PathBuf::from("cvc5"),
        }
    }
}

/// Errors raised by the solver layer.
#[derive(Debug, thiserror::Error)]
pub enum SolverError {
    /// Subprocess warden failure (spawn, IO, or wall-clock timeout).
    #[error(transparent)]
    Warden(#[from] WardenError),
    /// Solver stdout did not match a recognised SMT-LIBv2 response.
    #[error("solver returned unparseable output: {0}")]
    UnparseableOutput(String),
    /// Z3 produced an explicit `(error ...)` response.
    #[error("z3 reported an error: {0}")]
    Z3Error(String),
    /// cvc5 produced an explicit `(error ...)` response.
    #[error("cvc5 reported an error: {0}")]
    Cvc5Error(String),
    /// Z3 returned `unknown` — Phase 0 will not fabricate a verdict.
    #[error("solver returned `unknown` verdict (not enough information to certify)")]
    UnknownVerdict,
    /// Z3 and cvc5 disagreed on sat / unsat. Surfaces an integrity
    /// failure rather than silently picking a winner.
    #[error("solver disagreement: z3={z3:?} cvc5={cvc5:?}")]
    SolverDisagreement { z3: Verdict, cvc5: Verdict },
}

/// Verify `matrix` against Z3 + cvc5 and produce a
/// [`FormalVerificationTrace`].
///
/// Pipeline:
///
/// 1. Z3 decides sat / unsat / unknown and (when unsat) emits the unsat
///    core label set.
/// 2. On `unsat`, cvc5 re-checks and emits an Alethe proof. Disagreement
///    is a hard error.
/// 3. The unsat-core labels are projected through
///    [`LabelledAssertion::provenance`] into `atom:<doc>:<start>-<end>`
///    spans (constraint **C4**: MUC ↔ source-span).
///
/// # Errors
/// See [`SolverError`].
pub async fn verify(
    matrix: &SmtConstraintMatrix,
    opts: &VerifyOptions,
) -> Result<FormalVerificationTrace, SolverError> {
    let z3_outcome = z3::run(matrix, &opts.z3_path, opts.timeout).await?;

    let trace = match z3_outcome.verdict {
        Verdict::Sat => FormalVerificationTrace {
            schema_version: SCHEMA_VERSION.to_string(),
            sat: true,
            muc: Vec::new(),
            alethe_proof: None,
        },
        Verdict::Unknown => return Err(SolverError::UnknownVerdict),
        Verdict::Unsat => {
            let cvc5_outcome = cvc5::run(matrix, &opts.cvc5_path, opts.timeout).await?;
            if cvc5_outcome.verdict != Verdict::Unsat {
                return Err(SolverError::SolverDisagreement {
                    z3: z3_outcome.verdict,
                    cvc5: cvc5_outcome.verdict,
                });
            }
            let muc = project_muc(&z3_outcome.unsat_core, matrix);
            FormalVerificationTrace {
                schema_version: SCHEMA_VERSION.to_string(),
                sat: false,
                muc,
                alethe_proof: cvc5_outcome.alethe_proof,
            }
        }
    };

    Ok(trace)
}

/// Lift unsat-core labels through `matrix.assumptions[*].provenance`
/// into source-span identifiers. Labels with no provenance fall back
/// to the bare label so a kernel-synthesised assertion (e.g. a domain
/// bound) still surfaces in the MUC. Output is sorted + deduplicated
/// for byte-stable `FormalVerificationTrace` JSON.
#[must_use]
pub fn project_muc(labels: &[String], matrix: &SmtConstraintMatrix) -> Vec<String> {
    let lookup: BTreeMap<&str, Option<&str>> = matrix
        .assumptions
        .iter()
        .map(|a| (a.label.as_str(), a.provenance.as_deref()))
        .collect();

    let mut out: Vec<String> = labels
        .iter()
        .map(|label| match lookup.get(label.as_str()) {
            Some(Some(prov)) => (*prov).to_string(),
            Some(None) | None => label.clone(),
        })
        .collect();
    out.sort();
    out.dedup();
    out
}

#[cfg(test)]
mod tests {
    use super::project_muc;
    use crate::schema::{LabelledAssertion, SmtConstraintMatrix};

    fn matrix_with_provenance() -> SmtConstraintMatrix {
        SmtConstraintMatrix {
            schema_version: "0.1.0".to_string(),
            logic: "QF_LRA".to_string(),
            theories: vec!["LRA".to_string()],
            preamble: "(set-logic QF_LRA)\n".to_string(),
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
                    label: "kernel_bound_000".to_string(),
                    formula: "(>= spo2 0.0)".to_string(),
                    enabled: true,
                    provenance: None,
                },
            ],
        }
    }

    #[test]
    fn projects_labels_through_provenance() {
        let labels = vec!["clause_001".to_string(), "clause_000".to_string()];
        let muc = project_muc(&labels, &matrix_with_provenance());
        assert_eq!(
            muc,
            vec![
                "atom:contradictory-bound:0-4".to_string(),
                "atom:contradictory-bound:15-19".to_string(),
            ]
        );
    }

    #[test]
    fn falls_back_to_bare_label_for_missing_provenance() {
        let labels = vec!["kernel_bound_000".to_string()];
        let muc = project_muc(&labels, &matrix_with_provenance());
        assert_eq!(muc, vec!["kernel_bound_000".to_string()]);
    }

    #[test]
    fn unknown_label_passes_through_verbatim() {
        let labels = vec!["never_emitted".to_string()];
        let muc = project_muc(&labels, &matrix_with_provenance());
        assert_eq!(muc, vec!["never_emitted".to_string()]);
    }

    #[test]
    fn projection_is_sorted_and_deduplicated() {
        let labels = vec![
            "clause_001".to_string(),
            "clause_000".to_string(),
            "clause_001".to_string(),
        ];
        let muc = project_muc(&labels, &matrix_with_provenance());
        assert_eq!(muc.len(), 2);
        assert!(muc.windows(2).all(|w| w[0] < w[1]));
    }
}
