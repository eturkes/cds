//! Error surface for the ZK kernel.
//!
//! `NotYetImplemented(<sub-task>)` is the dominant variant for sub-tasks
//! whose impl has not yet landed; it carries the sub-task number that
//! will replace the stub. The witness-specific variants
//! (`WitnessTooLarge`, `TraceFieldOverflow`, `WitnessHeader…`,
//! `WitnessPayload…`) cover the failure modes of the Task 12.2
//! length-prefixed binary encoding declared in [`crate::witness`]. The
//! Risc0-specific variants (`Risc0ProveFailed`, `Risc0VerifyFailed`)
//! cover the prove + verify call-site failures wired up at Task 12.3b1
//! per ADR-035 §3.

use thiserror::Error;

/// Top-level error type for every public entrypoint of the ZK kernel.
#[derive(Debug, Error)]
pub enum ZkError {
    /// Foundation-stub placeholder — the named sub-task will replace
    /// this branch with the real implementation.
    #[error("not yet implemented (lands at Task 12.{0})")]
    NotYetImplemented(u8),

    /// Anything that goes wrong in the [`crate::prove::prove`] path:
    /// `ExecutorEnv` build failure, prover backend failure, receipt
    /// `bincode::serialize` failure. Carries the upstream error string
    /// verbatim so operators can diagnose without re-running.
    #[error("Risc0 prove failed: {0}")]
    Risc0ProveFailed(String),

    /// Anything that goes wrong in the [`crate::verify::verify`] path:
    /// `bincode::deserialize` failure on the proof bytes, image-id
    /// `Digest` conversion failure, or the underlying
    /// `Receipt::verify` rejection. Carries the upstream error string
    /// verbatim so operators can diagnose without re-running.
    #[error("Risc0 verify failed: {0}")]
    Risc0VerifyFailed(String),

    /// One of the [`crate::witness::SmtTrace`] variable-length fields
    /// exceeds its per-field cap (e.g. too many MUC labels, oversized
    /// Alethe text). Surfaces from `extract_witness` *before* any byte
    /// is emitted.
    #[error("SMT-trace field `{field}` has {actual} entries; cap is {limit}")]
    TraceFieldOverflow {
        field: &'static str,
        actual: usize,
        limit: usize,
    },

    /// Encoded witness blob (header + payload) exceeds
    /// [`crate::witness::MAX_WITNESS_BYTES`].
    #[error("witness blob {actual} bytes exceeds cap {limit} bytes")]
    WitnessTooLarge { actual: usize, limit: usize },

    /// Witness blob is shorter than [`crate::witness::WITNESS_HEADER_BYTES`].
    #[error("witness blob too short ({0} bytes); header alone requires 12 bytes")]
    WitnessHeaderTruncated(usize),

    /// Witness blob does not start with the expected
    /// [`crate::witness::WITNESS_MAGIC`] prefix.
    #[error("witness blob lacks expected ZKSM magic prefix")]
    WitnessHeaderMagicMismatch,

    /// Witness blob declares an encoding version this kernel cannot decode.
    #[error("witness blob declares unsupported version {0}")]
    WitnessVersionUnsupported(u8),

    /// Header `payload_len` field disagrees with the actual byte count
    /// after the header.
    #[error("witness blob payload length mismatch: advertised {advertised}; actual {actual}")]
    WitnessPayloadLengthMismatch { advertised: usize, actual: usize },

    /// `serde_json` could not serialise the [`crate::witness::SmtTrace`].
    /// In practice unreachable because `SmtTrace` is plain owned data;
    /// surfaces only on allocator failure or future schema breakage.
    #[error("witness payload JSON encode error: {0}")]
    WitnessPayloadEncode(String),

    /// `serde_json` could not deserialise the post-header bytes back
    /// into an [`crate::witness::SmtTrace`].
    #[error("witness payload JSON decode error: {0}")]
    WitnessPayloadDecode(String),
}
