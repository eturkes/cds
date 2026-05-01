/**
 * Shape-validation primitives for the hand-written TypeScript schema mirrors.
 *
 * Each `parse*` helper in the sibling modules walks an `unknown` input,
 * verifies every documented field, and returns a rebuilt object containing
 * only the documented fields. That guarantees the Vitest parity tripwire
 * (`parity.test.ts`) catches drift in either direction: a Rust-side new
 * field that the TS parser drops, or a TS-side stale field the Rust source
 * has removed.
 *
 * Cross-reference: ADR-022 §8 (hand-written TS, parity tripwire over codegen).
 */

export class SchemaParseError extends Error {
	constructor(
		public readonly path: string,
		public readonly expected: string,
		public readonly actual: unknown
	) {
		super(`SchemaParseError at ${path}: expected ${expected}, got ${describe(actual)}`);
		this.name = 'SchemaParseError';
	}
}

function describe(value: unknown): string {
	if (value === null) return 'null';
	if (Array.isArray(value)) return 'array';
	return typeof value;
}

export function asObject(value: unknown, path: string): Record<string, unknown> {
	if (value === null || typeof value !== 'object' || Array.isArray(value)) {
		throw new SchemaParseError(path, 'object', value);
	}
	return value as Record<string, unknown>;
}

export function asString(value: unknown, path: string): string {
	if (typeof value !== 'string') throw new SchemaParseError(path, 'string', value);
	return value;
}

export function asNumber(value: unknown, path: string): number {
	if (typeof value !== 'number' || Number.isNaN(value)) {
		throw new SchemaParseError(path, 'number', value);
	}
	return value;
}

export function asInt(value: unknown, path: string): number {
	const n = asNumber(value, path);
	if (!Number.isInteger(n)) throw new SchemaParseError(path, 'integer', value);
	return n;
}

export function asBool(value: unknown, path: string): boolean {
	if (typeof value !== 'boolean') throw new SchemaParseError(path, 'boolean', value);
	return value;
}

export function asArray<T>(value: unknown, path: string, item: (v: unknown, p: string) => T): T[] {
	if (!Array.isArray(value)) throw new SchemaParseError(path, 'array', value);
	return value.map((entry, idx) => item(entry, `${path}[${idx}]`));
}

export function asRecord<T>(
	value: unknown,
	path: string,
	item: (v: unknown, p: string) => T
): Record<string, T> {
	const obj = asObject(value, path);
	const out: Record<string, T> = {};
	for (const [k, v] of Object.entries(obj)) {
		out[k] = item(v, `${path}.${k}`);
	}
	return out;
}

export function asNullable<T>(
	value: unknown,
	path: string,
	item: (v: unknown, p: string) => T
): T | null {
	if (value === null) return null;
	return item(value, path);
}

export function asLiteral<T extends string>(
	value: unknown,
	path: string,
	literals: readonly T[]
): T {
	const s = asString(value, path);
	if (!(literals as readonly string[]).includes(s)) {
		throw new SchemaParseError(path, `one of ${literals.join('|')}`, value);
	}
	return s as T;
}

/**
 * Sort the keys of a record into lexicographic order, matching the Rust
 * `BTreeMap`'s on-the-wire ordering. The harness side guarantees this on
 * outbound JSON; the BFF restores it before forwarding any payload that
 * a TS object may have reordered (V8 / SpiderMonkey reorder integer-string
 * keys to numeric order).
 *
 * Cross-reference: open notes for Task 9.2 — `sortVitalsKeys` requirement.
 */
export function sortRecordKeys<T>(rec: Record<string, T>): Record<string, T> {
	const out: Record<string, T> = {};
	for (const k of Object.keys(rec).sort()) {
		out[k] = rec[k] as T;
	}
	return out;
}
