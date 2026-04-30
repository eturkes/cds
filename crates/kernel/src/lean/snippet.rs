//! Lean 4 snippet generator for the Kimina re-check.
//!
//! Phase 0 ships a *structural* re-check: the snippet defines the cvc5
//! Alethe proof as a Lean `String`, then runs four `#eval` probes whose
//! info-message output is round-tripped back through the Kimina REST
//! response and parsed by [`super::client`]. This proves the Alethe
//! certificate has been ingested by the Lean 4 kernel via the JSON-over-
//! TCP boundary (constraint **C6**) and lays the wiring for a future
//! ADR that swaps in a foundational re-check (e.g. `lean-smt`'s Alethe
//! importer) without changing the bridge surface.
//!
//! The snippet is deliberately self-contained — no `import Mathlib`,
//! no `Std.*` imports — so the Kimina REPL's LRU header cache stays
//! cheap and the per-call elapsed time stays in single-digit seconds.
//!
//! ## Probe contract
//!
//! Four `#eval` lines print probe strings of the form
//! `PROBE <name>=<value>` to Lean's info messages. The Rust client
//! requires all four to land before declaring `LeanRecheck::ok`:
//!
//! | Probe                  | Expected value                                                    |
//! | ---------------------- | ----------------------------------------------------------------- |
//! | `PROBE byte_len=N`     | `N` is `alethe_proof.length` (must be > 0 for a non-empty proof). |
//! | `PROBE starts_paren=B` | `true` — every Alethe S-expression begins with `(`.               |
//! | `PROBE has_assume=B`   | `true` — Alethe proofs reference labelled assumptions.            |
//! | `PROBE has_rule=B`     | `true` — Alethe proofs carry `:rule` annotations on every step.   |
//!
//! The snippet escapes `\` and `"` so the proof body can be embedded in
//! a Lean string literal verbatim — no raw-string `r#"..."#` density
//! counting, no out-of-band hex decoder.

/// Render a self-contained Lean 4 snippet that defines the Alethe proof
/// as a `String` and runs the four `PROBE` `#eval` lines.
#[must_use]
pub fn render(alethe_proof: &str) -> String {
    let escaped = escape_lean_string(alethe_proof);
    let mut out = String::with_capacity(escaped.len() + 512);
    out.push_str("-- cds-kernel Phase 0 Lean re-check probe (Task 7).\n");
    out.push_str("def alethe_proof : String := \"");
    out.push_str(&escaped);
    out.push_str("\"\n\n");
    out.push_str("#eval s!\"PROBE byte_len={alethe_proof.length}\"\n");
    out.push_str("#eval s!\"PROBE starts_paren={\\\"(\\\".isPrefixOf alethe_proof}\"\n");
    out.push_str(
        "#eval s!\"PROBE has_assume={(alethe_proof.splitOn \\\"(assume\\\").length > 1}\"\n",
    );
    out.push_str("#eval s!\"PROBE has_rule={(alethe_proof.splitOn \\\":rule\\\").length > 1}\"\n");
    out
}

/// Escape `s` for embedding inside a Lean 4 double-quoted string literal.
///
/// Lean's lexer treats `\\`, `\"`, `\n`, `\r`, `\t` as escape sequences
/// inside `"..."` literals. Every other byte (including the rest of
/// ASCII control characters and arbitrary UTF-8) is left verbatim — the
/// Alethe proof is well-formed UTF-8 by construction (cvc5 emits
/// printable ASCII modulo whitespace) and Lean accepts UTF-8 strings.
#[must_use]
pub fn escape_lean_string(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for ch in s.chars() {
        match ch {
            '\\' => out.push_str("\\\\"),
            '"' => out.push_str("\\\""),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            other => out.push(other),
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::{escape_lean_string, render};

    #[test]
    fn escape_passes_plain_ascii() {
        assert_eq!(
            escape_lean_string("(assume c0 (> x 0))"),
            "(assume c0 (> x 0))"
        );
    }

    #[test]
    fn escape_handles_quotes_and_backslashes() {
        let raw = "say \"hi\" with a \\backslash";
        let esc = escape_lean_string(raw);
        assert_eq!(esc, "say \\\"hi\\\" with a \\\\backslash");
    }

    #[test]
    fn escape_handles_newlines_and_tabs() {
        let raw = "line1\n\tline2\r";
        let esc = escape_lean_string(raw);
        assert_eq!(esc, "line1\\n\\tline2\\r");
    }

    #[test]
    fn escape_passes_utf8_bmp_glyphs() {
        let raw = "≥ µ °C";
        let esc = escape_lean_string(raw);
        assert_eq!(esc, "≥ µ °C");
    }

    #[test]
    fn render_embeds_proof_and_all_four_probes() {
        let snippet = render("(assume c0 (> spo2 95/1))\n(step t0 (cl) :rule resolution)\n");
        assert!(snippet.contains("def alethe_proof : String := \""));
        // Newlines in the proof escape into `\n` inside the string literal.
        assert!(snippet.contains("(assume c0 (> spo2 95/1))\\n(step t0 (cl) :rule resolution)\\n"));
        assert!(snippet.contains("PROBE byte_len="));
        assert!(snippet.contains("PROBE starts_paren="));
        assert!(snippet.contains("PROBE has_assume="));
        assert!(snippet.contains("PROBE has_rule="));
        // Lean meta-syntax probes use `s!"..."` interpolation.
        assert!(snippet.contains("s!\"PROBE byte_len={alethe_proof.length}\""));
    }

    #[test]
    fn render_is_self_contained_no_imports() {
        let snippet = render("()");
        assert!(
            !snippet.contains("import "),
            "snippet must not import to keep Kimina LRU cache cheap"
        );
        assert!(
            !snippet.contains("open "),
            "snippet must not open namespaces"
        );
    }

    #[test]
    fn render_handles_empty_proof_string() {
        // Edge case: cvc5 should never emit empty, but the bridge must
        // still produce well-formed Lean. The byte_len probe will print
        // `PROBE byte_len=0`, which the client treats as failure.
        let snippet = render("");
        assert!(snippet.contains("def alethe_proof : String := \"\""));
        assert!(snippet.contains("PROBE byte_len="));
    }
}
