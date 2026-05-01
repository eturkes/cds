import { expect, test } from '@playwright/test';

// Tombstone — proves the Playwright runner is wired (Task 9.1). Real E2E
// pipeline coverage lands in Task 9.3 against `frontend-preview` + a live
// Dapr cluster.
test('playwright runner is wired', () => {
	expect(1 + 1).toBe(2);
});
