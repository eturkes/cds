//! Fixed-size SMT-trace witness extraction (Task 12.2 lands here).
//!
//! Foundation stub at Task 12.1: the [`WitnessBlob`] newtype + the
//! [`extract_witness`] entrypoint are declared so downstream callers
//! (kernel `solver` module, future ZK pipeline) can refer to the API
//! shape without waiting for the Risc0 wire-up.

use serde::{Deserialize, Serialize};

use crate::errors::ZkError;

/// Opaque, fixed-size byte blob carrying a serialized SMT verification
/// trace suitable for Risc0 guest-program input. Concrete schema lands
/// at Task 12.2 (per ADR-032 §4); `Vec<u8>` is the placeholder shell.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct WitnessBlob(pub Vec<u8>);

impl WitnessBlob {
    /// Construct a witness from raw bytes (used by tests + Task 12.2 callers).
    #[must_use]
    pub fn new(bytes: Vec<u8>) -> Self {
        Self(bytes)
    }

    /// Byte length of the underlying blob.
    #[must_use]
    pub fn len(&self) -> usize {
        self.0.len()
    }

    /// Returns `true` when the blob carries no payload bytes.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.0.is_empty()
    }
}

/// Extract a fixed-size witness blob from an SMT verification trace.
///
/// Foundation stub: Task 12.2 supplies the actual serialization (likely
/// a length-prefixed Alethe step stream + MUC label set + theory
/// signature) and replaces this body. Callers should treat the
/// `NotYetImplemented(2)` arm as a discoverable contract surface, not
/// an operational failure mode.
///
/// # Errors
///
/// Always returns [`ZkError::NotYetImplemented`] until Task 12.2 lands.
pub fn extract_witness() -> Result<WitnessBlob, ZkError> {
    Err(ZkError::NotYetImplemented(2))
}

#[cfg(test)]
mod tests {
    use super::{WitnessBlob, extract_witness};
    use crate::errors::ZkError;

    #[test]
    fn witness_blob_roundtrips_byte_payload() {
        let blob = WitnessBlob::new(vec![1, 2, 3, 4]);
        assert_eq!(blob.len(), 4);
        assert!(!blob.is_empty());
    }

    #[test]
    fn empty_witness_blob_reports_empty() {
        let blob = WitnessBlob::new(vec![]);
        assert!(blob.is_empty());
    }

    #[test]
    fn extract_witness_returns_not_yet_implemented_at_12_2() {
        match extract_witness() {
            Err(ZkError::NotYetImplemented(2)) => {}
            other => panic!("expected NotYetImplemented(2); got {other:?}"),
        }
    }
}
