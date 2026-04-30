//! Phase 0 Datalog program — `ascent` in-process rule engine.
//!
//! Inputs are *threshold-breach* facts emitted by the kernel's evaluator
//! after pre-discriminating each `TelemetrySample.vitals` reading against
//! the `Phase0Thresholds` rule set. Each input fact carries the sample's
//! `monotonic_ns` as a `u64` key — the only column type we need at this
//! stage, which sidesteps the `f64`/`Eq+Hash` impedance mismatch by keeping
//! all numeric reasoning *outside* Datalog (where the octagon already
//! handles it). Datalog therefore only does what it is uniquely good at:
//! deductive closure over symbolic relations.
//!
//! Derived predicates split into named clinical conditions (one per
//! breach kind) and two roll-ups (`early_warning`, `compound_alarm`) that
//! demonstrate transitive rule firing. The set is deliberately small;
//! Tasks 6+ widen the rule base once SMT integration is online.

#![allow(clippy::pedantic, clippy::all, dead_code, missing_docs)]

ascent::ascent! {
    pub struct ClinicalDeductionProgram;
    // -- Threshold-breach inputs (one per (vital, direction) pair) -----------
    relation hr_high_breach(u64);
    relation hr_low_breach(u64);
    relation spo2_low_breach(u64);
    relation systolic_high_breach(u64);
    relation systolic_low_breach(u64);
    relation diastolic_high_breach(u64);
    relation diastolic_low_breach(u64);
    relation temp_high_breach(u64);
    relation temp_low_breach(u64);
    relation rr_high_breach(u64);
    relation rr_low_breach(u64);

    // -- Named clinical conditions -------------------------------------------
    relation tachycardia(u64);
    relation bradycardia(u64);
    relation desaturation(u64);
    relation hypotension(u64);
    relation hypertension(u64);
    relation hyperthermia(u64);
    relation hypothermia(u64);
    relation tachypnea(u64);
    relation bradypnea(u64);

    // -- Roll-up alarms ------------------------------------------------------
    relation early_warning(u64);
    relation compound_alarm(u64);

    tachycardia(t)  <-- hr_high_breach(t);
    bradycardia(t)  <-- hr_low_breach(t);
    desaturation(t) <-- spo2_low_breach(t);
    hypotension(t)  <-- systolic_low_breach(t);
    hypertension(t) <-- systolic_high_breach(t);
    hyperthermia(t) <-- temp_high_breach(t);
    hypothermia(t)  <-- temp_low_breach(t);
    tachypnea(t)    <-- rr_high_breach(t);
    bradypnea(t)    <-- rr_low_breach(t);

    early_warning(t) <-- tachycardia(t);
    early_warning(t) <-- bradycardia(t);
    early_warning(t) <-- desaturation(t);
    early_warning(t) <-- hypotension(t);
    early_warning(t) <-- hypertension(t);
    early_warning(t) <-- hyperthermia(t);
    early_warning(t) <-- hypothermia(t);
    early_warning(t) <-- tachypnea(t);
    early_warning(t) <-- bradypnea(t);

    compound_alarm(t) <-- tachycardia(t), desaturation(t);
    compound_alarm(t) <-- hypotension(t), tachycardia(t);
    compound_alarm(t) <-- desaturation(t), hyperthermia(t);
}

#[cfg(test)]
mod tests {
    use super::ClinicalDeductionProgram;

    fn drain_sorted(rel: &[(u64,)]) -> Vec<u64> {
        let mut v: Vec<u64> = rel.iter().map(|t| t.0).collect();
        v.sort_unstable();
        v.dedup();
        v
    }

    #[test]
    fn no_breaches_yields_no_alarms() {
        let mut prog = ClinicalDeductionProgram::default();
        prog.run();
        assert!(prog.early_warning.is_empty());
        assert!(prog.compound_alarm.is_empty());
    }

    #[test]
    fn isolated_breach_promotes_to_named_condition() {
        let mut prog = ClinicalDeductionProgram::default();
        prog.hr_high_breach.push((1_000,));
        prog.run();
        assert_eq!(drain_sorted(&prog.tachycardia), vec![1_000]);
        assert_eq!(drain_sorted(&prog.early_warning), vec![1_000]);
        assert!(prog.compound_alarm.is_empty());
    }

    #[test]
    fn co_occurring_breaches_fire_compound_alarm() {
        let mut prog = ClinicalDeductionProgram::default();
        prog.hr_high_breach.push((2_000,));
        prog.spo2_low_breach.push((2_000,));
        prog.run();
        assert_eq!(drain_sorted(&prog.tachycardia), vec![2_000]);
        assert_eq!(drain_sorted(&prog.desaturation), vec![2_000]);
        assert_eq!(drain_sorted(&prog.compound_alarm), vec![2_000]);
        assert_eq!(drain_sorted(&prog.early_warning), vec![2_000]);
    }

    #[test]
    fn compound_alarm_requires_co_occurrence_at_same_marker() {
        // Two breaches at *different* monotonic markers must not produce a
        // compound alarm — the Datalog join is on the marker column.
        let mut prog = ClinicalDeductionProgram::default();
        prog.hr_high_breach.push((3_000,));
        prog.spo2_low_breach.push((4_000,));
        prog.run();
        assert!(prog.compound_alarm.is_empty());
        assert_eq!(drain_sorted(&prog.early_warning), vec![3_000, 4_000]);
    }

    #[test]
    fn rule_engine_is_idempotent_under_reruns() {
        // ascent's seminaive evaluation is idempotent: running twice without
        // adding inputs must not double-count derived tuples.
        let mut prog = ClinicalDeductionProgram::default();
        prog.hr_high_breach.push((5_000,));
        prog.run();
        let first: Vec<(u64,)> = prog.early_warning.clone();
        prog.run();
        assert_eq!(prog.early_warning, first);
    }
}
