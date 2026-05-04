//! Fixed-size SMT-trace witness extraction (Task 12.2 — ADR-033).
//!
//! [`SmtTrace`] is the host-side input shape: a bounded triple of
//! (theory signature, MUC label set, Alethe proof text). It mirrors the
//! UNSAT outcome of `cds_kernel::FormalVerificationTrace` one-to-one —
//! `theory_signature` ← `SmtConstraintMatrix::theories`, `muc_labels`
//! ← `FormalVerificationTrace::muc`, `alethe_proof` ←
//! `FormalVerificationTrace::alethe_proof` (see
//! `crates/kernel/src/schema/verification.rs`).
//!
//! [`extract_witness`] serialises an `SmtTrace` into a deterministic,
//! length-prefixed byte blob suitable for Risc0 guest-program
//! consumption (`env::read_slice` in the guest, then
//! `serde_json::from_slice` over the post-header bytes).
//! [`parse_witness`] is the host-side inverse — used by tests and by
//! Task 12.3's host-side prove glue when assembling the executor
//! environment.
//!
//! # Wire format (post-quantum-stable, deterministic, no extra deps)
//!
//! ```text
//! +----------+----------+-------------+--------------+--------------------+
//! | magic    | version  | reserved    | payload_len  | json payload       |
//! | 4 bytes  | 1 byte   | 3 bytes (0) | u32 LE       | payload_len bytes  |
//! +----------+----------+-------------+--------------+--------------------+
//!     "ZKSM"      0x01      0x000000   little-endian   serde_json text
//! ```
//!
//! Total blob length = [`WITNESS_HEADER_BYTES`] + `payload_len`, capped
//! at [`MAX_WITNESS_BYTES`] (1 MiB). Per-field caps prevent any single
//! `SmtTrace` field from dominating the budget; see
//! [`MAX_THEORIES`] / [`MAX_MUC_LABELS`] / [`MAX_ALETHE_BYTES`] /
//! [`MAX_LABEL_BYTES`].
//!
//! The encoding does NOT depend on the heavy `risc0-zkvm` crate — that
//! workspace dep is deferred to Task 12.3 when the first kernel-side
//! consumer (prove + verify) lands. ADR-033 §3 re-affirms the
//! "first kernel-side consumer" pattern set by ADR-025 §3 + §8 and
//! ADR-032 §5.

use serde::{Deserialize, Serialize};

use crate::errors::ZkError;

/// Hard cap on the total witness blob byte length (1 MiB).
///
/// Covers the canonical `contradictory-bound` UNSAT trace by >100x; future
/// axes (richer logics, longer Alethe proofs) can lift via a fresh ADR.
pub const MAX_WITNESS_BYTES: usize = 1 << 20;

/// Header byte length: 4 (magic) + 1 (version) + 3 (reserved) + 4 (`payload_len` LE).
pub const WITNESS_HEADER_BYTES: usize = 12;

/// Byte string prefixed to every witness blob ("ZKSM" — ZKSMT magic).
pub const WITNESS_MAGIC: [u8; 4] = *b"ZKSM";

/// Wire-format version. Bumped on any breaking change to the encoding.
pub const WITNESS_VERSION: u8 = 1;

/// Maximum number of distinct SMT-LIB theories carried by a single trace.
pub const MAX_THEORIES: usize = 32;

/// Maximum number of MUC labels carried by a single trace.
pub const MAX_MUC_LABELS: usize = 1024;

/// Maximum byte length of the embedded Alethe proof text (768 KiB —
/// 75% of [`MAX_WITNESS_BYTES`], leaves room for header + theories + MUC).
pub const MAX_ALETHE_BYTES: usize = 768 * 1024;

/// Maximum byte length of any single theory or MUC label string.
pub const MAX_LABEL_BYTES: usize = 256;

