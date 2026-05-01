/**
 * Schema parity tripwire — ADR-022 §8.
 *
 * Decode every Rust-emitted golden JSON fixture under `tests/golden/`
 * through the matching TS parser; assert deep-equality with the raw JSON.
 * Detects drift in either direction:
 *
 * - Rust adds a field → TS parser drops it → `parsed !== raw` → fails.
 * - TS parser expects a field the Rust source no longer emits → throws
 *   `SchemaParseError` at parse time → fails.
 *
 * The "all fixtures exercised" coverage check fails if a new fixture lands
 * without a parser registration here.
 */

import { describe, expect, it } from 'vitest';
import { readFileSync, readdirSync } from 'node:fs';
import { join, resolve } from 'node:path';

import {
	parseClinicalTelemetryPayload,
	parseFormalVerificationTrace,
	parseOnionLIRTree,
	parseSmtConstraintMatrix
} from './index';

const goldenDir = resolve(import.meta.dirname, '../../../../tests/golden');

const parsers: Record<string, (value: unknown) => unknown> = {
	'clinical_telemetry_payload.json': parseClinicalTelemetryPayload,
	'onionl_ir_tree.json': parseOnionLIRTree,
	'smt_constraint_matrix.json': parseSmtConstraintMatrix,
	'formal_verification_trace.json': parseFormalVerificationTrace
};

describe('schema parity tripwire', () => {
	for (const [filename, parse] of Object.entries(parsers)) {
		it(`round-trips ${filename}`, () => {
			const raw: unknown = JSON.parse(readFileSync(join(goldenDir, filename), 'utf8'));
			const parsed = parse(raw);
			expect(parsed).toStrictEqual(raw);
		});
	}

	it('every Rust golden fixture has a registered TS parser', () => {
		const onDisk = readdirSync(goldenDir)
			.filter((name) => name.endsWith('.json'))
			.sort();
		const registered = Object.keys(parsers).sort();
		expect(onDisk).toStrictEqual(registered);
	});
});
