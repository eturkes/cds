/**
 * `POST /api/recheck` — proxy to `cds-kernel/method/v1/recheck`.
 *
 * Body: `{trace: FormalVerificationTrace, options?: RecheckOptionsWire}`.
 * Returns: `LeanRecheckWire`.
 */

import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { BackendError } from '$lib/server/errors';
import { backendErrorResponse, invokeKernel } from '$lib/server/dapr';
import { parseLeanRecheckWire } from '$lib/schemas';

export const POST: RequestHandler = async ({ request }) => {
	const body: unknown = await request.json();
	try {
		const response = await invokeKernel('/v1/recheck', body, 'recheck');
		return json(parseLeanRecheckWire(response));
	} catch (e) {
		if (e instanceof BackendError) return backendErrorResponse(e);
		throw e;
	}
};
