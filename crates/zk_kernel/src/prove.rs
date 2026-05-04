//! ZK proof generation (Task 12.3b1 lands the body fill — ADR-035 §3).
//!
//! [`prove`] runs the locked Risc0 v3.0.1 zkVM over a `(witness,
//! guest_elf)` pair: it builds an `ExecutorEnv` writing the witness
//! bytes into the guest's input frame, hands the env + ELF to the
//! `default_prover()`-selected backend, and `bincode::serialize`s
//! the resulting `Receipt` into the opaque [`ZkProof`] byte payload
//! consumed by [`crate::verify::verify`].
//!
//! The host accepts the guest ELF as a `&[u8]` parameter (NOT via a
//! `risc0-build` build.rs `embed_methods` macro) so the host crate
//! stays compile-clean without `cargo-risczero` installed — the
//! Task 12.3b2 `tests/canonical_roundtrip.rs` integration test loads
//! the ELF bytes from the cross-compiled artifact at smoke time.
//! Mirrors the FHIR-axis "first kernel-side consumer" deferral pattern
//! one more hop (ADR-025 §3 + §8 → ADR-032 §5 → ADR-033 §3 → ADR-034
//! §3 → ADR-035 §3).

use serde::{Deserialize, Serialize};

use crate::errors::ZkError;
use crate::witness::WitnessBlob;

/// Opaque ZK proof artefact emitted by the locked zkVM (Risc0 v3.0.1).
///
/// Wraps a `bincode::serialize`d `risc0_zkvm::Receipt` — the matching
/// [`crate::verify::verify`] entrypoint is the only legitimate
/// consumer (the byte layout is internal to the kernel).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ZkProof(pub Vec<u8>);

impl ZkProof {
    /// Construct a proof from raw bytes (used by tests + kernel callers).
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

/// Run the locked zkVM over the supplied witness and guest ELF, emit a
/// `ZkProof` carrying a `bincode`-serialized `Receipt`.
///
/// The caller supplies the guest ELF bytes; the
/// `tests/canonical_roundtrip.rs` integration test (Task 12.3b2) loads
/// them from the cargo-risczero cross-compiled artefact. Decoupling
/// keeps the host crate compile-clean without cargo-risczero
/// installed.
///
/// `default_prover()` selects the prover backend per the
/// `RISC0_PROVER` env var (`local` for in-process `LocalProver` — the
/// default; `bonsai` for hosted Bonsai; `ipc` for `r0vm` sub-process).
/// For dev/test runs, set `RISC0_DEV_MODE=1` to use the fast fake
/// prover that skips actual STARK generation.
///
/// # Errors
///
/// Returns [`ZkError::Risc0ProveFailed`] for any failure along the
/// prove path: `ExecutorEnv::build`, `Prover::prove`, or
/// `bincode::serialize` on the receipt. The wrapped string carries
/// the upstream error verbatim for operator diagnosis.
pub fn prove(witness: &WitnessBlob, guest_elf: &[u8]) -> Result<ZkProof, ZkError> {
    let env = risc0_zkvm::ExecutorEnv::builder()
        .write(&witness.0)
        .map_err(|e| ZkError::Risc0ProveFailed(format!("ExecutorEnv::write: {e}")))?
        .build()
        .map_err(|e| ZkError::Risc0ProveFailed(format!("ExecutorEnv::build: {e}")))?;

    let prove_info = risc0_zkvm::default_prover()
        .prove(env, guest_elf)
        .map_err(|e| ZkError::Risc0ProveFailed(format!("Prover::prove: {e}")))?;

    let bytes = bincode::serialize(&prove_info.receipt)
        .map_err(|e| ZkError::Risc0ProveFailed(format!("bincode::serialize: {e}")))?;

    Ok(ZkProof(bytes))
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

    /// Compile-time check: [`prove`] takes `(&WitnessBlob, &[u8])`.
    /// Does NOT exercise the heavy Risc0 backend — the canonical
    /// `extract → prove → verify` round-trip lives in
    /// `tests/canonical_roundtrip.rs` (Task 12.3b2 deliverable per
    /// ADR-035 §3 + §6) and is gated on `.bin/.zk/cargo-risczero`.
    #[test]
    fn prove_signature_takes_witness_and_guest_elf() {
        let _: fn(&WitnessBlob, &[u8]) -> Result<ZkProof, ZkError> = prove;
    }
}