/// Host-side input shape for witness extraction.
///
/// Mirrors the UNSAT outcome of `FormalVerificationTrace`:
///
/// - `theory_signature`: SMT-LIB theory family identifiers actively in
///   use (e.g. `["LRA"]` for the canonical `contradictory-bound` smoke).
/// - `muc_labels`: Minimal Unsatisfiable Core — ordered list of
///   labelled-assertion identifiers, each tracing back to an `OnionL`
///   atom `source_span` (constraint C4 in `Plan.md` §5).
/// - `alethe_proof`: cvc5-emitted Alethe S-expression text. May be
///   empty for degenerate test traces; production traces always carry
///   the cvc5 proof text.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SmtTrace {
    pub theory_signature: Vec<String>,
    pub muc_labels: Vec<String>,
    pub alethe_proof: String,
}

impl SmtTrace {
    /// Construct a trace from its three components.
    #[must_use]
    pub fn new(
        theory_signature: Vec<String>,
        muc_labels: Vec<String>,
        alethe_proof: String,
    ) -> Self {
        Self {
            theory_signature,
            muc_labels,
            alethe_proof,
        }
    }

    /// Validate per-field caps before encoding. Returns the offending
    /// field on the first violation (deterministic ordering: theories
    /// → `muc_labels` → `alethe_proof` → per-label length).
    fn validate_caps(&self) -> Result<(), ZkError> {
        if self.theory_signature.len() > MAX_THEORIES {
            return Err(ZkError::TraceFieldOverflow {
                field: "theory_signature",
                actual: self.theory_signature.len(),
                limit: MAX_THEORIES,
            });
        }
        if self.muc_labels.len() > MAX_MUC_LABELS {
            return Err(ZkError::TraceFieldOverflow {
                field: "muc_labels",
                actual: self.muc_labels.len(),
                limit: MAX_MUC_LABELS,
            });
        }
        if self.alethe_proof.len() > MAX_ALETHE_BYTES {
            return Err(ZkError::TraceFieldOverflow {
                field: "alethe_proof",
                actual: self.alethe_proof.len(),
                limit: MAX_ALETHE_BYTES,
            });
        }
        for label in &self.theory_signature {
            if label.len() > MAX_LABEL_BYTES {
                return Err(ZkError::TraceFieldOverflow {
                    field: "theory_signature[label]",
                    actual: label.len(),
                    limit: MAX_LABEL_BYTES,
                });
            }
        }
        for label in &self.muc_labels {
            if label.len() > MAX_LABEL_BYTES {
                return Err(ZkError::TraceFieldOverflow {
                    field: "muc_labels[label]",
                    actual: label.len(),
                    limit: MAX_LABEL_BYTES,
                });
            }
        }
        Ok(())
    }
}

/// Opaque, length-prefixed byte blob carrying a serialized [`SmtTrace`]
/// suitable for Risc0 guest-program input.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct WitnessBlob(pub Vec<u8>);

impl WitnessBlob {
    /// Wrap raw bytes in a witness blob (used by tests + Task 12.3 callers).
    #[must_use]
    pub fn new(bytes: Vec<u8>) -> Self {
        Self(bytes)
    }

    /// Total byte length (header + payload).
    #[must_use]
    pub fn len(&self) -> usize {
        self.0.len()
    }

    /// Returns `true` when the blob carries no bytes at all.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.0.is_empty()
    }

    /// Returns the payload byte count advertised by the header (does NOT
    /// validate magic / version — use [`parse_witness`] for full
    /// validation).
    ///
    /// # Errors
    ///
    /// Returns [`ZkError::WitnessHeaderTruncated`] if the blob is shorter
    /// than [`WITNESS_HEADER_BYTES`].
    ///
    /// # Panics
    ///
    /// Unreachable in practice: the post-header `try_into` to a `[u8; 4]`
    /// is statically guaranteed to succeed (the slice indices `8..12`
    /// cover exactly four bytes), and the `u32` → `usize` widening
    /// holds on every supported target (32-bit and above).
    pub fn advertised_payload_len(&self) -> Result<usize, ZkError> {
        if self.0.len() < WITNESS_HEADER_BYTES {
            return Err(ZkError::WitnessHeaderTruncated(self.0.len()));
        }
        let raw: [u8; 4] = self.0[8..12]
            .try_into()
            .expect("slice covers exactly bytes 8..12 by construction");
        Ok(usize::try_from(u32::from_le_bytes(raw))
            .expect("u32 fits in usize on every supported target (32-bit and above)"))
    }
}

