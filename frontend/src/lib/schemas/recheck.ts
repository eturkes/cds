/**
 * `LeanRecheckWire` — TS mirror of `crates/kernel/src/service/handlers.rs`.
 *
 * The kernel's internal `LeanRecheck` does not derive `Serialize`; the
 * wire shape lives in `LeanRecheckWire` so the snake-case severity
 * (`info` / `warning` / `error`) is locked at the service boundary.
 * `env_id` is `Option<String>` and surfaces as `null` on the wire when the
 * Kimina envelope has no environment id.
 */

import {
	asArray,
	asInt,
	asLiteral,
	asNullable,
	asObject,
	asRecord,
	asString,
	asBool
} from './parse';

export type LeanSeverityWire = 'info' | 'warning' | 'error';

export interface LeanMessageWire {
	severity: LeanSeverityWire;
	body: string;
}

export interface LeanRecheckWire {
	ok: boolean;
	custom_id: string;
	env_id: string | null;
	elapsed_ms: number;
	messages: LeanMessageWire[];
	probes: Record<string, string>;
}

const SEVERITIES = ['info', 'warning', 'error'] as const;

function parseMessage(value: unknown, path: string): LeanMessageWire {
	const obj = asObject(value, path);
	return {
		severity: asLiteral(obj.severity, `${path}.severity`, SEVERITIES),
		body: asString(obj.body, `${path}.body`)
	};
}

export function parseLeanRecheckWire(value: unknown): LeanRecheckWire {
	const obj = asObject(value, 'LeanRecheckWire');
	return {
		ok: asBool(obj.ok, 'LeanRecheckWire.ok'),
		custom_id: asString(obj.custom_id, 'LeanRecheckWire.custom_id'),
		env_id: asNullable(obj.env_id, 'LeanRecheckWire.env_id', asString),
		elapsed_ms: asInt(obj.elapsed_ms, 'LeanRecheckWire.elapsed_ms'),
		messages: asArray(obj.messages, 'LeanRecheckWire.messages', parseMessage),
		probes: asRecord(obj.probes, 'LeanRecheckWire.probes', asString)
	};
}
