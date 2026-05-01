<script lang="ts">
	import {
		parseClinicalTelemetryPayload,
		parseFormalVerificationTrace,
		parseLeanRecheckWire,
		parseOnionLIRTree,
		parseSmtConstraintMatrix,
		parseVerdict,
		sortVitalsKeys,
		asObject,
		type ClinicalTelemetryPayload,
		type FormalVerificationTrace,
		type LeanRecheckWire,
		type OnionLIRTree,
		type SmtConstraintMatrix,
		type Verdict
	} from '$lib/schemas';
	import AstTree from '$lib/components/AstTree.svelte';
	import Octagon from '$lib/components/Octagon.svelte';
	import MucViewer from '$lib/components/MucViewer.svelte';
	import VerificationTrace from '$lib/components/VerificationTrace.svelte';

	type StageState =
		| { status: 'idle' }
		| { status: 'running' }
		| { status: 'ok' }
		| { status: 'error'; message: string };

	type State = {
		payload: ClinicalTelemetryPayload | null;
		ir: OnionLIRTree | null;
		matrix: SmtConstraintMatrix | null;
		verdict: Verdict | null;
		trace: FormalVerificationTrace | null;
		recheck: LeanRecheckWire | null;
		stages: {
			ingest: StageState;
			translate: StageState;
			deduce: StageState;
			solve: StageState;
			recheck: StageState;
		};
		runId: number;
	};

	const initial: State = {
		payload: null,
		ir: null,
		matrix: null,
		verdict: null,
		trace: null,
		recheck: null,
		stages: {
			ingest: { status: 'idle' },
			translate: { status: 'idle' },
			deduce: { status: 'idle' },
			solve: { status: 'idle' },
			recheck: { status: 'idle' }
		},
		runId: 0
	};

	let s = $state<State>(initial);

	const SAMPLE_TELEMETRY = JSON.stringify(
		{
			schema_version: '0.1.0',
			source: { device_id: 'icu-monitor-02', patient_pseudo_id: 'pseudo-def456' },
			samples: [
				{
					wall_clock_utc: '2026-04-29T13:00:00.000000Z',
					monotonic_ns: 2000000000000,
					vitals: { heart_rate_bpm: 88.0, spo2_percent: 94.0 },
					events: []
				},
				{
					wall_clock_utc: '2026-04-29T13:00:01.000000Z',
					monotonic_ns: 2001000000000,
					vitals: { heart_rate_bpm: 90.0, spo2_percent: 93.5 },
					events: []
				}
			]
		},
		null,
		2
	);

	const SAMPLE_GUIDELINE = `SpO2 above 95.\nSpO2 below 90.\n`;

	const SAMPLE_RECORDED = JSON.stringify(
		{
			schema_version: '0.1.0',
			root: {
				kind: 'scope',
				id: 'contradictory-bound',
				scope_kind: 'guideline',
				children: [
					{
						kind: 'relation',
						op: 'greater_than',
						args: [
							{
								kind: 'atom',
								predicate: 'spo2',
								terms: [],
								source_span: { start: 0, end: 4, doc_id: 'contradictory-bound' }
							},
							{
								kind: 'atom',
								predicate: 'literal',
								terms: [{ kind: 'constant', value: '95.0' }],
								source_span: { start: 11, end: 13, doc_id: 'contradictory-bound' }
							}
						]
					},
					{
						kind: 'relation',
						op: 'less_than',
						args: [
							{
								kind: 'atom',
								predicate: 'spo2',
								terms: [],
								source_span: { start: 15, end: 19, doc_id: 'contradictory-bound' }
							},
							{
								kind: 'atom',
								predicate: 'literal',
								terms: [{ kind: 'constant', value: '90.0' }],
								source_span: { start: 26, end: 28, doc_id: 'contradictory-bound' }
							}
						]
					}
				]
			}
		},
		null,
		2
	);

	let docId = $state('contradictory-bound');
	let telemetryText = $state(SAMPLE_TELEMETRY);
	let guidelineText = $state(SAMPLE_GUIDELINE);
	let recordedText = $state(SAMPLE_RECORDED);

	const isRunning = $derived(
		s.stages.ingest.status === 'running' ||
			s.stages.translate.status === 'running' ||
			s.stages.deduce.status === 'running' ||
			s.stages.solve.status === 'running' ||
			s.stages.recheck.status === 'running'
	);

	function reset(): void {
		s = { ...initial, runId: s.runId + 1 };
	}

	async function postJson(path: string, body: unknown): Promise<unknown> {
		const res = await fetch(path, {
			method: 'POST',
			headers: { 'content-type': 'application/json' },
			body: JSON.stringify(body)
		});
		const text = await res.text();
		let decoded: unknown = null;
		try {
			decoded = JSON.parse(text);
		} catch {
			// non-JSON body — fall back to raw text in the error path below.
		}
		if (!res.ok) {
			let detail = text;
			if (decoded !== null && typeof decoded === 'object' && 'detail' in decoded) {
				const d = (decoded as Record<string, unknown>).detail;
				if (typeof d === 'string') detail = d;
			}
			throw new Error(`${path}: HTTP ${res.status} ${detail}`);
		}
		return decoded;
	}

	async function runStage<T>(
		stage: keyof State['stages'],
		fn: () => Promise<T>,
		assign: (value: T) => void
	): Promise<boolean> {
		s.stages[stage] = { status: 'running' };
		try {
			const value = await fn();
			assign(value);
			s.stages[stage] = { status: 'ok' };
			return true;
		} catch (e) {
			s.stages[stage] = { status: 'error', message: e instanceof Error ? e.message : String(e) };
			return false;
		}
	}

	async function runPipeline(): Promise<void> {
		reset();
		let envelope: unknown;
		let recordedRoot: unknown;
		try {
			envelope = JSON.parse(telemetryText);
			const recordedDoc = JSON.parse(recordedText);
			const obj = asObject(recordedDoc, 'recorded');
			recordedRoot = obj.root;
		} catch (e) {
			s.stages.ingest = {
				status: 'error',
				message: `input parse failed: ${e instanceof Error ? e.message : String(e)}`
			};
			return;
		}
		const ingested = await runStage(
			'ingest',
			async () => {
				const raw = await postJson('/api/ingest', { format: 'json', envelope });
				return sortVitalsKeys(parseClinicalTelemetryPayload(raw));
			},
			(value) => (s.payload = value)
		);
		if (!ingested || s.payload === null) return;
		const translated = await runStage(
			'translate',
			async () => {
				const raw = await postJson('/api/translate', {
					doc_id: docId,
					text: guidelineText,
					root: recordedRoot,
					logic: 'QF_LRA'
				});
				const o = asObject(raw, 'TranslateResponse');
				return {
					ir: parseOnionLIRTree(o.ir),
					matrix: parseSmtConstraintMatrix(o.matrix)
				};
			},
			(value) => {
				s.ir = value.ir;
				s.matrix = value.matrix;
			}
		);
		if (!translated || s.matrix === null) return;
		await runStage(
			'deduce',
			async () => {
				const raw = await postJson('/api/deduce', { payload: s.payload });
				return parseVerdict(raw);
			},
			(value) => (s.verdict = value)
		);
		const solved = await runStage(
			'solve',
			async () => {
				const raw = await postJson('/api/solve', { matrix: s.matrix });
				return parseFormalVerificationTrace(raw);
			},
			(value) => (s.trace = value)
		);
		if (!solved || s.trace === null) return;
		await runStage(
			'recheck',
			async () => {
				const raw = await postJson('/api/recheck', {
					trace: s.trace,
					options: { custom_id: 'cds-ui-pipeline' }
				});
				return parseLeanRecheckWire(raw);
			},
			(value) => (s.recheck = value)
		);
	}

	function stageBadge(state: StageState): { label: string; cls: string } {
		switch (state.status) {
			case 'idle':
				return { label: '—', cls: 'bg-slate-100 text-slate-600 ring-slate-300' };
			case 'running':
				return { label: '…', cls: 'bg-sky-100 text-sky-700 ring-sky-300' };
			case 'ok':
				return { label: '✓', cls: 'bg-emerald-100 text-emerald-700 ring-emerald-300' };
			case 'error':
				return { label: '✗', cls: 'bg-rose-100 text-rose-700 ring-rose-300' };
		}
	}

	const stageOrder: Array<keyof State['stages']> = [
		'ingest',
		'translate',
		'deduce',
		'solve',
		'recheck'
	];
