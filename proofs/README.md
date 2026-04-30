# Proof artifacts

Phase 0 stages mechanically-emitted Alethe / LFSC proof certificates here so
they are inspectable in `git diff` and re-checkable by Lean 4 / Kimina (Task 7).

## File layout

- `<doc-id>.alethe.proof` — cvc5-emitted Alethe proof for the contradictory
  guideline `<doc-id>`. The first line is `unsat`; the remainder is the
  Alethe S-expression. `(assume <label> ...)` lines reference the same
  `LabelledAssertion::label` strings the Z3 driver returns in its unsat core
  (Task 6 `solver::project_muc` lifts those to `atom:<doc>:<start>-<end>`
  source-span identifiers in `FormalVerificationTrace::muc`).

## Regenerating

The artifacts here are checked in for human inspection and snapshot diffing.
The authoritative emitter is the Rust solver layer (`cds_kernel::solver`); the
Justfile recipe `rs-solver` exercises it end-to-end and returns the same
proof text inline. To regenerate the snapshot via the bare cvc5 CLI:

```bash
echo '(set-logic QF_LRA)
(declare-fun spo2 () Real)
(assert (! (> spo2 95.0) :named clause_000))
(assert (! (< spo2 90.0) :named clause_001))
(check-sat)' \
  | .bin/cvc5 --lang=smt2 \
              --dump-proofs --proof-format-mode=alethe \
              --simplification=none --dag-thresh=0 \
              --proof-granularity=theory-rewrite \
  > proofs/contradictory-bound.alethe.proof
```
