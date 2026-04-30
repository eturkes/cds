//! Deductive evaluation layer (Phase 0, Task 5).
//!
//! Composes:
//! 1. The **Octagon abstract domain** ([`octagon`]) — relational `±x ±y ≤ c`
//!    constraints over canonical vitals; Phase 0 emits single-variable
//!    bounds and joins point-octagons across the sample stream.
//! 2. An in-process **Datalog rule engine** ([`datalog`]) backed by
//!    `ascent` — fires named clinical conditions and roll-up alarms from
//!    pre-discriminated threshold-breach facts.
//! 3. A locked-in Phase 0 **threshold rule set** ([`rules`]).
//!
//! The public entry point is [`evaluate`], which consumes a
//! [`ClinicalTelemetryPayload`](crate::schema::ClinicalTelemetryPayload)
//! plus a [`Phase0Thresholds`] and returns a [`Verdict`]. The verdict is
//! intentionally an *internal* kernel type for now — the four wire-format
//! schemas (Task 2) are unaffected. Task 6 introduces the SMT-side
//! `FormalVerificationTrace` populated from the verdict.
//!
//! Concurrency: the evaluator is a pure synchronous function. The
//! `Octagon` and ascent-generated `ClinicalDeductionProgram` carry no
//! interior mutability and own all their state — both are `Send + Sync`
//! and trivially safe to consume in async tasks. No subprocesses are
//! spawned (per ADR-013 Phase 0 keeps Datalog evaluation in-process,
//! which honours ADR-004's warden discipline by *not* introducing a new
//! external child).

pub mod datalog;
pub mod octagon;
pub mod rules;

use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};

use crate::canonical::is_canonical_vital;
use crate::schema::ClinicalTelemetryPayload;

pub use datalog::ClinicalDeductionProgram;
pub use octagon::{DomainError, Octagon, VitalInterval};
pub use rules::{Phase0Thresholds, ThresholdBand};

/// Outcome of a deductive sweep over one telemetry payload.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Verdict {
    /// Number of `TelemetrySample` rows consumed.
    pub samples_processed: usize,
    /// Per-vital convex hull recovered from the octagon snapshot.
    pub octagon_bounds: BTreeMap<String, VitalInterval>,
    /// Sorted, deduplicated `monotonic_ns` markers for which *any*
    /// named clinical condition fired.
    pub early_warnings: Vec<u64>,
    /// Sorted, deduplicated `monotonic_ns` markers for which a rule
    /// requiring co-occurring breaches fired.
    pub compound_alarms: Vec<u64>,
    /// Per-condition breach roll-up. Each list is sorted + deduplicated.
    pub breach_summary: BreachSummary,
}

/// Per-clinical-condition breach roll-up.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct BreachSummary {
    pub tachycardia: Vec<u64>,
    pub bradycardia: Vec<u64>,
    pub desaturation: Vec<u64>,
    pub hypotension: Vec<u64>,
    pub hypertension: Vec<u64>,
    pub hyperthermia: Vec<u64>,
    pub hypothermia: Vec<u64>,
    pub tachypnea: Vec<u64>,
    pub bradypnea: Vec<u64>,
}

