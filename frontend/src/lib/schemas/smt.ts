/**
 * `SmtConstraintMatrix` — TS mirror of `crates/kernel/src/schema/smt.rs`.
 *
 * `provenance` is `Option<String>` on the Rust side without a
 * `skip_serializing_if`, so on the wire it surfaces as `null` (not absent)
 * when the assertion is kernel-synthesized. The TS shape matches with
 * `string | null` rather than `string | undefined`.
 */

import { asArray, asBool, asNullable, asObject, asString } from './parse';

export interface LabelledAssertion {
	label: string;
	formula: string;
	enabled: boolean;
	provenance: string | null;
}

export interface SmtConstraintMatrix {
	schema_version: string;
	logic: string;
	theories: string[];
	preamble: string;
	assumptions: LabelledAssertion[];
}

function parseAssertion(value: unknown, path: string): LabelledAssertion {
	const obj = asObject(value, path);
	return {
		label: asString(obj.label, `${path}.label`),
		formula: asString(obj.formula, `${path}.formula`),
		enabled: asBool(obj.enabled, `${path}.enabled`),
		provenance: asNullable(obj.provenance, `${path}.provenance`, asString)
	};
}

export function parseSmtConstraintMatrix(value: unknown): SmtConstraintMatrix {
	const obj = asObject(value, 'SmtConstraintMatrix');
	return {
		schema_version: asString(obj.schema_version, 'SmtConstraintMatrix.schema_version'),
		logic: asString(obj.logic, 'SmtConstraintMatrix.logic'),
		theories: asArray(obj.theories, 'SmtConstraintMatrix.theories', asString),
		preamble: asString(obj.preamble, 'SmtConstraintMatrix.preamble'),
		assumptions: asArray(obj.assumptions, 'SmtConstraintMatrix.assumptions', parseAssertion)
	};
}
