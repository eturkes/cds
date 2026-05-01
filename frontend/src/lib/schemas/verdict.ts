/**
 * `Verdict` — TS mirror of `crates/kernel/src/deduce/mod.rs`.
 *
 * `BreachSummary` enumerates the nine canonical clinical conditions tracked
 * by Phase 0's Datalog rule set; each list is sorted + deduplicated on the
 * Rust side. `octagon_bounds` keys match the canonical-vital allowlist
 * (see `crates/kernel/src/canonical.rs`); the wire shape is a
 * `BTreeMap<String, VitalInterval>`.
 */

import { asArray, asInt, asNumber, asObject, asRecord } from './parse';

export interface VitalInterval {
	low: number;
	high: number;
}

export interface BreachSummary {
	tachycardia: number[];
	bradycardia: number[];
	desaturation: number[];
	hypotension: number[];
	hypertension: number[];
	hyperthermia: number[];
	hypothermia: number[];
	tachypnea: number[];
	bradypnea: number[];
}

export interface Verdict {
	samples_processed: number;
	octagon_bounds: Record<string, VitalInterval>;
	early_warnings: number[];
	compound_alarms: number[];
	breach_summary: BreachSummary;
}

function parseInterval(value: unknown, path: string): VitalInterval {
	const obj = asObject(value, path);
	return {
		low: asNumber(obj.low, `${path}.low`),
		high: asNumber(obj.high, `${path}.high`)
	};
}

function parseBreachSummary(value: unknown, path: string): BreachSummary {
	const obj = asObject(value, path);
	const conditions = [
		'tachycardia',
		'bradycardia',
		'desaturation',
		'hypotension',
		'hypertension',
		'hyperthermia',
		'hypothermia',
		'tachypnea',
		'bradypnea'
	] as const;
	const out: Partial<BreachSummary> = {};
	for (const cond of conditions) {
		out[cond] = asArray(obj[cond], `${path}.${cond}`, asInt);
	}
	return out as BreachSummary;
}

export function parseVerdict(value: unknown): Verdict {
	const obj = asObject(value, 'Verdict');
	return {
		samples_processed: asInt(obj.samples_processed, 'Verdict.samples_processed'),
		octagon_bounds: asRecord(obj.octagon_bounds, 'Verdict.octagon_bounds', parseInterval),
		early_warnings: asArray(obj.early_warnings, 'Verdict.early_warnings', asInt),
		compound_alarms: asArray(obj.compound_alarms, 'Verdict.compound_alarms', asInt),
		breach_summary: parseBreachSummary(obj.breach_summary, 'Verdict.breach_summary')
	};
}
