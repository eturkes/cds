/**
 * `POST /api/ingest` — proxy to `cds-harness/method/v1/ingest`.
 *
 * Body: `{format: 'json', envelope: ...}` or `{format: 'csv', csv_text, meta, file_label?}`.
 * Returns: `ClinicalTelemetryPayload` (the harness wraps it in `{payload: ...}`;
 * the BFF unwraps so each Phase 0 route returns the bare schema shape).
 */

import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { BackendError } from '$lib/server/errors';
import { backendErrorResponse, invokeHarness } from '$lib/server/dapr';
import { parseClinicalTelemetryPayload, sortVitalsKeys, asObject } from '$lib/schemas';

export const POST: RequestHandler = async ({ request }) => {
	const body: unknown = await request.json();
	try {
		const response = await invokeHarness('/v1/ingest', body, 'ingest');
		const obj = asObject(response, 'IngestResponse');
		const payload = parseClinicalTelemetryPayload(obj.payload);
		return json(sortVitalsKeys(payload));
	} catch (e) {
		if (e instanceof BackendError) return backendErrorResponse(e);
		throw e;
	}
};
