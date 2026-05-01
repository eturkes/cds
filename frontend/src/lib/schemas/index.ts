/**
 * Barrel re-export of the six Phase 0 wire-schema mirrors plus the
 * pipeline aggregate. Hand-written; parity with the Rust + Python
 * source-of-truth is enforced by `parity.test.ts`.
 *
 * Cross-reference: ADR-022 §3 + §8.
 */

export {
	SchemaParseError,
	asArray,
	asBool,
	asInt,
	asLiteral,
	asNullable,
	asNumber,
	asObject,
	asRecord,
	asString,
	sortRecordKeys
} from './parse';

export type {
	ClinicalTelemetryPayload,
	DiscreteEvent,
	TelemetrySample,
	TelemetrySource
} from './telemetry';
export { parseClinicalTelemetryPayload, sortVitalsKeys } from './telemetry';

export type { OnionLIRTree, OnionLNode, SourceSpan, Term } from './onion';
export { parseOnionLIRTree } from './onion';

export type { LabelledAssertion, SmtConstraintMatrix } from './smt';
export { parseSmtConstraintMatrix } from './smt';

export type { BreachSummary, Verdict, VitalInterval } from './verdict';
export { parseVerdict } from './verdict';

export type { FormalVerificationTrace } from './trace';
export { parseFormalVerificationTrace } from './trace';

export type { LeanMessageWire, LeanRecheckWire, LeanSeverityWire } from './recheck';
export { parseLeanRecheckWire } from './recheck';

export type { PipelineEnvelope, PipelineInput } from './pipeline';
