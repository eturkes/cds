import { describe, expect, it } from 'vitest';

// Tombstone — proves the Vitest runner is wired (Task 9.1). The schema
// parity tripwire lands in Task 9.2.
describe('vitest tombstone', () => {
	it('runner is wired', () => {
		expect(1 + 1).toBe(2);
	});
});
