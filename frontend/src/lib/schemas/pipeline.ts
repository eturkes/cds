/**
 * `PipelineInput` + `PipelineEnvelope` — TS mirror of
 * `python/cds_harness/workflow/pipeline.py` (input) and the in-band
 * envelope returned by `pipeline_workflow` (output).
 *
 * Phase 0 BFF drives the per-stage `/api/{ingest,translate,deduce,solve,
 * recheck}` routes directly (ADR-022 §7); this envelope is the shape an
 * eventual `/api/pipeline/workflow` route would return when Phase 1+ adds
 * `DaprWorkflowClient` orchestration. Today the envelope type is the
 * canonical shape for any aggregator that wants to bundle a single
 * pipeline run.
 */

import type { ClinicalTelemetryPayload } from './telemetry';
import type { OnionLIRTree } from './onion';
import type { SmtConstraintMatrix } from './smt';
import type { Verdict } from './verdict';
import type { FormalVerificationTrace } from './trace';
import type { LeanRecheckWire } from './recheck';

export interface PipelineInput {
	doc_id: string;
	guideline_text: string;
	guideline_root: unknown;
	ingest_request: unknown;
	logic: string;
	smt_check: boolean;
	kimina_url: string;
	custom_id: string;
	solve_timeout_ms: number;
	recheck_timeout_ms: number;
	z3_path: string | null;
	cvc5_path: string | null;
}

export interface PipelineEnvelope {
	payload: ClinicalTelemetryPayload;
	ir: OnionLIRTree;
	matrix: SmtConstraintMatrix;
	verdict: Verdict;
	trace: FormalVerificationTrace;
	recheck: LeanRecheckWire;
}
