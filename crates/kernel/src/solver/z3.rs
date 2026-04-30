//! Z3 driver — runs a `.bin/z3 -smt2 -in` child via the warden, asks for an
//! unsat core, and returns the labels that participate in it.
//!
//! The unsat-core list maps 1:1 to [`LabelledAssertion::label`] strings; the
//! `solver::project_muc` helper lifts them to source-span provenance, which
//! lands in [`FormalVerificationTrace::muc`].
//!
//! Why Z3 for the core (and cvc5 for the proof)? **ADR-006**: Z3 has the
//! stronger CDCL(T) ergonomics for the workload and exposes
//! `check-sat-assuming` retraction; cvc5 owns the foundationally-checked
//! Alethe / LFSC proof format.

use std::path::Path;
use std::time::Duration;

use crate::schema::SmtConstraintMatrix;

use super::SolverError;
use super::script::{RenderMode, render};
use super::warden::run_with_input;

/// Sat / unsat / unknown verdict as reported by an SMT solver.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Verdict {
    Sat,
    Unsat,
    Unknown,
}

/// Outcome of a single Z3 invocation against an [`SmtConstraintMatrix`].
#[derive(Debug, Clone)]
pub struct Z3Outcome {
    /// Sat / unsat / unknown.
    pub verdict: Verdict,
    /// Assertion labels participating in the unsat core. Empty when
    /// `verdict != Unsat`. Order is whatever Z3 produced — callers
    /// that require determinism must sort.
    pub unsat_core: Vec<String>,
    /// Raw stdout, retained for diagnostics / logging.
    pub raw_stdout: String,
}

/// Run `z3 -smt2 -in` on the rendered SMT script and parse the result.
///
/// # Errors
/// Any [`SolverError`] from the warden, plus
/// [`SolverError::UnparseableOutput`] when the verdict line cannot be
/// recognised.
pub async fn run(
    matrix: &SmtConstraintMatrix,
    z3_path: &Path,
    timeout: Duration,
) -> Result<Z3Outcome, SolverError> {
    let script = render(matrix, RenderMode::UnsatCore);
    let outcome = run_with_input(z3_path, &["-smt2", "-in"], &script, timeout).await?;

    if !outcome.stderr.trim().is_empty() {
        // Z3 prints warnings to stderr; only surface as an error if stdout
        // is also unrecognisable (handled by `parse_outcome`).
        tracing::debug!(target = "cds_kernel::solver::z3", stderr = %outcome.stderr.trim());
    }

    parse_outcome(&outcome.stdout)
}

fn parse_outcome(stdout: &str) -> Result<Z3Outcome, SolverError> {
    let mut lines = stdout.lines().peekable();
    while lines.peek().is_some_and(|l| l.trim().is_empty()) {
        lines.next();
    }
    let verdict_line = lines
        .next()
        .ok_or_else(|| SolverError::UnparseableOutput("z3 produced no output".into()))?
        .trim();

    let verdict = match verdict_line {
        "sat" => Verdict::Sat,
        "unsat" => Verdict::Unsat,
        "unknown" => Verdict::Unknown,
        other if other.starts_with("(error") => {
            return Err(SolverError::Z3Error(stdout.trim().to_string()));
        }
        other => {
            return Err(SolverError::UnparseableOutput(format!(
                "z3: expected sat/unsat/unknown, got {other:?}"
            )));
        }
    };

    let unsat_core = if verdict == Verdict::Unsat {
        parse_label_list(&lines.collect::<Vec<_>>().join("\n"))
    } else {
        Vec::new()
    };

    Ok(Z3Outcome {
        verdict,
        unsat_core,
        raw_stdout: stdout.to_string(),
    })
}

/// Parse a `(label_a label_b ...)` SMT-LIB list into a `Vec<String>`.
fn parse_label_list(s: &str) -> Vec<String> {
    let trimmed = s.trim();
    let inside = trimmed.trim_start_matches('(').trim_end_matches(')');
    inside
        .split_whitespace()
        .map(str::to_string)
        .collect::<Vec<_>>()
}

#[cfg(test)]
mod tests {
    use super::{Verdict, parse_label_list, parse_outcome};

    #[test]
    fn parses_sat_with_no_core() {
        let outcome = parse_outcome("sat\n").expect("parse");
        assert_eq!(outcome.verdict, Verdict::Sat);
        assert!(outcome.unsat_core.is_empty());
    }

    #[test]
    fn parses_unsat_with_core() {
        let outcome = parse_outcome("unsat\n(clause_000 clause_001)\n").expect("parse");
        assert_eq!(outcome.verdict, Verdict::Unsat);
        assert_eq!(outcome.unsat_core, vec!["clause_000", "clause_001"]);
    }

    #[test]
    fn parses_unknown() {
        let outcome = parse_outcome("unknown\n").expect("parse");
        assert_eq!(outcome.verdict, Verdict::Unknown);
        assert!(outcome.unsat_core.is_empty());
    }

    #[test]
    fn rejects_solver_error_lines() {
        let err = parse_outcome("(error \"line 1 column 0: bad\")\n").expect_err("should error");
        match err {
            super::SolverError::Z3Error(msg) => assert!(msg.contains("error")),
            other => panic!("expected Z3Error, got {other:?}"),
        }
    }

    #[test]
    fn label_list_handles_extra_whitespace() {
        let labels = parse_label_list("(  a   b\n c  )");
        assert_eq!(labels, vec!["a", "b", "c"]);
    }

    #[test]
    fn label_list_empty_parens() {
        let labels = parse_label_list("()");
        assert!(labels.is_empty());
    }
}
