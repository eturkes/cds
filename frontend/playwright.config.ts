import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright config — Phase 0.
 *
 * The pipeline E2E (`e2e/pipeline.e2e.ts`) self-skips when
 * `CDS_E2E_BASE_URL` is unset, so a bare `just frontend-e2e` exits clean
 * with zero asserted cases. The cluster-bound run is invoked through
 * `just frontend-pipeline-smoke`, which spins placement + scheduler + the
 * two daprd sidecars + an adapter-node BFF on freshly-allocated ports,
 * exports `CDS_E2E_BASE_URL`, and then runs Playwright against the live
 * stack with reverse-teardown traps.
 */
export default defineConfig({
	testDir: 'e2e',
	testMatch: '**/*.e2e.ts',
	fullyParallel: true,
	reporter: [['list']],
	use: { headless: true, baseURL: process.env.CDS_E2E_BASE_URL ?? undefined },
	projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }]
});