/// Errors raised by [`evaluate`] when the payload violates a kernel-side
/// invariant. Pure numerical / domain errors propagate as [`DomainError`].
#[derive(Debug, thiserror::Error, PartialEq)]
pub enum DeduceError {
    /// A vital key in the payload is not in the canonical-vital allowlist.
    /// Ingestion (Task 3) is meant to reject these earlier; this is a
    /// defence-in-depth check at the deductive boundary.
    #[error("non-canonical vital in payload: {0}")]
    NonCanonicalVital(String),
    /// The payload carried a non-finite (`NaN` / `±∞`) reading.
    #[error("non-finite reading for vital {name}: {value}")]
    NonFiniteReading { name: String, value: f64 },
    /// Octagon update failed.
    #[error(transparent)]
    Domain(#[from] DomainError),
}

/// Run the Phase 0 deductive engine over `payload`, classifying every
/// reading against `rules` and accumulating a streaming octagon hull.
///
/// # Errors
/// See [`DeduceError`].
pub fn evaluate(
    payload: &ClinicalTelemetryPayload,
    rules: &Phase0Thresholds,
) -> Result<Verdict, DeduceError> {
    let mut prog = ClinicalDeductionProgram::default();
    let mut hull: Option<Octagon> = None;

    for sample in &payload.samples {
        let t = sample.monotonic_ns;
        let mut point = Octagon::top();

        for (name, value) in &sample.vitals {
            if !is_canonical_vital(name) {
                return Err(DeduceError::NonCanonicalVital(name.clone()));
            }
            if !value.is_finite() {
                return Err(DeduceError::NonFiniteReading {
                    name: name.clone(),
                    value: *value,
                });
            }
            point.tighten_point(name, *value)?;

            if let Some(band) = rules.band(name) {
                if band.breaches_low(*value) {
                    push_low_breach(&mut prog, name, t);
                }
                if band.breaches_high(*value) {
                    push_high_breach(&mut prog, name, t);
                }
            }
        }

        hull = Some(match hull {
            None => point,
            Some(prev) => prev.join(&point),
        });
    }

    prog.run();

    Ok(Verdict {
        samples_processed: payload.samples.len(),
        octagon_bounds: hull.map(|o| o.snapshot()).unwrap_or_default(),
        early_warnings: collect_sorted(&prog.early_warning),
        compound_alarms: collect_sorted(&prog.compound_alarm),
        breach_summary: BreachSummary {
            tachycardia: collect_sorted(&prog.tachycardia),
            bradycardia: collect_sorted(&prog.bradycardia),
            desaturation: collect_sorted(&prog.desaturation),
            hypotension: collect_sorted(&prog.hypotension),
            hypertension: collect_sorted(&prog.hypertension),
            hyperthermia: collect_sorted(&prog.hyperthermia),
            hypothermia: collect_sorted(&prog.hypothermia),
            tachypnea: collect_sorted(&prog.tachypnea),
            bradypnea: collect_sorted(&prog.bradypnea),
        },
    })
}

fn push_low_breach(prog: &mut ClinicalDeductionProgram, name: &str, t: u64) {
    match name {
        "heart_rate_bpm" => prog.hr_low_breach.push((t,)),
        "spo2_percent" => prog.spo2_low_breach.push((t,)),
        "systolic_mmhg" => prog.systolic_low_breach.push((t,)),
        "diastolic_mmhg" => prog.diastolic_low_breach.push((t,)),
        "temp_celsius" => prog.temp_low_breach.push((t,)),
        "respiratory_rate_bpm" => prog.rr_low_breach.push((t,)),
        _ => {}
    }
}

fn push_high_breach(prog: &mut ClinicalDeductionProgram, name: &str, t: u64) {
    // SpO2-high is not clinically meaningful in Phase 0 (≥100 % is the
    // ceiling, not a deterioration signal); other non-mapped vitals fall
    // through silently for symmetry with the low-side dispatcher.
    match name {
        "heart_rate_bpm" => prog.hr_high_breach.push((t,)),
        "systolic_mmhg" => prog.systolic_high_breach.push((t,)),
        "diastolic_mmhg" => prog.diastolic_high_breach.push((t,)),
        "temp_celsius" => prog.temp_high_breach.push((t,)),
        "respiratory_rate_bpm" => prog.rr_high_breach.push((t,)),
        _ => {}
    }
}

fn collect_sorted(rel: &[(u64,)]) -> Vec<u64> {
    let mut v: Vec<u64> = rel.iter().map(|t| t.0).collect();
    v.sort_unstable();
    v.dedup();
    v
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;

    use super::{DeduceError, Phase0Thresholds, evaluate};
    use crate::schema::{ClinicalTelemetryPayload, TelemetrySample, TelemetrySource};

    fn make_payload(samples: Vec<TelemetrySample>) -> ClinicalTelemetryPayload {
        ClinicalTelemetryPayload {
            schema_version: crate::schema::SCHEMA_VERSION.to_string(),
            source: TelemetrySource {
                device_id: "test".to_string(),
                patient_pseudo_id: "pseudo".to_string(),
            },
            samples,
        }
    }

    fn vitals(pairs: &[(&str, f64)]) -> BTreeMap<String, f64> {
        pairs.iter().map(|(k, v)| ((*k).to_string(), *v)).collect()
    }

    fn sample(t: u64, vs: &[(&str, f64)]) -> TelemetrySample {
        TelemetrySample {
            wall_clock_utc: "2026-04-29T12:55:00.000000Z".to_string(),
            monotonic_ns: t,
            vitals: vitals(vs),
            events: vec![],
        }
    }

    #[test]
    fn empty_payload_yields_empty_verdict() {
        let p = make_payload(vec![]);
        let v = evaluate(&p, &Phase0Thresholds::default()).unwrap();
        assert_eq!(v.samples_processed, 0);
        assert!(v.octagon_bounds.is_empty());
        assert!(v.early_warnings.is_empty());
        assert!(v.compound_alarms.is_empty());
    }

    #[test]
    fn non_canonical_vital_is_rejected_at_boundary() {
        let p = make_payload(vec![sample(1, &[("glucose_mgdl", 5.5)])]);
        let err = evaluate(&p, &Phase0Thresholds::default()).unwrap_err();
        assert_eq!(err, DeduceError::NonCanonicalVital("glucose_mgdl".into()));
    }

    #[test]
    fn nan_reading_is_rejected_at_boundary() {
        let p = make_payload(vec![sample(1, &[("heart_rate_bpm", f64::NAN)])]);
        match evaluate(&p, &Phase0Thresholds::default()).unwrap_err() {
            DeduceError::NonFiniteReading { name, value } => {
                assert_eq!(name, "heart_rate_bpm");
                assert!(value.is_nan());
            }
            other => panic!("expected NonFiniteReading, got {other:?}"),
        }
    }
}