/// Serialise an [`SmtTrace`] into a fixed-size-bounded witness blob.
///
/// The encoding is deterministic — calling `extract_witness` twice on
/// the same input yields identical bytes — and is independent of the
/// heavy `risc0-zkvm` crate (Task 12.3 brings that dep in alongside
/// the actual proving call site).
///
/// # Errors
///
/// - [`ZkError::TraceFieldOverflow`] if any field exceeds its per-field cap.
/// - [`ZkError::WitnessTooLarge`] if the encoded payload + header exceeds
///   [`MAX_WITNESS_BYTES`].
/// - [`ZkError::WitnessPayloadEncode`] if `serde_json` cannot serialise
///   the trace (allocator failure or future schema breakage).
///
/// # Panics
///
/// Unreachable in practice: the `u32` length conversion is gated by an
/// explicit total-size check against [`MAX_WITNESS_BYTES`] (which is
/// well under `u32::MAX`).
pub fn extract_witness(trace: &SmtTrace) -> Result<WitnessBlob, ZkError> {
    trace.validate_caps()?;

    let payload =
        serde_json::to_vec(trace).map_err(|e| ZkError::WitnessPayloadEncode(e.to_string()))?;

    let total = WITNESS_HEADER_BYTES.saturating_add(payload.len());
    if total > MAX_WITNESS_BYTES {
        return Err(ZkError::WitnessTooLarge {
            actual: total,
            limit: MAX_WITNESS_BYTES,
        });
    }

    let payload_len = u32::try_from(payload.len())
        .expect("payload bounded by MAX_WITNESS_BYTES (< u32::MAX) by the size check above");

    let mut bytes = Vec::with_capacity(total);
    bytes.extend_from_slice(&WITNESS_MAGIC);
    bytes.push(WITNESS_VERSION);
    bytes.extend_from_slice(&[0u8; 3]);
    bytes.extend_from_slice(&payload_len.to_le_bytes());
    bytes.extend_from_slice(&payload);
    Ok(WitnessBlob(bytes))
}

/// Parse a witness blob back into an [`SmtTrace`].
///
/// Used by host-side round-trip tests and by Task 12.3's host glue
/// when assembling the Risc0 executor environment.
///
/// # Errors
///
/// - [`ZkError::WitnessHeaderTruncated`] if the blob is shorter than
///   the 12-byte header.
/// - [`ZkError::WitnessHeaderMagicMismatch`] if the first 4 bytes are
///   not [`WITNESS_MAGIC`].
/// - [`ZkError::WitnessVersionUnsupported`] if the version byte is not
///   [`WITNESS_VERSION`].
/// - [`ZkError::WitnessPayloadLengthMismatch`] if the header
///   `payload_len` disagrees with the actual post-header byte count.
/// - [`ZkError::WitnessPayloadDecode`] if the JSON payload cannot be
///   deserialised back into an `SmtTrace`.
///
/// # Panics
///
/// Unreachable in practice: the post-header `try_into` to a `[u8; 4]`
/// is statically guaranteed to succeed (header truncation is rejected
/// up front), and the `u32` → `usize` widening holds on every
/// supported target.
pub fn parse_witness(blob: &WitnessBlob) -> Result<SmtTrace, ZkError> {
    if blob.0.len() < WITNESS_HEADER_BYTES {
        return Err(ZkError::WitnessHeaderTruncated(blob.0.len()));
    }
    if blob.0[..4] != WITNESS_MAGIC {
        return Err(ZkError::WitnessHeaderMagicMismatch);
    }
    if blob.0[4] != WITNESS_VERSION {
        return Err(ZkError::WitnessVersionUnsupported(blob.0[4]));
    }
    let raw: [u8; 4] = blob.0[8..12]
        .try_into()
        .expect("slice covers exactly bytes 8..12 by construction");
    let advertised = usize::try_from(u32::from_le_bytes(raw))
        .expect("u32 fits in usize on every supported target (32-bit and above)");
    let actual = blob.0.len() - WITNESS_HEADER_BYTES;
    if advertised != actual {
        return Err(ZkError::WitnessPayloadLengthMismatch { advertised, actual });
    }
    serde_json::from_slice::<SmtTrace>(&blob.0[WITNESS_HEADER_BYTES..])
        .map_err(|e| ZkError::WitnessPayloadDecode(e.to_string()))
}

