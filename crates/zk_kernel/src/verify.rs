//! ZK proof verification (Task 12.3b1 lands the body fill — ADR-035 §3).
//!
//! [`verify`] `bincode::deserialize`s the [`crate::prove::ZkProof`]
//! payload into a `risc0_zkvm::Receipt`, then dispatches to
//! `Receipt::verify(image_id)`. The caller supplies the `image_id`
//! (computed via [`image_id_from_elf`] over the same ELF the prover
//! consumed) so the verifier remains compile-clean without the
//! `cargo-risczero` cross-compiler installed.

use crate::errors::ZkError;
use crate::prove::ZkProof;

/// Verify a `ZkProof` against the supplied `image_id`.
///
/// `image_id` is the 8-word `Digest` of the guest ELF — typically
/// obtained via [`image_id_from_elf`] over the same ELF bytes passed
/// to [`crate::prove::prove`]. The `[u32; 8]` shape is `Digest`'s
/// underlying word array (see `risc0_zkvm::Digest::AsRef<[u32]>`)
/// and converts losslessly via `Digest::from(...)`.
///
/// Returns `Ok(())` on a valid proof, [`ZkError::Risc0VerifyFailed`]
/// on any failure (`bincode::deserialize` failure on the proof bytes,
/// the underlying `Receipt::verify` rejection, etc.).
///
/// # Errors
///
/// Returns [`ZkError::Risc0VerifyFailed`] on any failure along the
/// verify path. The wrapped string carries the upstream error
/// verbatim for operator diagnosis.
pub fn verify(proof: &ZkProof, image_id: [u32; 8]) -> Result<(), ZkError> {
    let receipt: risc0_zkvm::Receipt = bincode::deserialize(&proof.0)
        .map_err(|e| ZkError::Risc0VerifyFailed(format!("bincode::deserialize: {e}")))?;

    receipt
        .verify(image_id)
        .map_err(|e| ZkError::Risc0VerifyFailed(format!("Receipt::verify: {e}")))
}

/// Compute the Risc0 `image_id` of a guest ELF as an 8-word array.
///
/// Thin wrapper around `risc0_zkvm::compute_image_id` that surfaces
/// the same `[u32; 8]` shape consumed by [`verify`]. Used by the
/// Task 12.3b2 `tests/canonical_roundtrip.rs` integration test to
/// derive the verifier's `image_id` argument from the same ELF the
/// prover ran against.
///
/// # Errors
///
/// Returns [`ZkError::Risc0VerifyFailed`] if Risc0 cannot decode the
/// ELF (malformed binary, wrong target, etc.).
pub fn image_id_from_elf(guest_elf: &[u8]) -> Result<[u32; 8], ZkError> {
    let digest = risc0_zkvm::compute_image_id(guest_elf)
        .map_err(|e| ZkError::Risc0VerifyFailed(format!("compute_image_id: {e}")))?;
    let words = digest.as_words();
    if words.len() != 8 {
        return Err(ZkError::Risc0VerifyFailed(format!(
            "image_id Digest must expose exactly 8 u32 words; got {}",
            words.len()
        )));
    }
    let mut out = [0u32; 8];
    out.copy_from_slice(words);
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::{image_id_from_elf, verify};
    use crate::errors::ZkError;
    use crate::prove::ZkProof;

    /// Compile-time check: [`verify`] takes `(&ZkProof, [u32; 8])`.
    /// Does NOT exercise the heavy Risc0 backend — the canonical
    /// `extract → prove → verify` round-trip lives in
    /// `tests/canonical_roundtrip.rs` (Task 12.3b2 deliverable per
    /// ADR-035 §3 + §6) and is gated on `.bin/.zk/cargo-risczero`.
    #[test]
    fn verify_signature_takes_proof_and_image_id() {
        let _: fn(&ZkProof, [u32; 8]) -> Result<(), ZkError> = verify;
    }

    #[test]
    fn image_id_from_elf_signature_takes_byte_slice() {
        let _: fn(&[u8]) -> Result<[u32; 8], ZkError> = image_id_from_elf;
    }

    #[test]
    fn verify_rejects_garbage_proof_bytes() {
        // bincode::deserialize over arbitrary garbage MUST fail —
        // exercises the early-return path without invoking the
        // Risc0 verifier (which would need a real receipt).
        let proof = ZkProof::new(vec![0xFFu8; 8]);
        match verify(&proof, [0u32; 8]) {
            Err(ZkError::Risc0VerifyFailed(msg)) => {
                assert!(
                    msg.contains("bincode::deserialize"),
                    "garbage bytes must fail at bincode decode; got: {msg}"
                );
            }
            other => panic!("expected Risc0VerifyFailed(bincode...); got {other:?}"),
        }
    }
}
