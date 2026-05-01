/**
 * `POST /api/deduce` — proxy to `cds-kernel/method/v1/deduce`.
 *
 * Body: `{payload: ClinicalTelemetryPayload, rules?: Phase0Thresholds}`.
 * Returns: `Verdict`.
 */

import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { BackendError } from '$lib/server/errors';
import { backendErrorResponse, invokeKernel } from '$lib/server/dapr';
import { parseVerdict } from '$lib/schemas';

export const POST: RequestHandler = async ({ request }) => {
	const body: unknown = await request.json();
	try {
		const response = await invokeKernel('/v1/deduce', body, 'deduce');
		return json(parseVerdict(response));
	} catch (e) {
		if (e instanceof BackendError) return backendErrorResponse(e);
		throw e;
	}
};
