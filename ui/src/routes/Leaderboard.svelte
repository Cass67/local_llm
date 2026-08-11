<script lang="ts">
	import { onMount, onDestroy } from "svelte";
	import {
		fetchLeaderboard,
		startBakeoff,
		fetchBakeoffJob,
		fetchBakeoffJobs,
		cancelBakeoff,
	} from "../lib/benchmarkApi";
	import type { LeaderboardRow, BakeoffJob } from "../lib/benchmarkApi";
	import { fetchClusters, fetchModels, fetchAllProfiles } from "../lib/api";
	import type { ClusterInfo, ModelInfo, FamilyProfiles } from "../lib/types";

	const STALE_DAYS = 14;

	type Col = {
		key: string;
		label: string;
		hint: string;
		value: (row: LeaderboardRow) => number | null;
		format: (row: LeaderboardRow) => string;
		// Higher is better for most columns; latency is the exception.
		lowerIsBetter?: boolean;
	};

	const AGENTIC = [
		{ type: "terminal-bench", label: "Term-bench" },
		{ type: "swe-bench", label: "SWE-bench" },
	];

	const COLS: Col[] = [
		{
			key: "best_tps",
			label: "Best tok/s",
			hint: "fastest standard run recorded for this model+profile",
			value: (r) => r.best_tps,
			format: (r) => (r.best_tps == null ? "—" : r.best_tps.toFixed(1)),
		},
		{
			key: "avg_tps",
			label: "Avg tok/s",
			hint: "mean across every standard run",
			value: (r) => r.avg_tps,
			format: (r) => (r.avg_tps == null ? "—" : r.avg_tps.toFixed(1)),
		},
		{
			key: "avg_latency_ms",
			label: "Avg run",
			hint: "whole-request wall time, not TTFT — varies with max_tokens",
			value: (r) => r.avg_latency_ms,
			format: (r) => (r.avg_latency_ms == null ? "—" : `${(r.avg_latency_ms / 1000).toFixed(1)} s`),
			lowerIsBetter: true,
		},
		{
			key: "best_tps_per_watt",
			label: "tok/s/W",
			hint: "throughput per watt of wall draw (PSU, not GPU sensors)",
			value: (r) => r.best_tps_per_watt,
			format: (r) => (r.best_tps_per_watt == null ? "—" : r.best_tps_per_watt.toFixed(3)),
		},
		{
			key: "avg_psu_w",
			label: "Avg W",
			hint: "mean wall draw during runs",
			value: (r) => r.avg_psu_w,
			format: (r) => (r.avg_psu_w == null ? "—" : r.avg_psu_w.toFixed(0)),
			lowerIsBetter: true,
		},
		{
			key: "quality_pass_rate",
			label: "Quality",
			hint: "latest golden-set pass rate, judge score in brackets",
			value: (r) => r.quality_pass_rate,
			format: (r) =>
				r.quality_pass_rate == null
					? "—"
					: `${(r.quality_pass_rate * 100).toFixed(0)}%` +
						(r.quality_judge_mean == null ? "" : ` (${r.quality_judge_mean.toFixed(1)})`),
		},
		...AGENTIC.map(({ type, label }) => ({
			key: type,
			label,
			hint: `latest ${type} score`,
			value: (r: LeaderboardRow) => r.agentic[type]?.rate ?? null,
			format: (r: LeaderboardRow) => {
				const score = r.agentic[type];
				return score ? `${score.resolved}/${score.total}` : "—";
			},
		})),
	];

	let rows = $state<LeaderboardRow[]>([]);
	let error = $state("");
	let loading = $state(true);
	let sortKey = $state("best_tps");
	let sortAsc = $state(false);

	async function load() {
		loading = true;
		try {
			rows = (await fetchLeaderboard()).rows;
			error = "";
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
	}

	// --- bake-off ---
	let clusters = $state<ClusterInfo[]>([]);
	let models = $state<ModelInfo[]>([]);
	let families = $state<Record<string, FamilyProfiles>>({});
	let clusterId = $state("");
	let picked = $state<Array<{ family: string; profile: string }>>([]);
	let repeats = $state(3);
	let withQuality = $state(true);
	let job = $state<BakeoffJob | null>(null);
	let bakeoffError = $state("");
	let poll: ReturnType<typeof setInterval> | null = null;

	const selectedCluster = $derived(clusters.find((c) => c.id === clusterId) ?? null);

	const eligible = $derived(
		selectedCluster
			? models.filter(
					(m) =>
						m.backend === selectedCluster.backend ||
						((selectedCluster.backend as string) === "mixed_vulkan" && m.backend === "vulkan"),
				)
			: [],
	);

	function profilesFor(family: string): string[] {
		const entry = families[family];
		if (!entry) return [];
		return Object.keys(entry.profiles ?? {});
	}

	function toggle(family: string) {
		const at = picked.findIndex((p) => p.family === family);
		if (at >= 0) picked = picked.filter((_, i) => i !== at);
		else picked = [...picked, { family, profile: families[family]?.default ?? "" }];
	}

	function setProfile(family: string, profile: string) {
		picked = picked.map((p) => (p.family === family ? { ...p, profile } : p));
	}

	const isPicked = $derived((family: string) => picked.some((p) => p.family === family));

	async function loadBakeoffInputs() {
		try {
			const [c, m, p] = await Promise.all([fetchClusters(), fetchModels(), fetchAllProfiles()]);
			clusters = c.clusters;
			models = m.models;
			families = p.families;
			if (!clusterId && clusters.length) clusterId = clusters[0].id;
			// Reattach to a run already in flight — a bake-off outlives this tab.
			const running = (await fetchBakeoffJobs()).jobs.find((j) => j.status === "running");
			if (running) watch(running.id);
		} catch (e) {
			bakeoffError = e instanceof Error ? e.message : String(e);
		}
	}

	function watch(jobId: string) {
		if (poll) clearInterval(poll);
		poll = setInterval(async () => {
			try {
				job = await fetchBakeoffJob(jobId);
				if (job.status !== "running") {
					if (poll) clearInterval(poll);
					poll = null;
					await load();
				}
			} catch {
				// transient; keep polling
			}
		}, 2000);
	}

	async function runBakeoff() {
		if (!clusterId || picked.length === 0) return;
		bakeoffError = "";
		try {
			const { job_id } = await startBakeoff({
				cluster_id: clusterId,
				entries: picked,
				repeats,
				quality: withQuality,
			});
			job = await fetchBakeoffJob(job_id);
			watch(job_id);
		} catch (e) {
			bakeoffError = e instanceof Error ? e.message : String(e);
		}
	}

	async function stopBakeoff() {
		if (!job) return;
		try {
			await cancelBakeoff(job.id);
		} catch (e) {
			bakeoffError = e instanceof Error ? e.message : String(e);
		}
	}

	onMount(() => {
		load();
		loadBakeoffInputs();
	});

	onDestroy(() => {
		if (poll) clearInterval(poll);
	});

	function sortBy(key: string) {
		if (sortKey === key) sortAsc = !sortAsc;
		else {
			sortKey = key;
			sortAsc = COLS.find((c) => c.key === key)?.lowerIsBetter ?? false;
		}
	}

	const sorted = $derived.by(() => {
		const col = COLS.find((c) => c.key === sortKey);
		if (!col) return rows;
		// Rows with no measurement for the sorted column always sink to the bottom.
		return [...rows].sort((a, b) => {
			const av = col.value(a);
			const bv = col.value(b);
			if (av == null && bv == null) return 0;
			if (av == null) return 1;
			if (bv == null) return -1;
			return sortAsc ? av - bv : bv - av;
		});
	});

	const leaders = $derived.by(() => {
		const best: Record<string, number> = {};
		for (const col of COLS) {
			const values = rows.map(col.value).filter((v): v is number => v != null);
			if (values.length > 1) {
				best[col.key] = col.lowerIsBetter ? Math.min(...values) : Math.max(...values);
			}
		}
		return best;
	});

	function isStale(at: string | null): boolean {
		if (!at) return true;
		const age = Date.now() - new Date(`${at}Z`).getTime();
		return age > STALE_DAYS * 86400_000;
	}

	function ago(at: string | null): string {
		if (!at) return "never";
		const days = Math.floor((Date.now() - new Date(`${at}Z`).getTime()) / 86400_000);
		if (days < 1) return "today";
		return days === 1 ? "1 day ago" : `${days} days ago`;
	}
</script>

<div class="leaderboard">
	<section class="hero">
		<div>
			<p class="eyebrow">Benchmarks</p>
			<h2>Leaderboard</h2>
			<p class="muted">
				One row per model and profile — speed, power, golden-set quality and agentic scores from
				every run already recorded. Bold is the best in that column.
			</p>
		</div>
		<button onclick={load} disabled={loading}>{loading ? "Loading…" : "Refresh"}</button>
	</section>

	{#if error}
		<div class="error">{error}</div>
	{/if}

	<section class="panel">
		<h3>Bake-off</h3>
		<p class="muted">
			Load each model in turn on one cluster, time the same prompt, score the same golden set.
			Every row below comes from runs measured this way, so they are comparable.
		</p>

		{#if bakeoffError}
			<div class="error">{bakeoffError}</div>
		{/if}

		<div class="form-row">
			<select bind:value={clusterId} disabled={job?.status === "running"}>
				{#each clusters as c}
					<option value={c.id}>{c.name} ({c.backend})</option>
				{/each}
			</select>
			<label class="inline">
				Repeats
				<input type="number" min="1" max="10" bind:value={repeats} disabled={job?.status === "running"} />
			</label>
			<label class="inline">
				<input type="checkbox" bind:checked={withQuality} disabled={job?.status === "running"} />
				Score golden set
			</label>
			{#if job?.status === "running"}
				<button class="danger" onclick={stopBakeoff}>Cancel</button>
			{:else}
				<button onclick={runBakeoff} disabled={!clusterId || picked.length === 0}>
					Run {picked.length || ""} {picked.length === 1 ? "model" : "models"}
				</button>
			{/if}
		</div>

		{#if selectedCluster && eligible.length === 0}
			<p class="muted">No installed models match this cluster's {selectedCluster.backend} backend.</p>
		{/if}

		<div class="picker">
			{#each eligible as m}
				<div class="pick" class:on={isPicked(m.family)}>
					<label>
						<input
							type="checkbox"
							checked={isPicked(m.family)}
							disabled={job?.status === "running"}
							onchange={() => toggle(m.family)}
						/>
						{m.label ?? m.model_name ?? m.family}
					</label>
					{#if isPicked(m.family)}
						<select
							value={picked.find((p) => p.family === m.family)?.profile ?? ""}
							disabled={job?.status === "running"}
							onchange={(e) => setProfile(m.family, e.currentTarget.value)}
						>
							<option value="">default</option>
							{#each profilesFor(m.family) as p}
								<option value={p}>{p}</option>
							{/each}
						</select>
					{/if}
				</div>
			{/each}
		</div>

		{#if job}
			<div class="job">
				<div class="job-head">
					<strong>{job.status}</strong>
					<span class="muted">{job.done}/{job.total} done</span>
					{#if job.current}<span class="muted">— {job.current}</span>{/if}
					<span class="muted">{Math.round(job.elapsed_s)}s</span>
				</div>
				<pre>{job.log.join("\n")}</pre>
			</div>
		{/if}
	</section>

	<section class="panel">
		{#if !loading && rows.length === 0}
			<p class="muted">No runs recorded yet. Run a benchmark and it shows up here.</p>
		{:else}
			<div class="scroll">
				<table>
					<thead>
						<tr>
							<th>Model</th>
							<th>Profile</th>
							<th class="num">Runs</th>
							{#each COLS as col}
								<th
									class="num sortable"
									class:sorted={sortKey === col.key}
									title={col.hint}
									onclick={() => sortBy(col.key)}
								>
									{col.label}{sortKey === col.key ? (sortAsc ? " ↑" : " ↓") : ""}
								</th>
							{/each}
							<th>Last run</th>
						</tr>
					</thead>
					<tbody>
						{#each sorted as row (row.model + (row.profile ?? ""))}
							<tr class:stale={isStale(row.last_run)}>
								<td class="model">{row.model}</td>
								<td class="muted-cell">{row.profile ?? "—"}</td>
								<td class="num muted-cell">{row.runs}</td>
								{#each COLS as col}
									<td class="num" class:leader={col.value(row) != null && col.value(row) === leaders[col.key]}>
										{col.format(row)}
									</td>
								{/each}
								<td class="muted-cell" title={row.last_run ?? ""}>{ago(row.last_run)}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
			<p class="muted footnote">
				Greyed rows have not been measured in {STALE_DAYS} days — treat their numbers as history,
				not as the current build.
			</p>
		{/if}
	</section>
</div>

<style>
	.leaderboard { display: flex; flex-direction: column; gap: 1rem; }
	.hero, .panel { background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px; }
	.hero { display: flex; justify-content: space-between; align-items: center; gap: 1rem; padding: 1rem; }
	.panel { padding: 1rem; }
	.eyebrow, .muted { color: var(--text-muted); margin: 0; }
	.eyebrow { font-size: 0.8rem; }
	h2 { margin: 0 0 0.3rem; }
	button { cursor: pointer; background: var(--accent); color: white; border: 1px solid var(--border); border-radius: 8px; padding: 0.55rem; }
	button:disabled { opacity: 0.5; cursor: not-allowed; }
	.error { background: var(--red); color: white; padding: 0.75rem; border-radius: 8px; margin: 0.5rem 0; }
	h3 { margin: 0 0 0.3rem; }
	select, input { border: 1px solid var(--border); background: var(--bg); color: var(--text); border-radius: 8px; padding: 0.45rem; }
	.form-row { display: flex; gap: 0.6rem; flex-wrap: wrap; align-items: center; margin: 0.75rem 0; }
	.inline { display: flex; align-items: center; gap: 0.35rem; color: var(--text-muted); font-size: 0.85rem; }
	.inline input[type="number"] { width: 4.5rem; }
	.danger { background: var(--red); }
	.picker { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 0.4rem; }
	.pick { display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; border: 1px solid var(--border); border-radius: 8px; padding: 0.4rem 0.5rem; font-size: 0.85rem; }
	.pick.on { border-color: var(--accent); }
	.pick label { display: flex; align-items: center; gap: 0.4rem; overflow-wrap: anywhere; }
	.pick select { padding: 0.2rem 0.35rem; font-size: 0.78rem; }
	.job { margin-top: 0.9rem; }
	.job-head { display: flex; gap: 0.6rem; align-items: center; flex-wrap: wrap; margin-bottom: 0.4rem; }
	pre { background: #000; border: 1px solid var(--border); border-radius: 8px; padding: 0.75rem; white-space: pre-wrap; max-height: 16rem; overflow: auto; font-size: 0.75rem; margin: 0; }
	.scroll { overflow-x: auto; }
	table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
	th, td { padding: 0.6rem 0.4rem; border-bottom: 1px solid var(--border); text-align: left; white-space: nowrap; }
	th { color: var(--text-muted); font-weight: normal; }
	th.sortable { cursor: pointer; user-select: none; }
	th.sorted { color: var(--text); }
	.num { text-align: right; }
	.model { overflow-wrap: anywhere; white-space: normal; }
	.muted-cell { color: var(--text-muted); }
	.leader { font-weight: bold; color: var(--accent); }
	tr.stale td { opacity: 0.45; }
	.footnote { font-size: 0.78rem; margin-top: 0.75rem; }
</style>
