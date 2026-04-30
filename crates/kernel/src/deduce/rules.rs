//! Phase 0 threshold-rule fixtures.
//!
//! Each canonical vital is paired with a `[low, high]` band; a sample's
//! reading triggers a threshold breach when it falls *strictly* outside
//! the band. The defaults below are clinically-motivated illustrations
//! suitable for Phase 0 *research-prototype* exercises (Plan §2: "does
//! not diagnose / decide care; produces proof certificates over
//! formalized guideline fragments"). They are **not** an authoritative
//! clinical rule set.
//!
//! Treat the band layout as an internal-engine concern: the wire-facing
//! contract for guideline encoding is `OnionLIRTree → SmtConstraintMatrix`
//! (Tasks 4+6). This module exists so the deductive engine has a
//! concrete, testable rule set today, and so a future "rule loader" can
//! materialize bands from a structured fixture.

use serde::{Deserialize, Serialize};

/// A `[low, high]` threshold band. A reading `v` *strictly below* `low`
/// or *strictly above* `high` triggers a breach. Equality on either
/// boundary is intentionally treated as in-band — the SMT side enforces
/// non-strict inequalities and we mirror that here.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct ThresholdBand {
    pub low: f64,
    pub high: f64,
}

impl ThresholdBand {
    /// Returns `true` iff `value < low` (i.e. low-side breach).
    #[must_use]
    pub fn breaches_low(self, value: f64) -> bool {
        value < self.low
    }

    /// Returns `true` iff `value > high` (i.e. high-side breach).
    #[must_use]
    pub fn breaches_high(self, value: f64) -> bool {
        value > self.high
    }
}

/// Phase 0 rule set — one band per canonical vital.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Phase0Thresholds {
    pub heart_rate_bpm: ThresholdBand,
    pub spo2_percent: ThresholdBand,
    pub systolic_mmhg: ThresholdBand,
    pub diastolic_mmhg: ThresholdBand,
    pub temp_celsius: ThresholdBand,
    pub respiratory_rate_bpm: ThresholdBand,
}

impl Phase0Thresholds {
    /// Look up the band associated with a canonical vital name.
    #[must_use]
    pub fn band(&self, name: &str) -> Option<ThresholdBand> {
        match name {
            "heart_rate_bpm" => Some(self.heart_rate_bpm),
            "spo2_percent" => Some(self.spo2_percent),
            "systolic_mmhg" => Some(self.systolic_mmhg),
            "diastolic_mmhg" => Some(self.diastolic_mmhg),
            "temp_celsius" => Some(self.temp_celsius),
            "respiratory_rate_bpm" => Some(self.respiratory_rate_bpm),
            _ => None,
        }
    }
}

impl Default for Phase0Thresholds {
    fn default() -> Self {
        Self {
            heart_rate_bpm: ThresholdBand {
                low: 50.0,
                high: 120.0,
            },
            spo2_percent: ThresholdBand {
                low: 92.0,
                high: 100.0,
            },
            systolic_mmhg: ThresholdBand {
                low: 90.0,
                high: 160.0,
            },
            diastolic_mmhg: ThresholdBand {
                low: 60.0,
                high: 100.0,
            },
            temp_celsius: ThresholdBand {
                low: 35.0,
                high: 38.5,
            },
            respiratory_rate_bpm: ThresholdBand {
                low: 12.0,
                high: 24.0,
            },
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{Phase0Thresholds, ThresholdBand};

    #[test]
    fn breach_predicates_are_strict() {
        let band = ThresholdBand {
            low: 92.0,
            high: 100.0,
        };
        assert!(band.breaches_low(91.999));
        assert!(!band.breaches_low(92.0));
        assert!(!band.breaches_high(100.0));
        assert!(band.breaches_high(100.001));
    }

    #[test]
    fn default_thresholds_cover_every_canonical_vital() {
        let t = Phase0Thresholds::default();
        for name in crate::canonical::CANONICAL_VITALS {
            assert!(t.band(name).is_some(), "missing band for {name}");
        }
    }

    #[test]
    fn unknown_vital_has_no_band() {
        assert!(Phase0Thresholds::default().band("glucose_mgdl").is_none());
    }

    #[test]
    fn round_trips_json() {
        let t = Phase0Thresholds::default();
        let s = serde_json::to_string(&t).unwrap();
        let back: Phase0Thresholds = serde_json::from_str(&s).unwrap();
        assert_eq!(t, back);
    }
}