#[cfg(test)]
mod tests {
    use super::{
        MAX_ALETHE_BYTES, MAX_LABEL_BYTES, MAX_MUC_LABELS, MAX_THEORIES, MAX_WITNESS_BYTES,
        SmtTrace, WITNESS_HEADER_BYTES, WITNESS_MAGIC, WITNESS_VERSION, WitnessBlob,
        extract_witness, parse_witness,
    };
    use crate::errors::ZkError;

    /// The actual cvc5-emitted Alethe proof text from the canonical
    /// `contradictory-bound` UNSAT smoke (Phase 0 close-out fixture).
    const CANONICAL_ALETHE: &str = include_str!("../../../proofs/contradictory-bound.alethe.proof");

    fn canonical_trace() -> SmtTrace {
        SmtTrace::new(
            vec!["LRA".to_string()],
            vec!["clause_000".to_string(), "clause_001".to_string()],
            CANONICAL_ALETHE.to_string(),
        )
    }

    fn empty_trace() -> SmtTrace {
        SmtTrace::new(vec![], vec![], String::new())
    }

    // -------------------------------------------------------------------------
    // Constants + WitnessBlob helpers
    // -------------------------------------------------------------------------

    #[test]
    fn witness_header_is_12_bytes() {
        assert_eq!(WITNESS_HEADER_BYTES, 12);
    }

    #[test]
    fn witness_magic_is_zksm() {
        assert_eq!(&WITNESS_MAGIC, b"ZKSM");
    }

    #[test]
    fn witness_version_starts_at_one() {
        assert_eq!(WITNESS_VERSION, 1);
    }

    #[test]
    fn max_witness_bytes_is_one_mib() {
        assert_eq!(MAX_WITNESS_BYTES, 1_048_576);
    }

    const _: () = assert!(
        MAX_ALETHE_BYTES < MAX_WITNESS_BYTES,
        "alethe cap must fit inside total cap with header + theory/MUC budget"
    );

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

    // -------------------------------------------------------------------------
    // extract_witness — happy paths
    // -------------------------------------------------------------------------

    #[test]
    fn extract_witness_round_trips_canonical_smt_trace() {
        let trace = canonical_trace();
        let blob = extract_witness(&trace).expect("extract canonical");
        let recovered = parse_witness(&blob).expect("parse canonical");
        assert_eq!(recovered, trace);
    }

    #[test]
    fn extract_witness_round_trips_empty_trace() {
        let trace = empty_trace();
        let blob = extract_witness(&trace).expect("extract empty");
        let recovered = parse_witness(&blob).expect("parse empty");
        assert_eq!(recovered, trace);
    }

    #[test]
    fn extract_witness_emits_zksm_magic() {
        let blob = extract_witness(&canonical_trace()).expect("extract canonical");
        assert_eq!(&blob.0[..4], &WITNESS_MAGIC);
    }

    #[test]
    fn extract_witness_emits_locked_version() {
        let blob = extract_witness(&canonical_trace()).expect("extract canonical");
        assert_eq!(blob.0[4], WITNESS_VERSION);
    }

