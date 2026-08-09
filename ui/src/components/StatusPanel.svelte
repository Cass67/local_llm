<script lang="ts">
	import { onMount } from "svelte";
	import { fetchStatus, fetchModels, switchModel, fetchStats, fetchStatsHistory, fetchRunnerHealth, cancelDownload, auditModels, cleanupOrphanedModels, fetchGpuStatus } from "../lib/api";
	import type { StatusResponse, ModelInfo, StatsResponse, ChatMetric, RunnerHealth, GpuStatusResponse } from "../lib/types";

	const HISTORY_LIMIT = 30;
	const GPU_POLL_MS = 2500;

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
	let gpuStatus: GpuStatusResponse | null = $state(null);

	async function load() {
		loading = true;
		error = "";
		try {
			const [s, m, runtimeStats, hist, health, gpu] = await Promise.all([
				fetchStatus(),
				fetchModels(),
				fetchStats(),
				fetchStatsHistory(HISTORY_LIMIT),
				fetchRunnerHealth(),
				fetchGpuStatus().catch(() => ({ ts: Date.now() / 1000, runners: [] as any[] })),
			]);
			status = s;
			models = m.models;
			stats = runtimeStats;
			tpsHistory = [...hist.metrics].reverse();
			runnerHealth = health;
			gpuStatus = gpu;
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

	function formatBytes(value: number | null | undefined): string {
		if (value == null) return "-";
		const units = ["B", "KiB", "MiB", "GiB", "TiB"];
		let size = Math.abs(value);
		let unit = units[0];
		for (const u of units) {
			unit = u;
			if (size < 1024 || u === units[units.length - 1]) break;
			size /= 1024;
		}
		return `${size.toFixed(1)} ${unit}`;
	}

	function pct(used: number | null | undefined, total: number | null | undefined): number | null {
		if (used == null || !total) return null;
		return Math.min(100, (used / total) * 100);
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
		// Backend resamples GPU/system every 2s; poll that alone so meters stay live.
		const gpuId = setInterval(async () => {
			try {
				gpuStatus = await fetchGpuStatus();
			} catch {
				/* transient; next tick retries */
			}
		}, GPU_POLL_MS);
		return () => {
			clearInterval(id);
			clearInterval(gpuId);
		};
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


			{#if gpuStatus?.system && gpuStatus.system.mem_total != null}
				{@const sys = gpuStatus.system}
				<h3>System</h3>
				<div class="sys-row">
					<div class="sys-tile">
						<span class="label">CPU{#if sys.cpu_count}<span class="muted"> · {sys.cpu_count} threads</span>{/if}</span>
						<div class="meter-track"><div class="meter" style="--fill: {sys.cpu_percent ?? 0}%"></div></div>
						<strong>{sys.cpu_percent != null ? `${sys.cpu_percent.toFixed(1)}%` : "-"}</strong>
						{#if sys.cpu_cores?.length}
							<div class="cores">
								{#each sys.cpu_cores as core}
									<div class="core" style="--fill: {core}%" title="{core.toFixed(0)}%"></div>
								{/each}
							</div>
						{/if}
					</div>
					<div class="sys-tile">
						<span class="label">Memory</span>
						<div class="meter-track"><div class="meter" style="--fill: {pct(sys.mem_used, sys.mem_total) ?? 0}%"></div></div>
						<strong>{formatBytes(sys.mem_used)} <span class="muted">/ {formatBytes(sys.mem_total)}</span></strong>
						{#if sys.swap_total}
							<span class="muted">swap {formatBytes(sys.swap_used)} / {formatBytes(sys.swap_total)}</span>
						{/if}
					</div>
					<div class="sys-tile">
						<span class="label">Load / Thermals</span>
						<strong>{sys.load?.length ? sys.load.map(l => l.toFixed(2)).join("  ") : "-"}</strong>
						<span class="muted">
							{#if sys.cpu_temp_c != null}CPU {sys.cpu_temp_c.toFixed(0)}°C{/if}
							{#if sys.psu_power_w != null} · PSU {sys.psu_power_w.toFixed(0)}W{/if}
							{#if sys.fan_rpms?.length} · fans {sys.fan_rpms.join("/")} rpm{/if}
						</span>
					</div>
				</div>
			{/if}

			{#if gpuStatus?.devices?.length}
				<h3>GPUs</h3>
				<div class="sys-row">
					{#each gpuStatus.devices as dev}
						<div class="sys-tile gpu-tile">
							<span class="label">{dev.pci_id}</span>
							<div class="meter-track"><div class="meter" style="--fill: {dev.gpu_busy_percent ?? 0}%"></div></div>
							<strong>{dev.gpu_busy_percent != null ? `${dev.gpu_busy_percent}%` : "-"} <span class="muted">busy</span></strong>
							<div class="dev-grid">
								<span class="muted">VRAM</span>
								<span>{formatBytes(dev.vram_used)} / {formatBytes(dev.vram_total)}</span>
								{#if dev.mem_busy_percent != null}
									<span class="muted">Mem bus</span><span>{dev.mem_busy_percent}%</span>
								{/if}
								{#if dev.temp_c != null}
									<span class="muted">Temp</span>
									<span>{dev.temp_c.toFixed(0)}°C{#if dev.junction_temp_c != null} <span class="muted">(junc {dev.junction_temp_c.toFixed(0)}°C)</span>{/if}</span>
								{/if}
								{#if dev.power_w != null}
									<span class="muted">Power</span>
									<span>{dev.power_w.toFixed(0)} W{#if dev.power_cap_w != null} <span class="muted">/ {dev.power_cap_w.toFixed(0)} W</span>{/if}</span>
								{/if}
								{#if dev.fan_rpm != null}
									<span class="muted">Fan</span>
									<span>{dev.fan_rpm} rpm{#if dev.fan_pct != null} <span class="muted">({dev.fan_pct}%)</span>{/if}</span>
								{/if}
								{#if dev.sclk || dev.mclk}
									<span class="muted">Clocks</span>
									<span>{dev.sclk ?? "-"} <span class="muted">core</span> · {dev.mclk ?? "-"} <span class="muted">mem</span></span>
								{/if}
							</div>
						</div>
					{/each}
				</div>
			{/if}

			{#if gpuStatus && !gpuStatus.error && gpuStatus.runners.length > 0}
				<h3>GPU Parallelism</h3>
				<div class="gpu-status">
					{#each gpuStatus.runners as runner}
						<div class="gpu-runner-card">
							<div class="gpu-runner-header">
								<span class="gpu-cluster">{runner.cluster_name}</span>
								<span class="gpu-split-mode">{runner.split_config.split_mode ?? "?"}</span>
								{#if runner.split_config.tensor_split}
									<span class="muted">ts={runner.split_config.tensor_split}</span>
								{/if}
								{#if runner.gpu_count > 1}
									<span class="gpu-aggregate">{runner.aggregate_gpu_equiv?.toFixed(2) ?? "?"} / {runner.gpu_count}.0 GPU-equiv</span>
								{/if}
								{#if runner.verdict}
									<span class:verdict-serialized={runner.verdict.startsWith("serialized")} class:verdict-concurrent={runner.verdict === "concurrent"}>{runner.verdict}</span>
								{/if}
							</div>
							<div class="gpu-row">
								{#each Object.entries(runner.gpus) as [pci, gpu]}
									<div class="gpu-device">
										<span class="gpu-pci">{pci}</span>
										{#if gpu.engine_busy != null}
											<div class="gpu-bar-track">
												<div class:gpu-bar-serialized={runner.verdict.startsWith("serialized")} class="gpu-bar" style="--busy: {Math.min(gpu.engine_busy, 100)}%"></div>
											</div>
											<span class="gpu-busy">{gpu.engine_busy.toFixed(1)}%{gpu.engine_busy < 1 ? " idle" : ""}</span>
										{:else}
											<span class="muted">no drm-engine counters</span>
										{/if}
										<span class="muted gpu-vram">{gpu.vram_human}</span>
									</div>
								{/each}
							</div>
						</div>
					{/each}
				</div>
			{/if}
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

	.sys-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 0.7rem; }
	.sys-tile { background: var(--bg-card); border: 1px solid var(--border); border-radius: 8px; padding: 0.8rem; display: flex; flex-direction: column; gap: 0.35rem; font-size: 0.85rem; }
	.meter-track { height: 8px; background: #000; border-radius: 4px; overflow: hidden; border: 1px solid var(--border); }
	.meter { height: 100%; width: var(--fill, 0%); background: var(--accent); transition: width 0.3s ease; }
	.cores { display: flex; gap: 2px; height: 18px; align-items: flex-end; }
	.core { flex: 1; min-width: 2px; height: max(2px, var(--fill, 0%)); background: var(--accent); border-radius: 1px; transition: height 0.3s ease; }
	.dev-grid { display: grid; grid-template-columns: auto 1fr; gap: 0.15rem 0.6rem; font-size: 0.78rem; }
	.gpu-tile .label { font-family: monospace; }

.gpu-status { display: flex; flex-direction: column; gap: 0.75rem; }
.gpu-runner-card { background: var(--bg-card); border: 1px solid var(--border); border-radius: 8px; padding: 0.75rem; font-size: 0.85rem; }
.gpu-runner-header { display: flex; align-items: center; gap: 0.6rem; flex-wrap: wrap; margin-bottom: 0.5rem; }
.gpu-cluster { font-weight: bold; }
.gpu-split-mode { background: var(--bg); border: 1px solid var(--border); border-radius: 3px; padding: 0.1rem 0.4rem; color: var(--accent); font-size: 0.75rem; }
.gpu-aggregate { color: var(--text-muted); font-size: 0.8rem; }
.verdict-serialized { color: #f59e0b; font-style: italic; font-size: 0.8rem; }
.verdict-concurrent { color: #4caf50; font-size: 0.8rem; }
.gpu-row { display: flex; gap: 0.75rem; flex-wrap: wrap; }
.gpu-device { background: var(--bg); border: 1px solid var(--border); border-radius: 6px; padding: 0.5rem 0.6rem; min-width: 180px; display: flex; flex-direction: column; gap: 0.3rem; }
.gpu-pci { font-size: 0.75rem; color: var(--text-muted); }
.gpu-bar-track { height: 8px; background: #000; border-radius: 4px; overflow: hidden; border: 1px solid var(--border); }
.gpu-bar { height: 100%; background: var(--accent); width: var(--busy, 0%); transition: width 0.3s ease; }
.gpu-bar-serialized { background: #f59e0b; }
.gpu-busy { font-size: 0.8rem; color: var(--text); }
.gpu-vram { font-size: 0.7rem; }

</style>
