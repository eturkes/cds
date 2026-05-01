<script lang="ts" module>
	import type { OnionLNode, SourceSpan } from '$lib/schemas';
	export function atomSpanId(span: SourceSpan): string {
		return `atom:${span.doc_id}:${span.start}-${span.end}`;
	}
	export function nodeLabel(node: OnionLNode): string {
		switch (node.kind) {
			case 'scope':
				return `scope[${node.scope_kind}] #${node.id}`;
			case 'relation':
				return `relation ${node.op}`;
			case 'indicator_constraint':
				return 'indicator-constraint';
			case 'atom':
				return `atom ${node.predicate}`;
		}
	}
	export function children(n: OnionLNode): OnionLNode[] {
		switch (n.kind) {
			case 'scope':
				return n.children;
			case 'relation':
				return n.args;
			case 'indicator_constraint':
				return [n.guard, n.body];
			case 'atom':
				return [];
		}
	}
</script>

<script lang="ts">
	import Self from './AstTree.svelte';
	import { getHighlightedSpan, getPulseToken, pulseHighlight } from '$lib/stores/highlight.svelte';

	type Props = {
		node: OnionLNode;
		muc: readonly string[];
		depth?: number;
	};
	const { node, muc, depth = 0 }: Props = $props();

	let collapsed = $state(false);

	const spanId: string | null = $derived(
		node.kind === 'atom' ? atomSpanId(node.source_span) : null
	);
	const isMuc: boolean = $derived(spanId !== null && muc.includes(spanId));
	const isPulsing: boolean = $derived(spanId !== null && getHighlightedSpan() === spanId);
	const tooltip: string | null = $derived(
		node.kind === 'atom'
			? `${node.source_span.doc_id} bytes ${node.source_span.start}-${node.source_span.end}`
			: null
	);

	let pulseEl: HTMLSpanElement | undefined = $state(undefined);
	$effect(() => {
		void getPulseToken();
		if (isPulsing && pulseEl !== undefined) {
			pulseEl.classList.remove('cds-pulse');
			void pulseEl.offsetWidth;
			pulseEl.classList.add('cds-pulse');
		}
	});

	const kids = $derived(children(node));
	const hasKids = $derived(kids.length > 0);
</script>

<li
	class="my-0.5 list-none font-mono text-sm"
	style="margin-left: {depth === 0 ? 0 : 1}rem"
	data-testid="ast-node"
	data-kind={node.kind}
	data-span-id={spanId}
	data-muc={isMuc ? 'true' : 'false'}
>
	<span
		bind:this={pulseEl}
		data-testid="ast-node-label"
		class="inline-flex items-center gap-2 rounded px-1.5 py-0.5 ring-1"
		class:bg-rose-100={isMuc}
		class:ring-rose-300={isMuc}
		class:bg-slate-50={!isMuc}
		class:ring-slate-200={!isMuc}
		title={tooltip}
		onclick={() => spanId !== null && pulseHighlight(spanId)}
		role="button"
		tabindex="0"
		onkeydown={(e) => {
			if ((e.key === 'Enter' || e.key === ' ') && spanId !== null) {
				e.preventDefault();
				pulseHighlight(spanId);
			}
		}}
	>
		{#if hasKids}
			<button
				type="button"
				class="text-slate-500 hover:text-slate-800"
				aria-label={collapsed ? 'expand' : 'collapse'}
				aria-expanded={!collapsed}
				onclick={(e) => {
					e.stopPropagation();
					collapsed = !collapsed;
				}}
			>
				{collapsed ? '▸' : '▾'}
			</button>
		{:else}
			<span class="w-3" aria-hidden="true"></span>
		{/if}
		<span class="font-medium text-slate-800">{nodeLabel(node)}</span>
		{#if node.kind === 'atom' && node.terms.length > 0}
			<span class="text-slate-500"
				>({node.terms
					.map((t) => (t.kind === 'variable' ? `?${t.name}` : t.value))
					.join(', ')})</span
			>
		{/if}
	</span>
	{#if hasKids && !collapsed}
		<ul class="border-l border-slate-200 pl-3">
			{#each kids as child, i (i)}
				<Self node={child} {muc} depth={depth + 1} />
			{/each}
		</ul>
	{/if}
</li>

<style>
	:global(.cds-pulse) {
		animation: cds-pulse 0.9s ease-out 1;
	}
	@keyframes cds-pulse {
		0% {
			box-shadow: 0 0 0 0 rgba(244, 63, 94, 0.55);
		}
		70% {
			box-shadow: 0 0 0 0.6rem rgba(244, 63, 94, 0);
		}
		100% {
			box-shadow: 0 0 0 0 rgba(244, 63, 94, 0);
		}
	}
</style>