    #[test]
    fn extract_witness_zeroes_reserved_bytes() {
        let blob = extract_witness(&canonical_trace()).expect("extract canonical");
        assert_eq!(&blob.0[5..8], &[0u8; 3], "reserved bytes must be zero");
    }

    #[test]
    fn extract_witness_records_payload_len_in_header() {
        let blob = extract_witness(&canonical_trace()).expect("extract canonical");
        let advertised = blob.advertised_payload_len().expect("header present");
        assert_eq!(advertised, blob.0.len() - WITNESS_HEADER_BYTES);
    }

    #[test]
    fn extract_witness_canonical_fits_under_total_cap() {
        let blob = extract_witness(&canonical_trace()).expect("extract canonical");
        assert!(
            blob.len() <= MAX_WITNESS_BYTES,
            "canonical blob {} bytes must fit MAX_WITNESS_BYTES={}",
            blob.len(),
            MAX_WITNESS_BYTES
        );
    }

    #[test]
    fn extract_witness_is_deterministic() {
        let trace = canonical_trace();
        let a = extract_witness(&trace).expect("extract a");
        let b = extract_witness(&trace).expect("extract b");
        assert_eq!(
            a.0, b.0,
            "encoding must be deterministic for stable proving"
        );
    }

    // -------------------------------------------------------------------------
    // extract_witness — per-field caps
    // -------------------------------------------------------------------------

    #[test]
    fn extract_witness_rejects_too_many_theories() {
        let theories: Vec<String> = (0..=MAX_THEORIES).map(|i| format!("T{i}")).collect();
        let trace = SmtTrace::new(theories, vec![], String::new());
        match extract_witness(&trace) {
            Err(ZkError::TraceFieldOverflow {
                field,
                actual,
                limit,
            }) => {
                assert_eq!(field, "theory_signature");
                assert_eq!(actual, MAX_THEORIES + 1);
                assert_eq!(limit, MAX_THEORIES);
            }
            other => panic!("expected TraceFieldOverflow(theory_signature); got {other:?}"),
        }
    }

    #[test]
    fn extract_witness_rejects_too_many_muc_labels() {
        let mucs: Vec<String> = (0..=MAX_MUC_LABELS).map(|i| format!("L{i}")).collect();
        let trace = SmtTrace::new(vec![], mucs, String::new());
        match extract_witness(&trace) {
            Err(ZkError::TraceFieldOverflow {
                field,
                actual,
                limit,
            }) => {
                assert_eq!(field, "muc_labels");
                assert_eq!(actual, MAX_MUC_LABELS + 1);
                assert_eq!(limit, MAX_MUC_LABELS);
            }
            other => panic!("expected TraceFieldOverflow(muc_labels); got {other:?}"),
        }
    }

    #[test]
    fn extract_witness_rejects_oversized_alethe_text() {
        let alethe = "x".repeat(MAX_ALETHE_BYTES + 1);
        let trace = SmtTrace::new(vec![], vec![], alethe);
        match extract_witness(&trace) {
            Err(ZkError::TraceFieldOverflow {
                field,
                actual,
                limit,
            }) => {
                assert_eq!(field, "alethe_proof");
                assert_eq!(actual, MAX_ALETHE_BYTES + 1);
                assert_eq!(limit, MAX_ALETHE_BYTES);
            }
            other => panic!("expected TraceFieldOverflow(alethe_proof); got {other:?}"),
        }
    }

    #[test]
    fn extract_witness_rejects_oversized_theory_label() {
        let trace = SmtTrace::new(vec!["x".repeat(MAX_LABEL_BYTES + 1)], vec![], String::new());
        match extract_witness(&trace) {
            Err(ZkError::TraceFieldOverflow {
                field,
                actual,
                limit,
            }) => {
                assert_eq!(field, "theory_signature[label]");
                assert_eq!(actual, MAX_LABEL_BYTES + 1);
                assert_eq!(limit, MAX_LABEL_BYTES);
            }
            other => panic!("expected TraceFieldOverflow(theory_signature[label]); got {other:?}"),
        }
    }

