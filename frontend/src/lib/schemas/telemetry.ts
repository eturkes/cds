/**
 * `ClinicalTelemetryPayload` — TS mirror of `crates/kernel/src/schema/telemetry.rs`.
 *
 * The Rust source-of-truth uses `BTreeMap<String, f64>` for `vitals`; the wire
 * shape is therefore lexicographically-sorted. TS objects do not preserve
 * insertion order on integer-string-coerced keys, so the BFF runs every
 * outbound vitals record through {@link sortRecordKeys} before encoding.
 */

import { asArray, asInt, asNumber, asObject, asRecord, asString, sortRecordKeys } from './parse';

export interface TelemetrySource {
	device_id: string;
	patient_pseudo_id: string;
}

export interface DiscreteEvent {
	name: string;
	at_monotonic_ns: number;
	data: unknown;
}

export interface TelemetrySample {
	wall_clock_utc: string;
	monotonic_ns: number;
	vitals: Record<string, number>;
	events: DiscreteEvent[];
}

export interface ClinicalTelemetryPayload {
	schema_version: string;
	source: TelemetrySource;
	samples: TelemetrySample[];
}

function parseSource(value: unknown, path: string): TelemetrySource {
	const obj = asObject(value, path);
	return {
		device_id: asString(obj.device_id, `${path}.device_id`),
		patient_pseudo_id: asString(obj.patient_pseudo_id, `${path}.patient_pseudo_id`)
	};
}

function parseEvent(value: unknown, path: string): DiscreteEvent {
	const obj = asObject(value, path);
	return {
		name: asString(obj.name, `${path}.name`),
		at_monotonic_ns: asInt(obj.at_monotonic_ns, `${path}.at_monotonic_ns`),
		data: obj.data
	};
}

function parseSample(value: unknown, path: string): TelemetrySample {
	const obj = asObject(value, path);
	return {
		wall_clock_utc: asString(obj.wall_clock_utc, `${path}.wall_clock_utc`),
		monotonic_ns: asInt(obj.monotonic_ns, `${path}.monotonic_ns`),
		vitals: asRecord(obj.vitals, `${path}.vitals`, asNumber),
		events: asArray(obj.events, `${path}.events`, parseEvent)
	};
}

export function parseClinicalTelemetryPayload(value: unknown): ClinicalTelemetryPayload {
	const obj = asObject(value, 'ClinicalTelemetryPayload');
	return {
		schema_version: asString(obj.schema_version, 'ClinicalTelemetryPayload.schema_version'),
		source: parseSource(obj.source, 'ClinicalTelemetryPayload.source'),
		samples: asArray(obj.samples, 'ClinicalTelemetryPayload.samples', parseSample)
	};
}

/**
 * Restore lexicographic ordering on every sample's `vitals` record. Use this
 * on every outbound payload destined for the harness so the on-the-wire
 * shape matches the Rust `BTreeMap` key order.
 */
export function sortVitalsKeys(payload: ClinicalTelemetryPayload): ClinicalTelemetryPayload {
	return {
		...payload,
		samples: payload.samples.map((s) => ({ ...s, vitals: sortRecordKeys(s.vitals) }))
	};
}
