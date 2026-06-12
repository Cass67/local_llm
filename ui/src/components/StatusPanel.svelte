<script lang="ts">
	import { onMount } from "svelte";
	import { fetchStatus, fetchModels, switchModel, fetchStats } from "../lib/api";
	import type { StatusResponse, ModelInfo, StatsResponse } from "../lib/types";

	let status: StatusResponse | null = $state(null);
	let models: ModelInfo[] = $state([]);
	let stats: StatsResponse = $state({});
	let loading = $state(true);
	let error = $state("");
	let restarting: string | null = $state(null);

	async function load() {
		loading = true;
		error = "";
		try {
				const [s, m, runtimeStats] = await Promise.all([fetchStatus(), fetchModels(), fetchStats()]);
			status = s;
			models = m.models;
			stats = runtimeStats;
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
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

	onMount(() => {
		load();
		const id = setInterval(load, 10000);
		return () => clearInterval(id);
	});
</script>

<div class="status-panel">
	<div class="toolbar">
		<button onclick={load} disabled={loading}>{loading ? "Loading..." : "Refresh"}</button>
	</div>

	{#if error}
		<div class="error">{error}</div>
	{/if}

	{#if status}
		<div class="cards">
			<div class="status-card"><span>Target</span><strong>{status.target}</strong></div>
			<div class="status-card"><span>Running</span><strong>{status.running.family || status.running.status}</strong></div>
			<div class="status-card"><span>Context</span><strong>{status.running.ctx ? status.running.ctx.toLocaleString() : "-"}</strong></div>
			<div class="status-card"><span>Accepted</span><strong>{status.accepted_count}</strong></div>
			<div class="status-card"><span>Default</span><strong>{status.default_set ? "yes" : "no"}</strong></div>
			<div class="status-card"><span>Tok/s</span><strong>{stats.predicted_per_second ? stats.predicted_per_second.toFixed(1) : "-"}</strong></div>
			<div class="status-card"><span>Prompt tok/s</span><strong>{stats.prompt_per_second ? stats.prompt_per_second.toFixed(1) : "-"}</strong></div>
			<div class="status-card"><span>Draft accepted</span><strong>{stats.draft_n_accepted ?? "-"}/{stats.draft_n ?? "-"}</strong></div>
		</div>

		<h3>Models</h3>
		<table>
			<thead><tr><th>Run</th><th>Family</th><th>Alias</th><th>Profile</th><th>Backend</th><th>Ctx</th><th>Action</th></tr></thead>
			<tbody>
				{#each models as model}
					<tr class:active={status.running.family === model.family}>
						<td>{status.running.family === model.family ? "▶" : ""}</td>
						<td>{model.family}</td>
						<td>{model.alias}</td>
						<td>{model.profile}</td>
						<td>{model.backend}</td>
						<td>{model.context ? model.context.toLocaleString() : "-"}</td>
						<td><button onclick={() => restart(model)} disabled={restarting === model.family}>{restarting === model.family ? "Launching..." : "Launch"}</button></td>
					</tr>
				{/each}
			</tbody>
		</table>

		<h3>Active Downloads</h3>
		<table>
			<thead><tr><th>PID</th><th>Repo</th></tr></thead>
			<tbody>
				{#if status.downloads.length === 0}
					<tr><td colspan="2">none</td></tr>
				{:else}
					{#each status.downloads as dl}
						<tr><td>{dl.pid}</td><td>{dl.repo}</td></tr>
					{/each}
				{/if}
			</tbody>
		</table>
	{/if}
</div>

<style>
	.status-panel { display: flex; flex-direction: column; gap: 1rem; }
	.toolbar { display: flex; justify-content: flex-end; }
	button { padding: 0.3rem 0.6rem; border: 1px solid var(--border); background: var(--bg-card); color: var(--text); border-radius: 4px; cursor: pointer; }
	.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 0.7rem; }
	.status-card { background: var(--bg-card); border: 1px solid var(--border); border-radius: 8px; padding: 0.8rem; display: flex; flex-direction: column; gap: 0.2rem; }
	.status-card span { color: var(--text-muted); font-size: 0.8rem; }
	table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
	th, td { padding: 0.4rem; border-bottom: 1px solid var(--border); text-align: left; }
	th { color: var(--text-muted); }
	tr.active { background: #4caf501a; }
	.error { background: var(--red); color: white; padding: 0.5rem; border-radius: 4px; }
</style>
