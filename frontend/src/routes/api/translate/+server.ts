/**
 * `POST /api/translate` — proxy to `cds-harness/method/v1/translate`.
 *
 * Body: `{doc_id, text, root, logic?, smt_check?}`. The harness returns
 * `{tree, matrix, smt_check?}`; the BFF rebrands `tree → ir` to match the
 * downstream `PipelineEnvelope` field naming established by the workflow
 * harness (8.4b) and ADR-022 §3.
 */

import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { BackendError } from '$lib/server/errors';
import { backendErrorResponse, invokeHarness } from '$lib/server/dapr';
import { asObject, parseOnionLIRTree, parseSmtConstraintMatrix } from '$lib/schemas';

export const POST: RequestHandler = async ({ request }) => {
	const body: unknown = await request.json();
	try {
		const response = await invokeHarness('/v1/translate', body, 'translate');
		const obj = asObject(response, 'TranslateResponse');
		const ir = parseOnionLIRTree(obj.tree);
		const matrix = parseSmtConstraintMatrix(obj.matrix);
		return json({ ir, matrix });
	} catch (e) {
		if (e instanceof BackendError) return backendErrorResponse(e);
		throw e;
	}
};
