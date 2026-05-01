/**
 * Cross-component MUC highlight store.
 *
 * The MUC viewer publishes a clicked source-span id; the AST tree subscribes
 * and visually pulses the matching node. State is held in a Svelte 5 `$state`
 * rune that callers reach through getter/setter functions — the rune lives
 * inside a `.svelte.ts` module so its reactivity wires correctly when
 * imported into `.svelte` components.
 *
 * Cross-reference: ADR-022 §4 (visualizer-library policy + cross-component
 * highlight via small `$state` store).
 */

let highlighted = $state<string | null>(null);
let pulseToken = $state(0);

/** Currently highlighted MUC span id, or `null` when none. */
export function getHighlightedSpan(): string | null {
	return highlighted;
}

/** Monotonic token bumped on every `pulseHighlight` call (forces effect rerun). */
export function getPulseToken(): number {
	return pulseToken;
}

/**
 * Set the highlighted span and bump the pulse token. The token bump matters
 * even when the same span is re-clicked: the AST tree's pulse animation
 * should re-trigger so the user sees feedback on the second click.
 */
export function pulseHighlight(span: string | null): void {
	highlighted = span;
	pulseToken += 1;
}
