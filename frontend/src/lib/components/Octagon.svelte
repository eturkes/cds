<script lang="ts" module>
	import type { Verdict, ClinicalTelemetryPayload } from '$lib/schemas';

	export const CANONICAL_VITALS = [
		'diastolic_mmhg',
		'heart_rate_bpm',
		'respiratory_rate_bpm',
		'spo2_percent',
		'systolic_mmhg',
		'temp_celsius'
	] as const;

	export type CanonicalVital = (typeof CANONICAL_VITALS)[number];

	export type Box = { xLow: number; xHigh: number; yLow: number; yHigh: number };

	export function projectBox(v: Verdict, x: CanonicalVital, y: CanonicalVital): Box | null {
		const bx = v.octagon_bounds[x];
		const by = v.octagon_bounds[y];
		if (bx === undefined || by === undefined) return null;
		if (!Number.isFinite(bx.low) || !Number.isFinite(bx.high)) return null;
		if (!Number.isFinite(by.low) || !Number.isFinite(by.high)) return null;
		return { xLow: bx.low, xHigh: bx.high, yLow: by.low, yHigh: by.high };
	}

	export function presentVitals(v: Verdict): readonly CanonicalVital[] {
		return CANONICAL_VITALS.filter((name) => {
			const b = v.octagon_bounds[name];
			return b !== undefined && Number.isFinite(b.low) && Number.isFinite(b.high) && b.high > b.low;
		});
	}
</script>

<script lang="ts">
	type Props = {
		verdict: Verdict;
		payload: ClinicalTelemetryPayload | null;
	};
	const { verdict, payload }: Props = $props();

	const present = $derived(presentVitals(verdict));

	let xVital: CanonicalVital = $state('heart_rate_bpm');
	let yVital: CanonicalVital = $state('spo2_percent');

	$effect(() => {
		const list = present;
		if (list.length === 0) return;
		const first = list[0]!;
		const second = list[1] ?? first;
		if (!list.includes(xVital)) xVital = first;
		if (!list.includes(yVital)) yVital = second;
	});

	const box = $derived(projectBox(verdict, xVital, yVital));

	const VIEW = { w: 360, h: 240, padL: 56, padR: 16, padT: 18, padB: 36 };

	function pad(span: number): number {
		return span === 0 ? 1 : Math.abs(span) * 0.1;
	}

	const domain = $derived.by(() => {
		if (box === null) return null;
		const xPad = pad(box.xHigh - box.xLow);
		const yPad = pad(box.yHigh - box.yLow);
		return {
			xMin: box.xLow - xPad,
			xMax: box.xHigh + xPad,
			yMin: box.yLow - yPad,
			yMax: box.yHigh + yPad
		};
	});

	function sx(value: number): number {
		if (domain === null) return VIEW.padL;
		const t = (value - domain.xMin) / (domain.xMax - domain.xMin);
		return VIEW.padL + t * (VIEW.w - VIEW.padL - VIEW.padR);
	}

	function sy(value: number): number {
		if (domain === null) return VIEW.h - VIEW.padB;
		const t = (value - domain.yMin) / (domain.yMax - domain.yMin);
		return VIEW.h - VIEW.padB - t * (VIEW.h - VIEW.padT - VIEW.padB);
	}

	const lastSample = $derived(
		payload === null || payload.samples.length === 0
			? null
			: payload.samples[payload.samples.length - 1]!
	);

	const marker = $derived.by(() => {
		if (lastSample === null) return null;
		const xv = lastSample.vitals[xVital];
		const yv = lastSample.vitals[yVital];
		if (xv === undefined || yv === undefined) return null;
		return { x: xv, y: yv };
	});
</script>

<section class="rounded-md border border-slate-200 bg-white p-3" data-testid="octagon-panel">
	<header class="mb-2 flex flex-wrap items-center gap-2">
		<h3 class="text-sm font-semibold text-slate-800">Octagon abstract domain</h3>
		<label class="ml-auto flex items-center gap-1 text-xs text-slate-600">
			x
			<select
				bind:value={xVital}
				class="rounded border border-slate-300 bg-white px-1 py-0.5 text-xs"
				data-testid="octagon-x-select"
			>
				{#each present as v (v)}
					<option value={v}>{v}</option>
				{/each}
			</select>
		</label>
		<label class="flex items-center gap-1 text-xs text-slate-600">
			y
			<select
				bind:value={yVital}
				class="rounded border border-slate-300 bg-white px-1 py-0.5 text-xs"
				data-testid="octagon-y-select"
			>
				{#each present as v (v)}
					<option value={v}>{v}</option>
				{/each}
			</select>
		</label>
	</header>
	{#if box === null || domain === null}
		<p class="text-xs text-slate-500" data-testid="octagon-empty">
			No octagon bounds for this projection.
		</p>
	{:else}
		<svg
			viewBox="0 0 {VIEW.w} {VIEW.h}"
			class="h-auto w-full"
			role="img"
			aria-label="Octagon abstract domain projection"
			data-testid="octagon-svg"
		>
			<rect
				x={sx(box.xLow)}
				y={sy(box.yHigh)}
				width={sx(box.xHigh) - sx(box.xLow)}
				height={sy(box.yLow) - sy(box.yHigh)}
				class="fill-emerald-100 stroke-emerald-500"
				stroke-width="1"
				data-testid="octagon-feasible"
			/>
			<line
				x1={VIEW.padL}
				y1={VIEW.h - VIEW.padB}
				x2={VIEW.w - VIEW.padR}
				y2={VIEW.h - VIEW.padB}
				class="stroke-slate-400"
				stroke-width="1"
			/>
			<line
				x1={VIEW.padL}
				y1={VIEW.padT}
				x2={VIEW.padL}
				y2={VIEW.h - VIEW.padB}
				class="stroke-slate-400"
				stroke-width="1"
			/>
			<text
				x={VIEW.padL + (VIEW.w - VIEW.padL - VIEW.padR) / 2}
				y={VIEW.h - 6}
				text-anchor="middle"
				class="fill-slate-600 text-[10px]"
				font-size="10">{xVital}</text
			>
			<text
				x={12}
				y={VIEW.padT + (VIEW.h - VIEW.padT - VIEW.padB) / 2}
				transform="rotate(-90 12 {VIEW.padT + (VIEW.h - VIEW.padT - VIEW.padB) / 2})"
				text-anchor="middle"
				class="fill-slate-600 text-[10px]"
				font-size="10">{yVital}</text
			>
			<text
				x={sx(box.xLow)}
				y={VIEW.h - VIEW.padB + 12}
				text-anchor="middle"
				class="fill-slate-500"
				font-size="9">{box.xLow.toFixed(1)}</text
			>
			<text
				x={sx(box.xHigh)}
				y={VIEW.h - VIEW.padB + 12}
				text-anchor="middle"
				class="fill-slate-500"
				font-size="9">{box.xHigh.toFixed(1)}</text
			>
			<text
				x={VIEW.padL - 4}
				y={sy(box.yLow) + 3}
				text-anchor="end"
				class="fill-slate-500"
				font-size="9">{box.yLow.toFixed(1)}</text
			>
			<text
				x={VIEW.padL - 4}
				y={sy(box.yHigh) + 3}
				text-anchor="end"
				class="fill-slate-500"
				font-size="9">{box.yHigh.toFixed(1)}</text
			>
			{#if marker !== null}
				<circle
					cx={sx(marker.x)}
					cy={sy(marker.y)}
					r="4"
					class="fill-sky-600"
					data-testid="octagon-marker"
				></circle>
			{/if}
		</svg>
	{/if}
</section>
