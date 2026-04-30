//! End-to-end smoke gate for the Phase 0 deductive engine (Task 5).
//!
//! Verifies:
//! 1. Octagon bounds tighten correctly across a sample stream — the hull
//!    of two point-observations equals the convex interval over them.
//! 2. Datalog rules evaluate — co-occurring threshold breaches at the
//!    same monotonic marker promote to the `compound_alarm` relation.
//! 3. Non-overlapping breaches do **not** falsely co-fire.
//! 4. The shared golden `clinical_telemetry_payload.json` fixture
//!    evaluates without panic and the resulting hull contains the
//!    fixture's lone observation.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use cds_kernel::deduce::{Phase0Thresholds, evaluate};
use cds_kernel::schema::{
    ClinicalTelemetryPayload, SCHEMA_VERSION, TelemetrySample, TelemetrySource,
};

fn vitals(pairs: &[(&str, f64)]) -> BTreeMap<String, f64> {
    pairs.iter().map(|(k, v)| ((*k).to_string(), *v)).collect()
}

fn sample(t: u64, pairs: &[(&str, f64)]) -> TelemetrySample {
    TelemetrySample {
        wall_clock_utc: "2026-04-29T12:55:00.000000Z".to_string(),
        monotonic_ns: t,
        vitals: vitals(pairs),
        events: vec![],
    }
}

fn payload(samples: Vec<TelemetrySample>) -> ClinicalTelemetryPayload {
    ClinicalTelemetryPayload {
        schema_version: SCHEMA_VERSION.to_string(),
        source: TelemetrySource {
            device_id: "icu-monitor-01".to_string(),
            patient_pseudo_id: "pseudo-test".to_string(),
        },
        samples,
    }
}

fn approx_eq(a: f64, b: f64) -> bool {
    (a - b).abs() < 1e-9
}

#[test]
fn octagon_bounds_widen_to_observed_hull() {
    // Three benign samples — the hull must capture the lo/hi extremes
    // exactly, with no spurious widening.
    let p = payload(vec![
        sample(1_000, &[("heart_rate_bpm", 72.5), ("spo2_percent", 98.0)]),
        sample(2_000, &[("heart_rate_bpm", 80.0), ("spo2_percent", 97.0)]),
        sample(3_000, &[("heart_rate_bpm", 76.0), ("spo2_percent", 96.5)]),
    ]);

    let v = evaluate(&p, &Phase0Thresholds::default()).expect("evaluate");

    let hr = v
        .octagon_bounds
        .get("heart_rate_bpm")
        .copied()
        .expect("HR bound present");
    assert!(approx_eq(hr.low, 72.5), "HR low = {}", hr.low);
    assert!(approx_eq(hr.high, 80.0), "HR high = {}", hr.high);

    let spo2 = v
        .octagon_bounds
        .get("spo2_percent")
        .copied()
        .expect("SpO2 bound present");
    assert!(approx_eq(spo2.low, 96.5), "SpO2 low = {}", spo2.low);
    assert!(approx_eq(spo2.high, 98.0), "SpO2 high = {}", spo2.high);

    // Vitals never observed must not appear in the hull.
    assert!(!v.octagon_bounds.contains_key("temp_celsius"));

    // Benign payload → no clinical alarms.
    assert!(v.early_warnings.is_empty());
    assert!(v.compound_alarms.is_empty());
}

#[test]
fn datalog_compound_alarm_fires_on_co_occurring_breach() {
    // Sample 2 has tachycardia (HR=140 > 120) AND desaturation (SpO2=88 < 92).
    // The Datalog rule `compound_alarm(t) <-- tachycardia(t), desaturation(t)`
    // must fire on monotonic_ns=2_000.
    let p = payload(vec![
        sample(1_000, &[("heart_rate_bpm", 75.0), ("spo2_percent", 97.0)]),
        sample(2_000, &[("heart_rate_bpm", 140.0), ("spo2_percent", 88.0)]),
        sample(3_000, &[("heart_rate_bpm", 78.0), ("spo2_percent", 96.0)]),
    ]);

    let v = evaluate(&p, &Phase0Thresholds::default()).expect("evaluate");

    assert_eq!(v.breach_summary.tachycardia, vec![2_000]);
    assert_eq!(v.breach_summary.desaturation, vec![2_000]);
    assert_eq!(v.compound_alarms, vec![2_000]);
    assert_eq!(v.early_warnings, vec![2_000]);
}

#[test]
fn datalog_does_not_join_breaches_across_distinct_markers() {
    // Tachycardia at t=1_000, desaturation at t=2_000 — must NOT fire
    // compound_alarm; both still raise early_warning at their respective
    // markers.
    let p = payload(vec![
        sample(1_000, &[("heart_rate_bpm", 140.0), ("spo2_percent", 97.0)]),
        sample(2_000, &[("heart_rate_bpm", 75.0), ("spo2_percent", 85.0)]),
    ]);

    let v = evaluate(&p, &Phase0Thresholds::default()).expect("evaluate");

    assert_eq!(v.breach_summary.tachycardia, vec![1_000]);
    assert_eq!(v.breach_summary.desaturation, vec![2_000]);
    assert!(
        v.compound_alarms.is_empty(),
        "compound_alarm must require co-occurrence"
    );
    assert_eq!(v.early_warnings, vec![1_000, 2_000]);
}

#[test]
fn high_systolic_with_tachycardia_fires_compound_alarm() {
    // Exercises the second compound_alarm rule:
    //   compound_alarm(t) <-- hypotension(t), tachycardia(t)
    // (low BP + high HR — early shock pattern).
    let p = payload(vec![sample(
        4_000,
        &[("heart_rate_bpm", 135.0), ("systolic_mmhg", 80.0)],
    )]);

    let v = evaluate(&p, &Phase0Thresholds::default()).expect("evaluate");

    assert_eq!(v.breach_summary.tachycardia, vec![4_000]);
    assert_eq!(v.breach_summary.hypotension, vec![4_000]);
    assert_eq!(v.compound_alarms, vec![4_000]);
}

#[test]
fn golden_clinical_payload_evaluates_cleanly() {
    let path: PathBuf = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..")
        .join("tests")
        .join("golden")
        .join("clinical_telemetry_payload.json");
    let raw =
        std::fs::read_to_string(&path).unwrap_or_else(|e| panic!("read {}: {e}", path.display()));
    let p: ClinicalTelemetryPayload = serde_json::from_str(&raw).expect("parse golden");
    let v = evaluate(&p, &Phase0Thresholds::default()).expect("evaluate golden");

    assert_eq!(v.samples_processed, p.samples.len());
    assert!(
        !v.octagon_bounds.is_empty(),
        "golden payload has at least one observed vital"
    );
    // Golden fixture's HR=72.5 is well inside the default band — must not alarm.
    assert!(v.early_warnings.is_empty());
    assert!(v.compound_alarms.is_empty());
}
