/**
 * Typed lift of the kernel + harness `{error, detail}` HTTP 422 envelope
 * shared across all five Phase 0 BFF routes. ADR-019 §1 + ADR-018 §1
 * established the wire format on the backend; this class preserves the
 * original status + structured fields so each `+server.ts` can re-emit
 * an identical envelope to the browser.
 */
export class BackendError extends Error {
	constructor(
		public readonly status: number,
		public readonly code: string,
		public readonly detail: string
	) {
		super(`backend ${status} ${code}: ${detail}`);
		this.name = 'BackendError';
	}
}
