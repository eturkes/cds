import { defineConfig, devices } from '@playwright/test';

// Phase 0 tombstone — no webServer (no Vite preview spin-up). Real E2E lands in Task 9.3.
export default defineConfig({
	testDir: 'e2e',
	testMatch: '**/*.e2e.ts',
	fullyParallel: true,
	reporter: [['list']],
	use: { headless: true },
	projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }]
});
