<script lang="ts">
	import { onMount } from "svelte";
	import { fetchStatus, fetchModels, switchModel, fetchStats, fetchStatsHistory, fetchRunnerHealth, cancelDownload, auditModels, cleanupOrphanedModels } from "../lib/api";
	import type { StatusResponse, ModelInfo, StatsResponse, ChatMetric, RunnerHealth } from "../lib/types";

	const HISTORY_LIMIT = 30;

	let status: StatusResponse | null = $state(null);
	let models: ModelInfo[] = $state([]);
	let stats: StatsResponse = $state({});
	let tpsHistory: ChatMetric[] = $state([]);
	let runnerHealth: RunnerHealth = $state({});
	let loading = $state(true);
	let error = $state("");
	let restarting: string | null = $state(null);
	let auditResult = $state<{ orphaned: Array<{ family: string; label: string | null; model_name: string }>; total: number } | null>(null);
	let auditing = $state(false);
	let cleaning = $state(false);

	async function load() {
		loading = true;
		error = "";
		try {
			const [s, m, runtimeStats, hist, health] = await Promise.all([
				fetchStatus(),
				fetchModels(),
				fetchStats(),
				fetchStatsHistory(HISTORY_LIMIT),
				fetchRunnerHealth(),
			]);
			status = s;
			models = m.models;
			stats = runtimeStats;
			tpsHistory = [...hist.metrics].reverse();
			runnerHealth = health;
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
	}

	function sparklinePoints(metrics: ChatMetric[]): string {
		const vals = metrics
			.map((m) => m.predicted_per_second)
			.filter((v): v is number => v != null && !Number.isNaN(v));
		if (vals.length < 2) return "";
		const min = Math.min(...vals);
		const max = Math.max(...vals);
		const spread = Math.max(max - min, 0.1);
		return vals
			.map((v, i) => {
				const x = (i / (vals.length - 1)) * 100;
				const y = 90 - ((v - min) / spread) * 80;
				return `${x.toFixed(1)},${y.toFixed(1)}`;
			})
			.join(" ");
	}

	function statsAge(ts: number): string {
		const secs = Math.round(Date.now() / 1000 - ts);
		if (secs < 60) return `${secs}s ago`;
		if (secs < 3600) return `${Math.round(secs / 60)}m ago`;
		return `${Math.round(secs / 3600)}h ago`;
	}

	async function restart(model: ModelInfo) {
		restarting = model.family;
		error = "";
		try {
			await switchModel({ family: model.family, profile: model.profile, backend: model.backend });
			await load();
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			restarting = null;
		}
	}

	async function handleAudit() {
		auditing = true;
		auditResult = null;
		try {
			auditResult = await auditModels();
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			auditing = false;
		}
	}

	async function handleCleanup() {
		cleaning = true;
		try {
			await cleanupOrphanedModels();
			auditResult = null;
			await load();
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			cleaning = false;
		}
	}

	onMount(() => {
		load();
		const id = setInterval(load, 10000);
		return () => clearInterval(id);
	});
</script>

<div class="status-panel">
	<div class="toolbar">
		<button onclick={handleAudit} class="audit" disabled={auditing}>{auditing ? "Scanning…" : "Audit"}</button>
		<button onclick={load} disabled={loading}>{loading ? "Loading..." : "Refresh"}</button>
	</div>

	{#if auditResult}
		<div class="audit-panel">
			{#if auditResult.orphaned.length === 0}
				<span class="audit-clean">✓ All {auditResult.total} registered models have files on disk.</span>
				<button onclick={() => auditResult = null}>✕</button>
			{:else}
				<div class="audit-header">
					<span class="audit-warn">{auditResult.orphaned.length} of {auditResult.total} registrations missing from cache:</span>
					<button class="btn-cleanup" onclick={handleCleanup} disabled={cleaning}>
						{cleaning ? "Removing…" : `Remove ${auditResult.orphaned.length}`}
					</button>
					<button onclick={() => auditResult = null}>✕</button>
				</div>
				<div class="audit-list">
					{#each auditResult.orphaned as m}
						<span class="audit-chip">{m.label ?? m.model_name ?? m.family}</span>
					{/each}
				</div>
			{/if}
		</div>
	{/if}

	{#if error}
		<div class="error">{error}</div>
	{/if}

	{#if status}
		<div class="cards">
			<div class="status-card"><span>Target</span><strong>{status.target}</strong></div>
			{#if (status.running_clusters ?? []).length === 0}
				<div class="status-card"><span>Running</span><strong class="muted">none</strong></div>
			{:else}
				{#each (status.running_clusters ?? []) as rc}
					<div class="status-card">
						<span>Running · {rc.cluster_name}</span>
						<strong>{models.find(m => m.family === rc.family)?.label ?? rc.family}</strong>
						{#if rc.profile}<small class="muted"> {rc.profile}</small>{/if}
					</div>
				{/each}
			{/if}
			<div class="status-card"><span>Accepted</span><strong>{status.accepted_count}</strong></div>
			<div class="status-card"><span>Default</span><strong>{status.default_set ? "yes" : "no"}</strong></div>
			<div class="status-card"><span>Tok/s</span><strong>{stats.predicted_per_second ? stats.predicted_per_second.toFixed(1) : "-"}</strong>{#if stats.ts}<small class="stat-age">{statsAge(stats.ts)}</small>{/if}</div>
			<div class="status-card"><span>Prompt tok/s</span><strong>{stats.prompt_per_second ? stats.prompt_per_second.toFixed(1) : "-"}</strong></div>
			<div class="status-card"><span>Draft accepted</span><strong>{stats.draft_n_accepted ?? "-"}/{stats.draft_n ?? "-"}</strong></div>
		</div>

		<h3>Models</h3>
		<table>
			<thead><tr><th>Run</th><th>Family</th><th>Alias</th><th>Profile</th><th>Backend</th><th>Ctx</th><th>Action</th></tr></thead>
			<tbody>
				{#each models as model}
					<tr class:active={(status.running_clusters ?? []).some(rc => rc.family === model.family)}>
						<td>{(status.running_clusters ?? []).some(rc => rc.family === model.family) ? "▶" : ""}</td>
						<td>{model.label ?? model.model_name ?? model.family}</td>
						<td>{model.alias}</td>
						<td>{model.profile}</td>
						<td>{model.backend}</td>
						<td>{model.context ? model.context.toLocaleString() : "-"}</td>
						<td><button onclick={() => restart(model)} disabled={restarting === model.family}>{restarting === model.family ? "Launching..." : "Launch"}</button></td>
					</tr>
				{/each}
			</tbody>
		</table>

		<div class="telemetry">
			<div class="telem-block">
				<span class="label">TPS history ({tpsHistory.filter(m => m.predicted_per_second != null).length} requests)</span>
				{#if sparklinePoints(tpsHistory)}
					<svg class="sparkline" viewBox="0 0 100 100" preserveAspectRatio="none">
						<polyline points={sparklinePoints(tpsHistory)} />
					</svg>
				{:else}
					<div class="spark-empty">no data yet</div>
				{/if}
			</div>
			{#if !runnerHealth.error}
				<div class="telem-block runner-info">
					<span class="label">Runner</span>
					<span class="runner-status">{runnerHealth.status ?? "unknown"}</span>
					{#if runnerHealth.slots_idle != null}
						<span class="muted">idle slots: {runnerHealth.slots_idle} / processing: {runnerHealth.slots_processing ?? 0}</span>
					{/if}
				</div>
			{/if}
		</div>

		<h3>Active Downloads</h3>
		<table>
			<thead><tr><th>PID</th><th>Repo</th><th></th></tr></thead>
			<tbody>
				{#if status.downloads.length === 0}
					<tr><td colspan="2">none</td></tr>
				{:else}
					{#each status.downloads as dl}
						<tr><td>{dl.pid}</td><td>{dl.repo}</td><td><button onclick={() => cancelDownload(dl.repo)}>Cancel</button></td></tr>
					{/each}
				{/if}
			</tbody>
		</table>
	{/if}
</div>

<style>
	.status-panel { display: flex; flex-direction: column; gap: 1rem; }
	.toolbar { display: flex; justify-content: flex-end; gap: 0.5rem; }
	button { padding: 0.3rem 0.6rem; border: 1px solid var(--border); background: var(--bg-card); color: var(--text); border-radius: 4px; cursor: pointer; }
	.audit { border-color: #f59e0b33; background: #f59e0b1a; color: #f59e0b; }
	.audit:hover { background: #f59e0b33; }
	.audit-panel { background: var(--bg-card); border: 1px solid var(--border); border-radius: 8px; padding: 0.75rem 1rem; font-size: 0.85rem; }
	.audit-header { display: flex; align-items: center; gap: 0.75rem; margin-bottom: 0.5rem; flex-wrap: wrap; }
	.audit-warn { color: #f59e0b; font-weight: 500; }
	.audit-clean { color: #4caf50; }
	.audit-list { display: flex; flex-wrap: wrap; gap: 0.4rem; }
	.audit-chip { background: var(--bg); border: 1px solid var(--border); border-radius: 4px; padding: 0.15rem 0.5rem; color: var(--text-muted); font-size: 0.8rem; }
	.btn-cleanup { border-color: #ef444433; background: #ef44441a; color: var(--red); }
	.btn-cleanup:hover { background: #ef444433; }
	.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 0.7rem; }
	.status-card { 
		background: var(--bg-card); 
		border: 1px solid var(--border); 
		border-radius: 8px; 
		padding: 0.8rem; 
		display: flex; 
		flex-direction: column; 
		gap: 0.2rem; 
		transition: border-color 0.1s ease;
	}
	.status-card:hover { border-color: var(--accent); }
	.status-card span { color: var(--text-muted); font-size: 0.8rem; }
	.stat-age { color: var(--text-muted); font-size: 0.7rem; margin-top: 0.1rem; }
	table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
	th, td { padding: 0.6rem 0.4rem; border-bottom: 1px solid var(--border); text-align: left; }
	th { color: var(--text-muted); font-weight: normal; }
	tr.active { background: var(--green11); }
	.error { background: var(--red); color: white; padding: 0.5rem; border-radius: 4px; }
	.telemetry { display: flex; gap: 1rem; flex-wrap: wrap; }
	.telem-block { background: var(--bg-card); border: 1px solid var(--border); border-radius: 8px; padding: 0.75rem; flex: 1; min-width: 200px; display: flex; flex-direction: column; gap: 0.3rem; }
	.label { color: var(--text-muted); font-size: 0.8rem; }
	.sparkline { width: 100%; height: 60px; background: #000; border-radius: 4px; border: 1px solid var(--border); display: block; }
	.sparkline polyline { fill: none; stroke: var(--accent); stroke-width: 2; vector-effect: non-scaling-stroke; }
	.spark-empty { height: 60px; background: #000; border-radius: 4px; border: 1px solid var(--border); display: flex; align-items: center; justify-content: center; color: var(--text-muted); font-size: 0.8rem; }
	.runner-info { justify-content: center; }
	.runner-status { font-size: 1.1rem; font-weight: bold; }
	.muted { color: var(--text-muted); font-size: 0.8rem; }
</style>
