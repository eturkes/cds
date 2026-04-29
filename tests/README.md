# Cross-cutting Integration Tests

This directory holds **end-to-end** integration tests that exercise multiple
ecosystems together (Python harness ↔ Rust kernel ↔ external solver binaries).

Per-language unit tests live next to their source:

- Rust: `crates/<crate>/src/**/*.rs` (`#[cfg(test)] mod tests`) and `crates/<crate>/tests/`
- Python: `python/tests/`
- Frontend: `frontend/src/**/*.test.ts` (added in Task 9)

The substantive integration suite — keyed to the four conceptual schemas
(`ClinicalTelemetryPayload`, `OnionL_IR_Tree`, `SMT_Constraint_Matrix`,
`Formal_Verification_Trace`) — lands in **Task 2** when those schemas are
defined.
