//! cvc5 driver — runs `.bin/cvc5 --dump-proofs --proof-format-mode=alethe`
//! via the warden and captures the Alethe certificate as a single string.
//!
//! The required cvc5 1.3 flags (verified 2026-04-30 against the cvc5
//! Alethe documentation) are:
//!
//! - `--dump-proofs` — emit the proof after `unsat`.
//! - `--proof-format-mode=alethe` — pick the Alethe dialect.
//! - `--simplification=none`, `--dag-thresh=0`,
//!   `--proof-granularity=theory-rewrite` — keep the proof in the
//!   restricted form Alethe currently supports.
//! - `--lang=smt2` — stdin has no extension to auto-detect from.
//!
//! The Alethe text returned here is what populates
//! [`FormalVerificationTrace::alethe_proof`]. Lean 4 / Kimina will
//! mechanically re-check it in Task 7.

use std::path::Path;
use std::time::Duration;

use crate::schema::SmtConstraintMatrix;

use super::SolverError;
use super::script::{RenderMode, render};
use super::warden::run_with_input;
use super::z3::Verdict;

/// Outcome of a single cvc5 invocation.
#[derive(Debug, Clone)]
pub struct Cvc5Outcome {
    /// Sat / unsat / unknown verdict from cvc5.
    pub verdict: Verdict,
    /// The Alethe proof S-expression (verbatim cvc5 stdout below the
    /// verdict line). `None` when `verdict != Unsat`.
    pub alethe_proof: Option<String>,
    /// Raw stdout, retained for diagnostics / logging.
    pub raw_stdout: String,
}

const CVC5_ALETHE_FLAGS: &[&str] = &[
    "--lang=smt2",
    "--dump-proofs",
    "--proof-format-mode=alethe",
    "--simplification=none",
    "--dag-thresh=0",
    "--proof-granularity=theory-rewrite",
];

/// Run cvc5 on the rendered script and parse the verdict + Alethe proof.
///
/// # Errors
/// Any [`SolverError`] from the warden, plus
/// [`SolverError::UnparseableOutput`] for unrecognised stdout shapes.
pub async fn run(
    matrix: &SmtConstraintMatrix,
    cvc5_path: &Path,
    timeout: Duration,
) -> Result<Cvc5Outcome, SolverError> {
    let script = render(matrix, RenderMode::Proof);
    let outcome = run_with_input(cvc5_path, CVC5_ALETHE_FLAGS, &script, timeout).await?;

    if !outcome.stderr.trim().is_empty() {
        tracing::debug!(target = "cds_kernel::solver::cvc5", stderr = %outcome.stderr.trim());
    }

    parse_outcome(&outcome.stdout)
}

fn parse_outcome(stdout: &str) -> Result<Cvc5Outcome, SolverError> {
    let mut lines = stdout.lines();
    let verdict_line = loop {
        match lines.next() {
            Some(line) if !line.trim().is_empty() => break line.trim(),
            Some(_) => {}
            None => {
                return Err(SolverError::UnparseableOutput(
                    "cvc5 produced no output".into(),
                ));
            }
        }
    };

    let verdict = match verdict_line {
        "sat" => Verdict::Sat,
        "unsat" => Verdict::Unsat,
        "unknown" => Verdict::Unknown,
        other if other.starts_with("(error") => {
            return Err(SolverError::Cvc5Error(stdout.trim().to_string()));
        }
        other => {
            return Err(SolverError::UnparseableOutput(format!(
                "cvc5: expected sat/unsat/unknown, got {other:?}"
            )));
        }
    };

    let alethe_proof = if verdict == Verdict::Unsat {
        let rest = lines.collect::<Vec<_>>().join("\n");
        let trimmed = rest.trim();
        if trimmed.is_empty() {
            None
        } else {
            Some(trimmed.to_string())
        }
    } else {
        None
    };

    Ok(Cvc5Outcome {
        verdict,
        alethe_proof,
        raw_stdout: stdout.to_string(),
    })
}

#[cfg(test)]
mod tests {
    use super::{Verdict, parse_outcome};

    #[test]
    fn parses_unsat_with_alethe_proof() {
        let stdout = "unsat\n(\n(assume c0 (> spo2 95/1))\n(step t0 (cl) :rule resolution)\n)\n";
        let outcome = parse_outcome(stdout).expect("parse");
        assert_eq!(outcome.verdict, Verdict::Unsat);
        let proof = outcome.alethe_proof.expect("alethe proof present");
        assert!(proof.starts_with('('));
        assert!(proof.contains("assume c0"));
        assert!(proof.contains(":rule resolution"));
    }

    #[test]
    fn parses_sat_without_proof() {
        let outcome = parse_outcome("sat\n").expect("parse");
        assert_eq!(outcome.verdict, Verdict::Sat);
        assert!(outcome.alethe_proof.is_none());
    }

    #[test]
    fn rejects_solver_error_lines() {
        let err = parse_outcome("(error \"bad input\")\n").expect_err("should error");
        match err {
            super::SolverError::Cvc5Error(msg) => assert!(msg.contains("error")),
            other => panic!("expected Cvc5Error, got {other:?}"),
        }
    }

    #[test]
    fn skips_leading_blank_lines() {
        let outcome = parse_outcome("\n\nsat\n").expect("parse");
        assert_eq!(outcome.verdict, Verdict::Sat);
    }
}
