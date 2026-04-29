# Golden schema fixtures (Task 2)

Canonical JSON instances of the four Phase 0 conceptual schemas. Both the
Rust kernel (`crates/kernel/tests/golden_roundtrip.rs`) and the Python
harness (`python/tests/test_schema_roundtrip.py`) load every file here,
deserialize into their language-native model, re-serialize, and assert that
the result re-deserializes equal to the original — proving the wire format
is bit-stable across Rust ↔ Python.

| File                                | Schema                       |
| ----------------------------------- | ---------------------------- |
| `clinical_telemetry_payload.json`   | `ClinicalTelemetryPayload`   |
| `onionl_ir_tree.json`               | `OnionLIRTree`               |
| `smt_constraint_matrix.json`        | `SmtConstraintMatrix`        |
| `formal_verification_trace.json`    | `FormalVerificationTrace`    |

Edits here are wire-format-breaking by definition: bump `SCHEMA_VERSION`
in both `crates/kernel/src/schema/mod.rs` and
`python/cds_harness/schema/__init__.py` before merging.
