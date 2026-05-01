/**
 * Daprd service-invocation client used by every Phase 0 BFF route.
 *
 * Phase 0 BFF talks JSON-over-TCP to two daprd sidecars:
 * - `cds-harness` (Python FastAPI app) — `/v1/ingest` + `/v1/translate`
 * - `cds-kernel`  (Rust axum app)      — `/v1/deduce` + `/v1/solve` + `/v1/recheck`
 *
 * Ports are read at request time (not module load) so a developer running
 * `just frontend-bff-smoke` — which allocates fresh ports per session —
 * sees the current values rather than a cached snapshot. Defaults
 * (3500 / 3501) match the legacy Phase 0 sidecar conventions when env is
 * unset.
 *
 * Cross-reference: ADR-022 §3 + §7. Constraint **C6** binds.
 */

import { BackendError } from './errors';

const HARNESS_APP_ID = 'cds-harness';
const KERNEL_APP_ID = 'cds-kernel';
const DEFAULT_HARNESS_PORT = 3500;
const DEFAULT_KERNEL_PORT = 3501;

export const HARNESS_PORT_ENV = 'DAPR_HTTP_PORT_HARNESS';
export const KERNEL_PORT_ENV = 'DAPR_HTTP_PORT_KERNEL';

function resolvePort(envKey: string, fallback: number): number {
	const raw = process.env[envKey];
	if (raw === undefined || raw.trim() === '') return fallback;
	const n = Number.parseInt(raw, 10);
	if (!Number.isInteger(n) || n < 1 || n > 65535) {
		throw new BackendError(500, 'invalid_dapr_port', `${envKey}=${raw}`);
	}
	return n;
}

async function invoke(
	appId: string,
	port: number,
	path: string,
	body: unknown,
	stage: string
): Promise<unknown> {
	const trimmed = path.startsWith('/') ? path.slice(1) : path;
	const url = `http://127.0.0.1:${port}/v1.0/invoke/${appId}/method/${trimmed}`;
	const t0 = performance.now();
	let res: Response;
	try {
		res = await fetch(url, {
			method: 'POST',
			headers: { 'content-type': 'application/json' },
			body: JSON.stringify(body)
		});
	} catch (cause) {
		console.info(
			JSON.stringify({ stage, app_id: appId, path, status: 'fetch_failed', error: String(cause) })
		);
		throw new BackendError(502, 'dapr_unreachable', `${url}: ${String(cause)}`);
	}
	const text = await res.text();
	const duration_ms = Math.round(performance.now() - t0);
	console.info(JSON.stringify({ stage, app_id: appId, path, status: res.status, duration_ms }));
	if (!res.ok) {
		let code = `http_${res.status}`;
		let detail = text;
		try {
			const decoded: unknown = JSON.parse(text);
			if (
				decoded !== null &&
				typeof decoded === 'object' &&
				'error' in decoded &&
				'detail' in decoded
			) {
				const err = (decoded as Record<string, unknown>).error;
				const det = (decoded as Record<string, unknown>).detail;
				if (typeof err === 'string') code = err;
				if (typeof det === 'string') detail = det;
			}
		} catch {
			// non-JSON body — fall back to raw text.
		}
		throw new BackendError(res.status, code, detail);
	}
	try {
		return JSON.parse(text);
	} catch (cause) {
		throw new BackendError(
			502,
			'dapr_invalid_json',
			`${url}: ${String(cause)}; raw=${text.slice(0, 200)}`
		);
	}
}

export async function invokeHarness(path: string, body: unknown, stage: string): Promise<unknown> {
	return invoke(
		HARNESS_APP_ID,
		resolvePort(HARNESS_PORT_ENV, DEFAULT_HARNESS_PORT),
		path,
		body,
		stage
	);
}

export async function invokeKernel(path: string, body: unknown, stage: string): Promise<unknown> {
	return invoke(
		KERNEL_APP_ID,
		resolvePort(KERNEL_PORT_ENV, DEFAULT_KERNEL_PORT),
		path,
		body,
		stage
	);
}

/**
 * Lift a thrown `BackendError` into a JSON `Response` matching the original
 * status + the canonical `{error, detail}` envelope. Routes call this from
 * their `catch` arm so the on-the-wire error shape is identical to what
 * the upstream daprd path emitted.
 */
export function backendErrorResponse(e: BackendError): Response {
	return new Response(JSON.stringify({ error: e.code, detail: e.detail }), {
		status: e.status,
		headers: { 'content-type': 'application/json' }
	});
}
