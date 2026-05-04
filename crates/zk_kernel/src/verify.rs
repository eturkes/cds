//! ZK proof verification (Task 12.3 lands here).
//!
//! Foundation stub at Task 12.1: the [`verify`] entrypoint is declared
//! so the future kernel-side close-out smoke (Task 12.4) can refer to
//! the verifier API shape.

use crate::errors::ZkError;
use crate::prove::ZkProof;

/// Verify a `ZkProof` against the locked zkVM image.
///
/// Foundation stub: Task 12.3 supplies the actual verify path (Risc0
/// `Receipt::verify(image_id)` returning `Ok(())` on success) and
/// replaces this body. Callers should treat the `NotYetImplemented(3)`
/// arm as a discoverable contract surface.
///
/// # Errors
///
/// Always returns [`ZkError::NotYetImplemented`] until Task 12.3 lands.
pub fn verify(_proof: &ZkProof) -> Result<(), ZkError> {
    Err(ZkError::NotYetImplemented(3))
}

#[cfg(test)]
mod tests {
    use super::verify;
    use crate::errors::ZkError;
    use crate::prove::ZkProof;

    #[test]
    fn verify_returns_not_yet_implemented_at_12_3() {
        let proof = ZkProof::new(vec![]);
        match verify(&proof) {
            Err(ZkError::NotYetImplemented(3)) => {}
            other => panic!("expected NotYetImplemented(3); got {other:?}"),
        }
    }
}
