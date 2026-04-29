//! Conceptual schemas (Phase 0, Task 2).
//!
//! Defines the four canonical wire-format types that flow between the Rust
//! deductive kernel, the Python neurosymbolic harness, and downstream solver
//! / proof subprocesses. Every type derives `serde::{Serialize, Deserialize}`
//! and is round-trip-stable through JSON. The on-the-wire JSON shape is
//! mirrored bit-for-bit by the Python (Pydantic v2) models in
//! `python/cds_harness/schema/`.
//!
//! Cross-language invariants (do **not** loosen without bumping the schema
//! version on every affected type):
//!
//! - All variant tags use the `snake_case` `kind` field for internally-tagged
//!   discriminated unions (Serde `tag = "kind"`, Pydantic `discriminator="kind"`).
//! - Floating-point values use IEEE-754 binary64 (Rust `f64`, Python `float`).
//! - Wall-clock timestamps are RFC 3339 / ISO-8601 UTC strings (`...Z`).
//! - Monotonic clock values are unsigned 64-bit nanoseconds (`u64`).
//! - Map types serialize with deterministic key ordering (`BTreeMap`) so two
//!   serializations of structurally-equal data are byte-identical.
//!
//! See `Plan.md §4` and `Memory_Scratchpad.md` for the Task 2 spec.

pub mod onionl;
pub mod smt;
pub mod telemetry;
pub mod verification;

pub use onionl::{OnionLIRTree, OnionLNode, SourceSpan, Term};
pub use smt::{LabelledAssertion, SmtConstraintMatrix};
pub use telemetry::{ClinicalTelemetryPayload, DiscreteEvent, TelemetrySample, TelemetrySource};
pub use verification::FormalVerificationTrace;

/// Schema-set version. Bumped only when a wire-format-breaking change lands.
/// Mirrored verbatim by `cds_harness.schema.SCHEMA_VERSION`.
pub const SCHEMA_VERSION: &str = "0.1.0";
