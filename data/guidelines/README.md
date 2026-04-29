# Guideline fixtures (Task 4)

Local clinical-guideline samples for the autoformalization translator
(`cds_harness.translate`). Constraint **C1** is honored: all fixtures live
in this directory; no HTTP fetch, no LLM call at translate time.

## File shapes

| Suffix             | Role                                                                                                |
| ------------------ | --------------------------------------------------------------------------------------------------- |
| `<doc>.txt`        | The natural-language guideline. UTF-8, no Markdown rendering required. `doc_id = <doc>` (file stem). |
| `<doc>.recorded.json` | A pre-authored `OnionLIRTree` envelope produced by an offline run of the CLOVER pipeline. The deterministic `RecordedAdapter` returns `tree.root` for `doc_id == <doc>`. |

The directory walker skips any `*.recorded.json` sidecar and any
`README.md`. Only `*.txt` files are translated.

## Source-span contract

Every `Atom.source_span` in a recorded fixture **must** be a valid
byte-offset slice of the matching `<doc>.txt` file, and the span's
`doc_id` **must** equal the file stem. The translator enforces both at
load time; violations raise `InvalidGuidelineError`.

## Phase 0 fixtures

| Stem                  | SMT outcome | Purpose                                                                          |
| --------------------- | ----------- | -------------------------------------------------------------------------------- |
| `hypoxemia-trigger`   | `sat`       | Two non-conflicting bounds on SpO2 (`< 100` and `> 60`). Smoke-tests the gate.    |
| `contradictory-bound` | `unsat`     | Two conflicting bounds on SpO2 (`> 95` and `< 90`). Wires up the MUC path (Task 6). |

## Adding a new fixture

1. Author the source text under `<doc>.txt`. Choose a stem that doubles
   as the canonical `doc_id`.
2. Compute byte offsets for each `Atom.source_span` against the source
   bytes (e.g. `python3 -c "print(open('<doc>.txt','rb').read()[start:end])"`).
3. Hand-author `<doc>.recorded.json` against the OnionL schema.
4. Optional smoke check: `just GUIDELINE_PATH=data/guidelines py-translate`.
5. Update the table above.

Coordinated edits to the canonical-vital namespace, the OP map, or the
SMT lowering contract are ADR-grade — see ADR-012.
