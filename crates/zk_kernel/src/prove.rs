//! ZK proof generation (Task 12.3 lands here).
//!
//! Foundation stub at Task 12.1: the [`ZkProof`] newtype + the
//! [`prove`] entrypoint are declared so the future `Formal_Verification_Trace.zk_attestation`
//! field (ADR-024 §1, Task 12.4) can refer to the canonical proof shape.

use serde::{Deserialize, Serialize};

use crate::errors::ZkError;
use crate::witness::WitnessBlob;

/// Opaque ZK proof artefact emitted by the locked zkVM (Risc0 v3.x).
/// Concrete schema lands at Task 12.3 (per ADR-032 §4); `Vec<u8>` is
/// the placeholder shell.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ZkProof(pub Vec<u8>);

impl ZkProof {
    /// Construct a proof from raw bytes (used by tests + Task 12.3 callers).
    #[must_use]
    pub fn new(bytes: Vec<u8>) -> Self {
        Self(bytes)
    }

    /// Byte length of the underlying proof artefact.
    #[must_use]
    pub fn len(&self) -> usize {
        self.0.len()
    }

    /// Returns `true` when the proof carries no payload bytes.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.0.is_empty()
    }
}

/// Run the locked zkVM over the supplied witness and emit a `ZkProof`.
///
/// Foundation stub: Task 12.3 supplies the actual prove path (Risc0
/// `default_prover().prove(env, ELF) → Receipt → seal bytes`) and
/// replaces this body. Callers should treat the `NotYetImplemented(3)`
/// arm as a discoverable contract surface.
///
/// # Errors
///
/// Always returns [`ZkError::NotYetImplemented`] until Task 12.3 lands.
pub fn prove(_witness: &WitnessBlob) -> Result<ZkProof, ZkError> {
    Err(ZkError::NotYetImplemented(3))
}

#[cfg(test)]
mod tests {
    use super::{ZkProof, prove};
    use crate::errors::ZkError;
    use crate::witness::WitnessBlob;

    #[test]
    fn zk_proof_roundtrips_byte_payload() {
        let proof = ZkProof::new(vec![9, 8, 7]);
        assert_eq!(proof.len(), 3);
        assert!(!proof.is_empty());
    }

    #[test]
    fn empty_zk_proof_reports_empty() {
        let proof = ZkProof::new(vec![]);
        assert!(proof.is_empty());
    }

    #[test]
    fn prove_returns_not_yet_implemented_at_12_3() {
        let witness = WitnessBlob::new(vec![]);
        match prove(&witness) {
            Err(ZkError::NotYetImplemented(3)) => {}
            other => panic!("expected NotYetImplemented(3); got {other:?}"),
        }
    }
}
