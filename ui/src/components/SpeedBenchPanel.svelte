<script lang="ts">
	import { onMount, onDestroy } from "svelte";
	import {
		fetchSpeedBenchCategories,
		fetchSpeedBenchStatus,
		startSpeedBench,
		stopSpeedBench,
	} from "../lib/benchmarkApi";
	import type {
		SpeedBenchCategories,
		SpeedBenchStatus,
		SpeedBenchSummaryRow,
	} from "../lib/benchmarkApi";
	import { fetchClusters } from "../lib/api";
	import type { ClusterInfo } from "../lib/types";

	let cats: SpeedBenchCategories | null = $state(null);
	let status: SpeedBenchStatus | null = $state(null);
	let clusters: ClusterInfo[] = $state([]);
	let clusterId = $state("");
	let perCategory = $state(10);
	let maxTokens = $state(256);
	let picked: Record<string, boolean> = $state({});
	let error = $state("");
	let loading = $state(false);
	let pollId: ReturnType<typeof setInterval> | null = null;

	let loaded = $derived(clusters.filter((c) => c.active));
	let chosen = $derived(Object.keys(picked).filter((name) => picked[name]));
	// Mirrors the backend's own selection: min(per_category, what that domain has).
	let planned = $derived.by(() =>
		(cats?.categories ?? [])
			.filter((c) => chosen.length === 0 || chosen.includes(c.name))
			.reduce((total, c) => total + Math.min(perCategory, c.usable), 0),
	);
	// While a sweep runs the live rows are the truth; when idle, the stored report.
	let table: SpeedBenchSummaryRow[] = $derived.by(() => status?.report?.per_category ?? []);

	async function load() {
		error = "";
		try {
			[cats, status] = await Promise.all([fetchSpeedBenchCategories(), fetchSpeedBenchStatus()]);
			clusters = (await fetchClusters()).clusters;
			if (!clusterId) clusterId = loaded[0]?.id ?? "";
			if (status.running) startPolling();
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : String(e);
		}
	}

	async function poll() {
		try {
			status = await fetchSpeedBenchStatus();
			if (!status.running && pollId) {
				clearInterval(pollId);
				pollId = null;
			}
		} catch {
			// mgmt briefly unreachable mid-sweep; keep polling
		}
	}

	function startPolling() {
		if (!pollId) pollId = setInterval(poll, 3000);
	}

	async function run() {
		loading = true;
		error = "";
		try {
			await startSpeedBench({
				cluster_id: clusterId,
				categories: chosen,
				per_category: perCategory,
				max_tokens: maxTokens,
			});
			await poll();
			startPolling();
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
	}

	async function stop() {
		try {
			await stopSpeedBench();
			await poll();
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : String(e);
		}
	}

	function fmtDate(ts: number): string {
		return new Date(ts * 1000).toLocaleString();
	}

	onMount(load);
	onDestroy(() => {
		if (pollId) clearInterval(pollId);
	});
</script>

<div class="panel">
	<div class="header">
		<h3>SPEED-Bench — spec-decode acceptance by domain</h3>
		<button onclick={load} disabled={status?.running}>Reload</button>
	</div>
	<p class="muted">
		Acceptance measured on code echo says nothing about acceptance on prose or multilingual.
		Prompts come from nvidia/SPEED-Bench and are fetched on demand, never vendored.
	</p>

	{#if error}<div class="error">{error}</div>{/if}

	{#if cats}
		{#if cats.placeholder_total > 0}
			<div class="warn">
				{cats.placeholder_total} of {cats.placeholder_total + cats.usable_total} rows ship as un-hydrated
				placeholders and are skipped — benchmarking them fakes ~100% acceptance. Run NVIDIA's
				<code>prepare.py</code> and set <code>SPEED_BENCH_PROMPTS_JSONL</code> for full coverage.
			</div>
		{/if}

		<div class="controls">
			<label>
				Cluster
				<select bind:value={clusterId} disabled={status?.running}>
					{#each loaded as c}
						<option value={c.id}>{c.name} — {c.active?.family}</option>
					{/each}
					{#if loaded.length === 0}<option value="">no cluster has a model loaded</option>{/if}
				</select>
			</label>
			<label>
				Prompts / category
				<input type="number" min="1" max="80" bind:value={perCategory} disabled={status?.running} />
			</label>
			<label>
				Max tokens
				<input type="number" min="32" max="4096" step="32" bind:value={maxTokens} disabled={status?.running} />
			</label>
			{#if status?.running}
				<button class="stop" onclick={stop}>Stop after this row</button>
			{:else}
				<button class="run" onclick={run} disabled={loading || !clusterId || planned === 0}>
					{loading ? "Starting…" : `Run ${planned} prompts`}
				</button>
			{/if}
		</div>

		<div class="cats">
			{#each cats.categories as c}
				<label class="cat" class:disabled={c.usable === 0}>
					<input
						type="checkbox"
						bind:checked={picked[c.name]}
						disabled={status?.running || c.usable === 0}
					/>
					{c.name}
					<span class="muted">{c.usable}{#if c.placeholders}<span class="dropped"> (−{c.placeholders})</span>{/if}</span>
				</label>
			{/each}
			<span class="muted">none ticked = every domain</span>
		</div>
	{/if}

	{#if status?.running}
		<div class="progress">
			<strong>{status.done}/{status.total}</strong>
			{#if status.current}· {status.current}{/if}
			· {status.cluster_name} · {status.model}
			<div class="bar"><div class="fill" style="width:{status.total ? (100 * status.done) / status.total : 0}%"></div></div>
		</div>
	{/if}

	{#if status?.errors && status.errors.length > 0}
		<details>
			<summary class="behind">{status.errors.length} rows failed</summary>
			<pre>{status.errors.join("\n")}</pre>
		</details>
	{/if}

	{#if table.length > 0 && status?.report}
		<div class="muted">
			{status.report.cluster_name} · {status.report.model} · {fmtDate(status.report.ts)}
			{#if status.report.cancelled}<span class="behind"> · stopped early</span>{/if}
		</div>
		<table>
			<thead><tr><th>Category</th><th>n</th><th>Accept %</th><th>Draft cover %</th><th>tok/s</th></tr></thead>
			<tbody>
				{#each table as row}
					<tr>
						<td>{row.category}</td>
						<td>{row.n}</td>
						<td class="num">{row.accept_pct}</td>
						<td class="num">{row.cover_pct}</td>
						<td class="num">{row.tg_tok_s}</td>
					</tr>
				{/each}
				<tr class="total">
					<td>ALL</td>
					<td>{status.report.overall.n}</td>
					<td class="num">{status.report.overall.accept_pct}</td>
					<td class="num">{status.report.overall.cover_pct}</td>
					<td class="num">{status.report.overall.tg_tok_s}</td>
				</tr>
			</tbody>
		</table>
	{:else if !status?.running}
		<div class="muted">No sweep recorded yet.</div>
	{/if}
</div>

<style>
	.panel { display: flex; flex-direction: column; gap: 0.75rem; background: var(--bg-card); border: 1px solid var(--border); border-radius: 8px; padding: 1rem; }
	.header { display: flex; justify-content: space-between; align-items: center; }
	.header h3 { margin: 0; }
	p { margin: 0; }
	button { padding: 0.3rem 0.6rem; border: 1px solid var(--border); background: var(--bg-card); color: var(--text); border-radius: 4px; cursor: pointer; }
	button:disabled { opacity: 0.5; cursor: default; }
	.run { border-color: #3b82f633; background: #3b82f61a; color: #3b82f6; }
	.stop { border-color: #f59e0b33; background: #f59e0b1a; color: #f59e0b; }
	.controls { display: flex; flex-wrap: wrap; gap: 0.75rem; align-items: flex-end; }
	label { display: flex; flex-direction: column; gap: 0.2rem; font-size: 0.8rem; color: var(--text-muted); }
	select, input { padding: 0.25rem 0.4rem; background: var(--bg); color: var(--text); border: 1px solid var(--border); border-radius: 4px; }
	input[type="number"] { width: 6rem; }
	.cats { display: flex; flex-wrap: wrap; gap: 0.5rem 1rem; align-items: center; font-size: 0.85rem; }
	.cat { flex-direction: row; align-items: center; gap: 0.3rem; color: var(--text); }
	.cat.disabled { opacity: 0.45; }
	.muted { color: var(--text-muted); font-size: 0.8rem; }
	.dropped { color: #f59e0b; }
	.warn { background: #f59e0b1a; border: 1px solid #f59e0b33; border-radius: 4px; padding: 0.5rem; font-size: 0.8rem; }
	.error { background: var(--red); color: white; padding: 0.5rem; border-radius: 4px; }
	.behind { color: #f59e0b; }
	.progress { font-size: 0.85rem; display: flex; flex-direction: column; gap: 0.3rem; }
	.bar { height: 6px; background: var(--bg); border: 1px solid var(--border); border-radius: 3px; overflow: hidden; }
	.fill { height: 100%; background: #3b82f6; transition: width 0.4s; }
	table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
	th, td { padding: 0.35rem 0.4rem; border-bottom: 1px solid var(--border); text-align: left; }
	th { color: var(--text-muted); font-weight: normal; }
	.num { text-align: right; font-variant-numeric: tabular-nums; }
	.total td { font-weight: 600; border-top: 1px solid var(--border); }
	pre { background: #000; border: 1px solid var(--border); border-radius: 4px; padding: 0.5rem; max-height: 160px; overflow: auto; font-size: 0.7rem; margin: 0.3rem 0 0; }
</style>