    #[test]
    fn extract_witness_rejects_oversized_muc_label() {
        let trace = SmtTrace::new(vec![], vec!["x".repeat(MAX_LABEL_BYTES + 1)], String::new());
        match extract_witness(&trace) {
            Err(ZkError::TraceFieldOverflow {
                field,
                actual,
                limit,
            }) => {
                assert_eq!(field, "muc_labels[label]");
                assert_eq!(actual, MAX_LABEL_BYTES + 1);
                assert_eq!(limit, MAX_LABEL_BYTES);
            }
            other => panic!("expected TraceFieldOverflow(muc_labels[label]); got {other:?}"),
        }
    }

    // -------------------------------------------------------------------------
    // parse_witness — failure modes
    // -------------------------------------------------------------------------

    #[test]
    fn parse_witness_rejects_truncated_blob() {
        let blob = WitnessBlob::new(vec![b'Z', b'K', b'S']);
        match parse_witness(&blob) {
            Err(ZkError::WitnessHeaderTruncated(3)) => {}
            other => panic!("expected WitnessHeaderTruncated(3); got {other:?}"),
        }
    }

    #[test]
    fn parse_witness_rejects_bad_magic() {
        let mut bytes = extract_witness(&canonical_trace()).expect("extract").0;
        bytes[0] = b'X';
        match parse_witness(&WitnessBlob::new(bytes)) {
            Err(ZkError::WitnessHeaderMagicMismatch) => {}
            other => panic!("expected WitnessHeaderMagicMismatch; got {other:?}"),
        }
    }

    #[test]
    fn parse_witness_rejects_unsupported_version() {
        let mut bytes = extract_witness(&canonical_trace()).expect("extract").0;
        bytes[4] = 0xFE;
        match parse_witness(&WitnessBlob::new(bytes)) {
            Err(ZkError::WitnessVersionUnsupported(0xFE)) => {}
            other => panic!("expected WitnessVersionUnsupported(0xFE); got {other:?}"),
        }
    }

    #[test]
    fn parse_witness_rejects_payload_length_mismatch() {
        let mut bytes = extract_witness(&canonical_trace()).expect("extract").0;
        // truncate one byte without updating the header
        bytes.pop();
        let advertised_before_truncation = {
            let raw: [u8; 4] = bytes[8..12]
                .try_into()
                .expect("slice covers exactly bytes 8..12 by construction");
            usize::try_from(u32::from_le_bytes(raw)).expect("fits")
        };
        match parse_witness(&WitnessBlob::new(bytes)) {
            Err(ZkError::WitnessPayloadLengthMismatch { advertised, actual }) => {
                assert_eq!(advertised, advertised_before_truncation);
                assert_eq!(actual, advertised_before_truncation - 1);
            }
            other => panic!("expected WitnessPayloadLengthMismatch; got {other:?}"),
        }
    }

    #[test]
    fn parse_witness_rejects_corrupted_json_payload() {
        let mut bytes = extract_witness(&canonical_trace()).expect("extract").0;
        let header_len = WITNESS_HEADER_BYTES;
        // Replace the JSON payload with garbage of identical length so the
        // length-prefix check passes and we hit the JSON decoder.
        for byte in &mut bytes[header_len..] {
            *byte = 0xFF;
        }
        match parse_witness(&WitnessBlob::new(bytes)) {
            Err(ZkError::WitnessPayloadDecode(_)) => {}
            other => panic!("expected WitnessPayloadDecode; got {other:?}"),
        }
    }

    #[test]
    fn advertised_payload_len_errors_on_short_blob() {
        let blob = WitnessBlob::new(vec![0u8; 3]);
        match blob.advertised_payload_len() {
            Err(ZkError::WitnessHeaderTruncated(3)) => {}
            other => panic!("expected WitnessHeaderTruncated(3); got {other:?}"),
        }
    }
}
