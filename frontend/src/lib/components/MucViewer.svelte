<script lang="ts">
	import { pulseHighlight, getHighlightedSpan } from '$lib/stores/highlight.svelte';

	type Props = { muc: readonly string[] };
	const { muc }: Props = $props();

	const highlighted = $derived(getHighlightedSpan());
</script>

<section class="rounded-md border border-slate-200 bg-white p-3" data-testid="muc-panel">
	<header class="mb-2 flex items-baseline justify-between">
		<h3 class="text-sm font-semibold text-slate-800">Minimal Unsatisfiable Core</h3>
		<span class="text-xs text-slate-500" data-testid="muc-count">{muc.length} entries</span>
	</header>
	{#if muc.length === 0}
		<p class="text-xs text-slate-500" data-testid="muc-empty">
			No MUC entries — the matrix is satisfiable.
		</p>
	{:else}
		<ul class="space-y-1">
			{#each muc as entry (entry)}
				<li>
					<button
						type="button"
						data-testid="muc-entry"
						data-span-id={entry}
						class="w-full rounded px-2 py-1 text-left font-mono text-xs ring-1 ring-rose-200 transition hover:bg-rose-50 hover:ring-rose-300"
						class:bg-rose-100={highlighted === entry}
						class:ring-rose-400={highlighted === entry}
						class:bg-white={highlighted !== entry}
						onclick={() => pulseHighlight(entry)}
					>
						{entry}
					</button>
				</li>
			{/each}
		</ul>
	{/if}
</section>
