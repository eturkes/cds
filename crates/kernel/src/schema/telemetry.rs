//! `ClinicalTelemetryPayload` — continuous physiological telemetry frames.
//!
//! Every `TelemetrySample` carries a wall-clock UTC timestamp (RFC 3339) for
//! human-readable provenance plus a monotonic-clock nanosecond counter for
//! deterministic ordering across host clock skew. Vitals are floating-point
//! scalars keyed by canonical observation name (e.g. `heart_rate_bpm`,
//! `spo2_percent`); discrete events carry a free-form structured `data`
//! payload.
//!
//! Duplicate `monotonic_ns` values across samples are **rejected** by the
//! ingestion stage (Task 3); this module only defines the shape, not the
//! ingestion policy.

use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};

/// Top-level telemetry envelope. Carries metadata + an ordered sample stream.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ClinicalTelemetryPayload {
    pub schema_version: String,
    pub source: TelemetrySource,
    pub samples: Vec<TelemetrySample>,
}

/// Provenance for a telemetry stream — pseudonymous patient + device.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct TelemetrySource {
    pub device_id: String,
    pub patient_pseudo_id: String,
}

/// A single instant of physiological observation.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct TelemetrySample {
    /// RFC 3339 / ISO-8601 UTC timestamp (e.g. `"2026-04-29T12:55:00.123456Z"`).
    pub wall_clock_utc: String,
    /// Monotonic-clock counter (nanoseconds since arbitrary host epoch).
    pub monotonic_ns: u64,
    /// Continuous scalar observations keyed by canonical observation name.
    /// `BTreeMap` ensures lexicographic key ordering on serialization for
    /// byte-stable JSON between equal payloads.
    pub vitals: BTreeMap<String, f64>,
    /// Discrete events that fired within this sample's frame.
    pub events: Vec<DiscreteEvent>,
}

/// A non-continuous clinical event (alarm, intervention, annotation).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct DiscreteEvent {
    pub name: String,
    pub at_monotonic_ns: u64,
    pub data: serde_json::Value,
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fixture() -> ClinicalTelemetryPayload {
        let mut vitals = BTreeMap::new();
        vitals.insert("heart_rate_bpm".to_string(), 72.5);
        vitals.insert("spo2_percent".to_string(), 98.0);
        ClinicalTelemetryPayload {
            schema_version: "0.1.0".to_string(),
            source: TelemetrySource {
                device_id: "icu-monitor-01".to_string(),
                patient_pseudo_id: "pseudo-abc123".to_string(),
            },
            samples: vec![TelemetrySample {
                wall_clock_utc: "2026-04-29T12:55:00.123456Z".to_string(),
                monotonic_ns: 1_234_567_890_123,
                vitals,
                events: vec![DiscreteEvent {
                    name: "manual_bp_cuff_inflate".to_string(),
                    at_monotonic_ns: 1_234_567_890_500,
                    data: serde_json::json!({"operator": "rn-077"}),
                }],
            }],
        }
    }

    #[test]
    fn round_trip_json() {
        let original = fixture();
        let serialized = serde_json::to_string(&original).expect("serialize");
        let deserialized: ClinicalTelemetryPayload =
            serde_json::from_str(&serialized).expect("deserialize");
        assert_eq!(original, deserialized);
    }

    #[test]
    fn vitals_keys_serialize_in_sorted_order() {
        let payload = fixture();
        let json = serde_json::to_string(&payload).expect("serialize");
        let hr_pos = json.find("heart_rate_bpm").expect("hr present");
        let sp_pos = json.find("spo2_percent").expect("spo2 present");
        assert!(
            hr_pos < sp_pos,
            "BTreeMap must serialize keys in lexicographic order"
        );
    }
}
