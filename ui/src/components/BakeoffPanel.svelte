<script lang="ts">
	import { onMount, onDestroy } from "svelte";
	import { startBakeoff, fetchBakeoffJob, fetchBakeoffJobs, cancelBakeoff } from "../lib/benchmarkApi";
	import type { BakeoffJob } from "../lib/benchmarkApi";
	import { fetchClusters, fetchModels, fetchAllProfiles } from "../lib/api";
	import type { ClusterInfo, ModelInfo, FamilyProfiles } from "../lib/types";

	// Called when a bake-off finishes, so the leaderboard can pick up its rows.
	let { onfinish }: { onfinish?: () => void } = $props();

	let clusters = $state<ClusterInfo[]>([]);
	let models = $state<ModelInfo[]>([]);
	let families = $state<Record<string, FamilyProfiles>>({});
	let clusterId = $state("");
	let picked = $state<Array<{ family: string; profile: string }>>([]);
	let repeats = $state(3);
	let withQuality = $state(true);
	let job = $state<BakeoffJob | null>(null);
	let error = $state("");
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

	async function loadInputs() {
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
			error = e instanceof Error ? e.message : String(e);
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
					onfinish?.();
				}
			} catch {
				// transient; keep polling
			}
		}, 2000);
	}

	async function run() {
		if (!clusterId || picked.length === 0) return;
		error = "";
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
			error = e instanceof Error ? e.message : String(e);
		}
	}

	async function stop() {
		if (!job) return;
		try {
			await cancelBakeoff(job.id);
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
	}

	onMount(loadInputs);
	onDestroy(() => {
		if (poll) clearInterval(poll);
	});
</script>

<section class="panel">
	<h3>Bake-off</h3>
	<p class="muted">
		Load each model in turn on one cluster, time the same prompt, score the same golden set — so the
		leaderboard rows are comparable rather than whatever each model happened to be asked.
	</p>

	{#if error}
		<div class="error">{error}</div>
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
			<button class="danger" onclick={stop}>Cancel</button>
		{:else}
			<button onclick={run} disabled={!clusterId || picked.length === 0}>
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

<style>
	.panel { background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px; padding: 1rem; }
	h3 { margin: 0 0 0.3rem; }
	.muted { color: var(--text-muted); margin: 0; }
	button { cursor: pointer; background: var(--accent); color: white; border: 1px solid var(--border); border-radius: 8px; padding: 0.55rem; }
	button:disabled { opacity: 0.5; cursor: not-allowed; }
	.danger { background: var(--red); }
	.error { background: var(--red); color: white; padding: 0.75rem; border-radius: 8px; margin: 0.5rem 0; }
	select, input { border: 1px solid var(--border); background: var(--bg); color: var(--text); border-radius: 8px; padding: 0.45rem; }
	.form-row { display: flex; gap: 0.6rem; flex-wrap: wrap; align-items: center; margin: 0.75rem 0; }
	.inline { display: flex; align-items: center; gap: 0.35rem; color: var(--text-muted); font-size: 0.85rem; }
	.inline input[type="number"] { width: 4.5rem; }
	.picker { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 0.4rem; }
	.pick { display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; border: 1px solid var(--border); border-radius: 8px; padding: 0.4rem 0.5rem; font-size: 0.85rem; }
	.pick.on { border-color: var(--accent); }
	.pick label { display: flex; align-items: center; gap: 0.4rem; overflow-wrap: anywhere; }
	.pick select { padding: 0.2rem 0.35rem; font-size: 0.78rem; }
	.job { margin-top: 0.9rem; }
	.job-head { display: flex; gap: 0.6rem; align-items: center; flex-wrap: wrap; margin-bottom: 0.4rem; }
	pre { background: #000; border: 1px solid var(--border); border-radius: 8px; padding: 0.75rem; white-space: pre-wrap; max-height: 16rem; overflow: auto; font-size: 0.75rem; margin: 0; }
</style>
