<script lang="ts">
	import type { FormalVerificationTrace, LeanRecheckWire } from '$lib/schemas';

	type Props = {
		trace: FormalVerificationTrace | null;
		recheck: LeanRecheckWire | null;
	};
	const { trace, recheck }: Props = $props();

	const satState = $derived.by(() => {
		if (trace === null) return 'pending' as const;
		return trace.sat ? ('sat' as const) : ('unsat' as const);
	});

	const recheckState = $derived.by(() => {
		if (recheck === null) return 'pending' as const;
		return recheck.ok ? ('ok' as const) : ('error' as const);
	});

	const proofPreview = $derived.by(() => {
		const proof = trace?.alethe_proof ?? null;
		if (proof === null) return null;
		const lines = proof.split('\n');
		const head = lines.slice(0, 50).join('\n');
		const truncated = lines.length > 50;
		return { head, truncated, total: lines.length };
	});
</script>

<section
	class="rounded-md border border-slate-200 bg-white p-3"
	data-testid="verification-trace-panel"
>
	<header class="flex flex-wrap items-center gap-2">
		<h3 class="text-sm font-semibold text-slate-800">Verification trace</h3>
		<span
			data-testid="sat-pill"
			data-state={satState}
			class="rounded-full px-2 py-0.5 text-xs font-semibold ring-1"
			class:bg-emerald-100={satState === 'sat'}
			class:text-emerald-800={satState === 'sat'}
			class:ring-emerald-300={satState === 'sat'}
			class:bg-rose-100={satState === 'unsat'}
			class:text-rose-800={satState === 'unsat'}
			class:ring-rose-300={satState === 'unsat'}
			class:bg-slate-100={satState === 'pending'}
			class:text-slate-700={satState === 'pending'}
			class:ring-slate-300={satState === 'pending'}
		>
			{satState === 'pending' ? '— pending' : satState === 'sat' ? '✓ sat' : '✗ unsat'}
		</span>
		<span
			data-testid="recheck-pill"
			data-state={recheckState}
			class="rounded-full px-2 py-0.5 text-xs font-semibold ring-1"
			class:bg-emerald-100={recheckState === 'ok'}
			class:text-emerald-800={recheckState === 'ok'}
			class:ring-emerald-300={recheckState === 'ok'}
			class:bg-rose-100={recheckState === 'error'}
			class:text-rose-800={recheckState === 'error'}
			class:ring-rose-300={recheckState === 'error'}
			class:bg-slate-100={recheckState === 'pending'}
			class:text-slate-700={recheckState === 'pending'}
			class:ring-slate-300={recheckState === 'pending'}
		>
			{recheckState === 'pending'
				? 'Lean recheck pending'
				: recheckState === 'ok'
					? 'Lean recheck ✓'
					: 'Lean recheck ✗'}
		</span>
		{#if recheck !== null}
			<span class="text-xs text-slate-500" data-testid="recheck-elapsed">
				{recheck.elapsed_ms} ms
			</span>
		{/if}
	</header>
	{#if proofPreview !== null}
		<details class="mt-3" data-testid="alethe-details">
			<summary class="cursor-pointer text-xs font-medium text-slate-700 hover:text-slate-900">
				Alethe proof preview
				{#if proofPreview.truncated}
					<span class="ml-1 text-slate-500">(first 50 of {proofPreview.total} lines)</span>
				{/if}
			</summary>
			<pre
				class="mt-2 max-h-72 overflow-auto rounded bg-slate-900 p-2 font-mono text-[11px] leading-snug text-slate-100"
				data-testid="alethe-pre">{proofPreview.head}</pre>
		</details>
	{:else if trace !== null}
		<p class="mt-2 text-xs text-slate-500" data-testid="alethe-empty">
			No Alethe proof emitted for this run.
		</p>
	{/if}
	{#if recheck !== null && recheck.messages.length > 0}
		<ul class="mt-3 space-y-0.5" data-testid="recheck-messages">
			{#each recheck.messages as msg, i (i)}
				<li
					class="rounded px-2 py-1 text-xs ring-1"
					class:bg-emerald-50={msg.severity === 'info'}
					class:ring-emerald-200={msg.severity === 'info'}
					class:bg-amber-50={msg.severity === 'warning'}
					class:ring-amber-200={msg.severity === 'warning'}
					class:bg-rose-50={msg.severity === 'error'}
					class:ring-rose-200={msg.severity === 'error'}
				>
					<span class="font-semibold">{msg.severity}:</span>
					{msg.body}
				</li>
			{/each}
		</ul>
	{/if}
</section>