</script>

<main class="mx-auto w-full max-w-7xl space-y-4 px-4 py-6">
	<header class="flex flex-wrap items-baseline justify-between gap-2">
		<div>
			<p class="text-xs tracking-widest text-slate-500 uppercase">Phase 0 — Neurosymbolic CDS</p>
			<h1 class="text-2xl font-semibold text-slate-900">Pipeline visualizer</h1>
		</div>
		<p class="max-w-prose text-xs text-slate-500">
			Drives <code>/api/ingest → translate → deduce → solve → recheck</code> in sequence through the Phase
			0 BFF (ADR-022 §3 + §4). Each stage's verdict surfaces immediately; AST nodes whose source-spans
			land in the MUC are highlighted rose, with cross-component pulse on click.
		</p>
	</header>

	<section class="rounded-md border border-slate-200 bg-white p-4 shadow-sm" data-testid="form">
		<div class="grid grid-cols-1 gap-3 lg:grid-cols-3">
			<label class="flex flex-col gap-1 text-xs text-slate-700">
				<span class="font-semibold">doc_id</span>
				<input
					type="text"
					bind:value={docId}
					data-testid="doc-id-input"
					class="rounded border border-slate-300 px-2 py-1 font-mono text-xs"
				/>
			</label>
			<label class="flex flex-col gap-1 text-xs text-slate-700 lg:col-span-2">
				<span class="font-semibold">Guideline text</span>
				<textarea
					bind:value={guidelineText}
					rows="3"
					data-testid="guideline-input"
					class="rounded border border-slate-300 px-2 py-1 font-mono text-xs"
				></textarea>
			</label>
			<label class="flex flex-col gap-1 text-xs text-slate-700 lg:col-span-2">
				<span class="font-semibold">Telemetry envelope (JSON)</span>
				<textarea
					bind:value={telemetryText}
					rows="10"
					data-testid="telemetry-input"
					class="rounded border border-slate-300 px-2 py-1 font-mono text-xs"
				></textarea>
			</label>
			<label class="flex flex-col gap-1 text-xs text-slate-700">
				<span class="font-semibold">Pre-formalised OnionL root (JSON)</span>
				<textarea
					bind:value={recordedText}
					rows="10"
					data-testid="recorded-input"
					class="rounded border border-slate-300 px-2 py-1 font-mono text-xs"
				></textarea>
			</label>
		</div>
		<div class="mt-3 flex items-center gap-2">
			<button
				type="button"
				onclick={runPipeline}
				disabled={isRunning}
				data-testid="run-button"
				class="rounded bg-slate-900 px-3 py-1.5 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
			>
				{isRunning ? 'Running…' : 'Run pipeline'}
			</button>
			<ul class="flex flex-wrap items-center gap-2" data-testid="stage-badges">
				{#each stageOrder as stage (stage)}
					{@const b = stageBadge(s.stages[stage])}
					<li
						class="flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] ring-1 {b.cls}"
						data-testid="stage-badge-{stage}"
						data-status={s.stages[stage].status}
					>
						<span class="font-mono">{b.label}</span>
						<span class="font-medium">{stage}</span>
					</li>
				{/each}
			</ul>
		</div>
		{#each stageOrder as stage (stage)}
			{#if s.stages[stage].status === 'error'}
				<p
					class="mt-2 rounded bg-rose-50 px-2 py-1 text-xs text-rose-800 ring-1 ring-rose-200"
					data-testid="stage-error-{stage}"
				>
					<span class="font-semibold">{stage}:</span>
					{(s.stages[stage] as { status: 'error'; message: string }).message}
				</p>
			{/if}
		{/each}
	</section>

	<VerificationTrace trace={s.trace} recheck={s.recheck} />

	<div class="grid grid-cols-1 gap-4 lg:grid-cols-2">
		<section class="rounded-md border border-slate-200 bg-white p-3" data-testid="ast-panel">
			<header class="mb-2 flex items-baseline justify-between">
				<h3 class="text-sm font-semibold text-slate-800">OnionL IR tree</h3>
				{#if s.ir !== null}
					<span class="text-xs text-slate-500">schema {s.ir.schema_version}</span>
				{/if}
			</header>
			{#if s.ir === null}
				<p class="text-xs text-slate-500" data-testid="ast-empty">
					Run the pipeline to render the OnionL tree.
				</p>
			{:else}
				<ul class="overflow-x-auto">
					<AstTree node={s.ir.root} muc={s.trace?.muc ?? []} />
				</ul>
			{/if}
		</section>
		{#if s.verdict !== null}
			<Octagon verdict={s.verdict} payload={s.payload} />
		{:else}
			<section
				class="rounded-md border border-slate-200 bg-white p-3"
				data-testid="octagon-panel-empty"
			>
				<h3 class="mb-2 text-sm font-semibold text-slate-800">Octagon abstract domain</h3>
				<p class="text-xs text-slate-500">Run the pipeline to render the Octagon projection.</p>
			</section>
		{/if}
	</div>

	<MucViewer muc={s.trace?.muc ?? []} />
</main>
