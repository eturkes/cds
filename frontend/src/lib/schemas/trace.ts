/**
 * `FormalVerificationTrace` — TS mirror of
 * `crates/kernel/src/schema/verification.rs`.
 *
 * `alethe_proof` is `Option<String>` on the Rust side without a
 * `skip_serializing_if`, so the wire shape carries `null` when sat or
 * before cvc5 emits a certificate.
 */

import { asArray, asBool, asNullable, asObject, asString } from './parse';

export interface FormalVerificationTrace {
	schema_version: string;
	sat: boolean;
	muc: string[];
	alethe_proof: string | null;
}

export function parseFormalVerificationTrace(value: unknown): FormalVerificationTrace {
	const obj = asObject(value, 'FormalVerificationTrace');
	return {
		schema_version: asString(obj.schema_version, 'FormalVerificationTrace.schema_version'),
		sat: asBool(obj.sat, 'FormalVerificationTrace.sat'),
		muc: asArray(obj.muc, 'FormalVerificationTrace.muc', asString),
		alethe_proof: asNullable(obj.alethe_proof, 'FormalVerificationTrace.alethe_proof', asString)
	};
}
