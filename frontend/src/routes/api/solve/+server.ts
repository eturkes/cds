/**
 * `POST /api/solve` — proxy to `cds-kernel/method/v1/solve`.
 *
 * Body: `{matrix: SmtConstraintMatrix, options?: SolveOptionsWire}`.
 * Returns: `FormalVerificationTrace`.
 */

import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { BackendError } from '$lib/server/errors';
import { backendErrorResponse, invokeKernel } from '$lib/server/dapr';
import { parseFormalVerificationTrace } from '$lib/schemas';

export const POST: RequestHandler = async ({ request }) => {
	const body: unknown = await request.json();
	try {
		const response = await invokeKernel('/v1/solve', body, 'solve');
		return json(parseFormalVerificationTrace(response));
	} catch (e) {
		if (e instanceof BackendError) return backendErrorResponse(e);
		throw e;
	}
};
