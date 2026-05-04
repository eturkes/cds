//! Error surface for the ZK kernel (foundation stub at Task 12.1).
//!
//! `NotYetImplemented` is the dominant variant during the Phase 1 ZK
//! axis foundation; it carries the sub-task number that will land the
//! actual implementation (12.2 = witness, 12.3 = prove/verify).

use thiserror::Error;

/// Top-level error type for every public entrypoint of the ZK kernel.
#[derive(Debug, Error)]
pub enum ZkError {
    /// Foundation-stub placeholder — the named sub-task will replace
    /// this branch with the real implementation.
    #[error("not yet implemented (lands at Task 12.{0})")]
    NotYetImplemented(u8),
}
