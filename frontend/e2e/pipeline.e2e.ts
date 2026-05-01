import { expect, test } from '@playwright/test';

/**
 * Phase 0 close-out E2E (Task 9.3).
 *
 * Drives the canonical `contradictory-bound` flow end-to-end against a
 * live Dapr cluster (placement + scheduler + cds-harness sidecar +
 * cds-kernel sidecar + Kimina) plus an adapter-node BFF spawned by the
 * `frontend-pipeline-smoke` Justfile recipe. The recipe sets
 * `CDS_E2E_BASE_URL` to the BFF's allocated port; absent that env var
 * the test self-skips (so a bare `just frontend-e2e` invocation does
 * not need cluster prerequisites).
 *
 * Cross-reference: ADR-022 §4 (visualizers + Phase 0 close-out gate).
 */
const baseURL = process.env.CDS_E2E_BASE_URL ?? '';

test.describe('Phase 0 pipeline UI', () => {
	test.skip(baseURL === '', 'CDS_E2E_BASE_URL unset — see `just frontend-pipeline-smoke`');
	// The /api/recheck call POSTs through Kimina and can take ~60–90 s in
	// the worst case; let the whole pipeline run have ~6 minutes of head-room
	// before the harness flags a flake.
	test.setTimeout(360_000);

	test('contradictory-bound run lights up unsat banner + MUC viewer + AST highlights', async ({
		page
	}) => {
		await page.goto(baseURL);

		await expect(page.getByRole('heading', { name: 'Pipeline visualizer' })).toBeVisible();

		// Default form values reproduce the canonical contradictory-bound fixture.
		await page.getByTestId('run-button').click();

		// Wait for every stage to settle to ok.
		for (const stage of ['ingest', 'translate', 'deduce', 'solve', 'recheck']) {
			await expect
				.poll(
					async () =>
						page.getByTestId(`stage-badge-${stage}`).getAttribute('data-status'),
					{ timeout: 300_000, intervals: [500, 1000, 2000] }
				)
				.toBe('ok');
		}

		// Verification banner — sat pill should land on `unsat`, recheck on `ok`.
		await expect(page.getByTestId('sat-pill')).toHaveAttribute('data-state', 'unsat');
		await expect(page.getByTestId('recheck-pill')).toHaveAttribute('data-state', 'ok');
		await expect(page.getByTestId('sat-pill')).toContainText('unsat');
		await expect(page.getByTestId('recheck-pill')).toContainText('Lean recheck ✓');

		// MUC viewer should show ≥2 entries (canonical fixture has two atoms).
		const mucEntries = page.getByTestId('muc-entry');
		await expect(mucEntries).toHaveCount(2, { timeout: 30_000 });
		const firstEntry = await mucEntries.first().getAttribute('data-span-id');
		expect(firstEntry).toMatch(/^atom:contradictory-bound:\d+-\d+$/);

		// AST tree should highlight at least two atom nodes with bg-rose-100
		// (the per-atom MUC marker — Tailwind class via class:bg-rose-100).
		const mucNodes = page.locator('[data-testid=ast-node][data-muc=\"true\"]');
		await expect(mucNodes).toHaveCount(2, { timeout: 30_000 });

		// Cross-component highlight: clicking a MUC entry pulses the AST node.
		await mucEntries.first().click();
		const targetSpan = await mucEntries.first().getAttribute('data-span-id');
		expect(targetSpan).not.toBeNull();
		await expect(
			page.locator(`[data-testid=ast-node][data-span-id=\"${targetSpan}\"]`)
		).toBeVisible();

		// Octagon panel renders an SVG once the deduce verdict is in.
		await expect(page.getByTestId('octagon-svg')).toBeVisible();
	});
});
