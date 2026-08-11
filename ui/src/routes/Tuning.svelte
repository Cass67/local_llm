<script lang="ts">
	import { onMount, onDestroy } from "svelte";
	import {
		fetchClusters,
		fetchAllProfiles,
		startSweep,
		fetchSweeps,
		fetchSweep,
		cancelSweep,
		promoteSweepResult,
		runQualitySet,
		fetchRegression,
		runRegressionGuard,
		acceptRegressionBaseline,
	} from "../lib/api";
	import type {
		ClusterInfo,
		FamilyProfiles,
		SweepSnapshot,
		SweepListEntry,
		QualityReport,
		RegressionResponse,
	} from "../lib/types";

	// Knobs worth sweeping, with the values that are actually plausible on this
	// hardware — a free-text grid invites typos the linter would only catch later.
	const KNOBS: Array<{ key: string; label: string; values: string[]; hint: string }> = [
		{ key: "ubatch", label: "U-batch (-ub)", values: ["128", "256", "512", "1024"], hint: "physical micro-batch; 512 is usually the sweet spot on RDNA3" },
		{ key: "batch", label: "Batch (-b)", values: ["1024", "2048", "4096", "8192"], hint: "logical batch" },
		{ key: "split_mode", label: "Split mode", values: ["layer", "tensor"], hint: "tensor needs f16 KV + flash attention" },
		{ key: "cache_type_k", label: "Cache type K", values: ["f16", "q8_0"], hint: "quantized KV frees VRAM for context" },
		{ key: "cache_type_v", label: "Cache type V", values: ["f16", "q8_0"], hint: "" },
		{ key: "spec_type", label: "Spec decoding", values: ["ngram-mod", "draft-mtp", "draft-mtp,ngram-mod"], hint: "ngram-mod helps echo/edit; draft-mtp helps novel text" },
		{ key: "ngram_mod_n_max", label: "ngram n_max", values: ["32", "64", "86", "128"], hint: "max drafted tokens per step" },
		{ key: "mtp_draft_n_max", label: "MTP draft depth", values: ["1", "2", "3"], hint: "above 3 degrades on grafted heads" },
		{ key: "parallel", label: "Parallel slots", values: ["1", "2", "4"], hint: "concurrent inference slots" },
		{ key: "flash_attention", label: "Flash attention", values: ["true", "false"], hint: "" },
	];

	const DEFAULT_PROMPT =
		"Write a Python class `LRUCache` with get and put in O(1), using a dict and a " +
		"doubly linked list. Include a short docstring and three assertions.";

	let clusters = $state<ClusterInfo[]>([]);
	let profiles = $state<Record<string, FamilyProfiles>>({});
	let error = $state("");

	// --- sweep form ---
	let clusterId = $state("");
	let baseProfile = $state("");
	let prompt = $state(DEFAULT_PROMPT);
	let objective = $state("decode_tps");
	let repeats = $state(2);
	let warmup = $state(1);
	let maxTokens = $state(256);
	let qualityGate = $state(true);
	let selected = $state<Record<string, Set<string>>>({});

	let sweeps = $state<SweepListEntry[]>([]);
	let current = $state<SweepSnapshot | null>(null);
	let starting = $state(false);
	let promoteName = $state("");
	let poll: ReturnType<typeof setInterval> | null = null;

	const activeCluster = $derived(clusters.find((c) => c.id === clusterId) ?? null);
	const family = $derived(activeCluster?.active?.family ?? activeCluster?.desired?.family ?? "");
	const profileNames = $derived(Object.keys(profiles[family]?.profiles ?? {}).sort());

	// Every combination is a full model reload, so show the cost before committing.
	const comboCount = $derived(
		Object.values(selected).reduce(
			(total, values) => (values.size > 0 ? total * values.size : total),
			1,
		),
	);
	const anySelected = $derived(Object.values(selected).some((v) => v.size > 0));

	function toggleValue(key: string, value: string) {
		const next = new Set(selected[key] ?? []);
		if (next.has(value)) next.delete(value);
		else next.add(value);
		selected = { ...selected, [key]: next };
	}

	function coerce(key: string, raw: string): unknown {
		if (raw === "true") return true;
		if (raw === "false") return false;
		if (/^-?\d+$/.test(raw)) return Number(raw);
		if (/^-?\d*\.\d+$/.test(raw)) return Number(raw);
		return raw;
	}

	function buildGrid(): Record<string, unknown[]> {
		const grid: Record<string, unknown[]> = {};
		for (const [key, values] of Object.entries(selected)) {
			if (values.size > 0) grid[key] = [...values].map((v) => coerce(key, v));
		}
		return grid;
	}

	async function loadBase() {
		try {
			const [clusterData, profileData] = await Promise.all([
				fetchClusters(),
				fetchAllProfiles(),
			]);
			clusters = clusterData.clusters;
			profiles = profileData.families;
			if (!clusterId) {
				const running = clusters.find((c) => c.active?.running);
				clusterId = running?.id ?? clusters[0]?.id ?? "";
			}
			if (!baseProfile) baseProfile = activeCluster?.active?.profile ?? profileNames[0] ?? "";
			sweeps = (await fetchSweeps()).sweeps;
		} catch (e: any) {
			error = e.message;
		}
	}

	async function handleStart() {
		error = "";
		if (!clusterId || !family) {
			error = "pick a cluster that has a model loaded";
			return;
		}
		if (!baseProfile) {
			error = "pick a base profile";
			return;
		}
		if (!anySelected) {
			error = "select at least one value to sweep";
			return;
		}
		starting = true;
		try {
			const { id } = await startSweep({
				family,
				cluster_id: clusterId,
				base_profile: baseProfile,
				grid: buildGrid(),
				prompt_text: prompt,
				max_tokens: maxTokens,
				repeats,
				warmup,
				objective,
				quality_gate: qualityGate,
			});
			await openSweep(id);
			sweeps = (await fetchSweeps()).sweeps;
		} catch (e: any) {
			error = e.message;
		} finally {
			starting = false;
		}
	}

	async function openSweep(id: string) {
		try {
			current = await fetchSweep(id);
			promoteName = `${current.base_profile}-tuned`;
		} catch (e: any) {
			error = e.message;
		}
	}

	async function handleCancel() {
		if (!current) return;
		try {
			await cancelSweep(current.id);
		} catch (e: any) {
			error = e.message;
		}
	}

	async function handlePromote(index?: number) {
		if (!current || !promoteName.trim()) return;
		error = "";
		try {
			const res = await promoteSweepResult(current.id, promoteName.trim(), index);
			profiles = (await fetchAllProfiles()).families;
			error = `saved profile "${res.profile}"`;
		} catch (e: any) {
			error = e.message;
		}
	}

	// --- quality ---
	let quality = $state<QualityReport | null>(null);
	let qualityRunning = $state(false);

	async function handleQuality() {
		if (!clusterId) return;
		qualityRunning = true;
		error = "";
		try {
			quality = await runQualitySet(clusterId);
		} catch (e: any) {
			error = e.message;
		} finally {
			qualityRunning = false;
		}
	}

	// --- regression guard ---
	let regression = $state<RegressionResponse | null>(null);
	let regressionRunning = $state(false);

	async function loadRegression() {
		try {
			regression = await fetchRegression();
		} catch {
			regression = null;
		}
	}

	async function handleRegression() {
		regressionRunning = true;
		error = "";
		try {
			await runRegressionGuard();
			await loadRegression();
		} catch (e: any) {
			error = e.message;
		} finally {
			regressionRunning = false;
		}
	}

	async function handleAcceptBaseline() {
		try {
			await acceptRegressionBaseline();
			await loadRegression();
		} catch (e: any) {
			error = e.message;
		}
	}

	const fmt = (v: number | null | undefined, digits = 1) =>
		v === null || v === undefined ? "—" : v.toFixed(digits);

	function comboLabel(combo: Record<string, unknown>): string {
		return Object.entries(combo)
			.map(([k, v]) => `${k}=${v}`)
			.join("  ");
	}

	onMount(() => {
		loadBase();
		loadRegression();
		// A sweep runs for minutes per combination; poll while one is live.
		poll = setInterval(async () => {
			if (current && (current.status === "running" || current.status === "pending")) {
				current = await fetchSweep(current.id);
			}
		}, 4000);
	});

	onDestroy(() => {
		if (poll) clearInterval(poll);
	});
</script>

<div class="tuning">
	{#if error}<p class="error">{error}</p>{/if}

	<section>
		<div class="section-head">
			<h3>Profile Sweep</h3>
			<span class="muted">
				grid-search llama-server knobs, rank the results, promote the winner
			</span>
		</div>

		<div class="form-row">
			<label>
				Cluster
				<select bind:value={clusterId} onchange={() => (baseProfile = activeCluster?.active?.profile ?? "")}>
					{#each clusters as c}
						<option value={c.id}>
							{c.name}{c.active?.running ? ` — ${c.active.model}` : " (stopped)"}
						</option>
					{/each}
				</select>
			</label>
			<label>
				Base profile
				<select bind:value={baseProfile}>
					{#each profileNames as name}<option value={name}>{name}</option>{/each}
				</select>
			</label>
			<label>
				Objective
				<select bind:value={objective}>
					<option value="decode_tps">decode tok/s</option>
					<option value="prompt_tps">prompt tok/s</option>
					<option value="tps_per_watt">tok/s per watt</option>
				</select>
			</label>
			<label>Repeats <input type="number" min="1" max="10" bind:value={repeats} /></label>
			<label>Warmup <input type="number" min="0" max="3" bind:value={warmup} /></label>
			<label>Max tokens <input type="number" min="16" max="8192" bind:value={maxTokens} /></label>
			<label class="toggle-label" title="Refuse to crown a config that fails the golden prompt set — a faster config that halved its output should not win.">
				<input type="checkbox" bind:checked={qualityGate} />
				Quality gate
			</label>
		</div>

		<label class="prompt-label">
			Benchmark prompt
			<textarea rows="3" bind:value={prompt}></textarea>
		</label>

		<div class="knob-grid">
			{#each KNOBS as knob}
				<div class="knob">
					<div class="knob-head">
						<strong>{knob.label}</strong>
						{#if knob.hint}<span class="muted">{knob.hint}</span>{/if}
					</div>
					<div class="knob-values">
						{#each knob.values as value}
							<button
								class="chip"
								class:on={selected[knob.key]?.has(value)}
								onclick={() => toggleValue(knob.key, value)}
							>
								{value}
							</button>
						{/each}
					</div>
				</div>
			{/each}
		</div>

		<div class="run-row">
			<button class="btn-primary" onclick={handleStart} disabled={starting || !anySelected}>
				{starting ? "Starting…" : "Run sweep"}
			</button>
			{#if anySelected}
				<span class="muted">
					{comboCount} combination{comboCount === 1 ? "" : "s"} — each one is a full model
					reload, so budget a few minutes apiece
				</span>
			{/if}
		</div>
	</section>

	{#if current}
		<section>
			<div class="section-head">
				<h3>Sweep {current.id}</h3>
				<span class="status-pill {current.status}">{current.status}</span>
				<span class="muted">{current.completed} / {current.total}</span>
				{#if current.status === "running" || current.status === "pending"}
					<button onclick={handleCancel}>Cancel</button>
				{/if}
			</div>
			{#if current.error}<p class="error">{current.error}</p>{/if}

			{#if current.best}
				<div class="best">
					<strong>Best:</strong>
					<code>{comboLabel(current.best.combo)}</code>
					<span>{fmt(current.best.decode_tps)} tok/s</span>
					{#if current.best.tps_per_watt}
						<span class="muted">{fmt(current.best.tps_per_watt, 3)} tok/s/W</span>
					{/if}
					<input placeholder="new profile name" bind:value={promoteName} />
					<button class="btn-primary" onclick={() => handlePromote()}>Save as profile</button>
				</div>
			{/if}

			<table>
				<thead>
					<tr>
						<th>Combination</th>
						<th>decode t/s</th>
						<th>prompt t/s</th>
						<th>W</th>
						<th>t/s/W</th>
						<th>quality</th>
						<th>reload</th>
						<th></th>
					</tr>
				</thead>
				<tbody>
					{#each current.results as r}
						<tr
							class:skipped={r.status === "skipped"}
							class:failed={r.status === "error"}
							class:winner={current.best?.index === r.index}
						>
							<td><code>{comboLabel(r.combo)}</code></td>
							<td>{fmt(r.decode_tps)}</td>
							<td>{fmt(r.prompt_tps, 0)}</td>
							<td>{fmt(r.psu_avg_w, 0)}</td>
							<td>{fmt(r.tps_per_watt, 3)}</td>
							<td>
								{#if r.quality}
									<span class:bad={r.quality_gate === "failed"}>
										{r.quality.passed}/{r.quality.total}
									</span>
								{:else}—{/if}
							</td>
							<td>{r.reload_s ? `${r.reload_s}s` : "—"}</td>
							<td class="reason">
								{#if r.status === "skipped"}
									<span title={r.error}>skipped — dead config</span>
								{:else if r.status === "error"}
									<span title={r.error}>failed</span>
								{:else if r.quality_gate === "failed"}
									<span>failed quality gate</span>
								{:else}
									<button onclick={() => handlePromote(r.index)}>Save</button>
								{/if}
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</section>
	{/if}

	{#if sweeps.length > 0}
		<section>
			<h3>Past sweeps</h3>
			<div class="past">
				{#each sweeps as s}
					<button class="past-item" onclick={() => openSweep(s.id)}>
						<code>{s.id}</code>
						<span class="muted">{s.family}</span>
						<span class="status-pill {s.status}">{s.status}</span>
						<span class="muted">{s.completed}/{s.total}</span>
					</button>
				{/each}
			</div>
		</section>
	{/if}

	<section>
		<div class="section-head">
			<h3>Quality Set</h3>
			<span class="muted">
				golden prompts — catches output that got faster by getting worse
			</span>
			<button onclick={handleQuality} disabled={qualityRunning || !clusterId}>
				{qualityRunning ? "Running…" : "Run on cluster"}
			</button>
		</div>

		{#if quality}
			<p>
				<strong>{quality.passed} / {quality.total}</strong> passed
				{#if quality.judge_mean}<span class="muted">· judge mean {quality.judge_mean}</span>{/if}
			</p>
			<table>
				<thead><tr><th>Case</th><th>Words</th><th>Repetition</th><th>Result</th></tr></thead>
				<tbody>
					{#each quality.cases as c}
						<tr class:failed={!c.passed}>
							<td><code>{c.id}</code></td>
							<td>{c.words}</td>
							<td>{(c.repetition_ratio * 100).toFixed(0)}%</td>
							<td>
								{#if c.passed}pass{:else}<span class="bad">{c.failures.join("; ")}</span>{/if}
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		{/if}
	</section>

	<section>
		<div class="section-head">
			<h3>Regression Guard</h3>
			<span class="muted">
				throughput vs last known-good, per cluster+model+profile
			</span>
			<button onclick={handleRegression} disabled={regressionRunning}>
				{regressionRunning ? "Measuring…" : "Run now"}
			</button>
			{#if regression?.report}
				<button onclick={handleAcceptBaseline}>Accept as baseline</button>
			{/if}
		</div>

		{#if regression?.report}
			<p class="muted">
				commit {regression.report.commit ? regression.report.commit.slice(0, 12) : "manual run"}
				· threshold {regression.report.threshold_pct}%
			</p>
			<table>
				<thead>
					<tr><th>Cluster</th><th>Model</th><th>Profile</th><th>tok/s</th><th>Baseline</th><th>Δ</th><th></th></tr>
				</thead>
				<tbody>
					{#each regression.report.clusters as c}
						<tr class:failed={c.verdict === "regressed"}>
							<td>{c.cluster_name}</td>
							<td>{c.family}</td>
							<td>{c.profile}</td>
							<td>{fmt(c.decode_tps)}</td>
							<td>{fmt(c.baseline_tps)}</td>
							<td class:bad={c.verdict === "regressed"} class:good={c.verdict === "improved"}>
								{c.delta_pct === null ? "—" : `${c.delta_pct > 0 ? "+" : ""}${c.delta_pct}%`}
							</td>
							<td><span class="status-pill {c.verdict}">{c.verdict}</span></td>
						</tr>
					{/each}
				</tbody>
			</table>
		{:else}
			<p class="muted">
				No measurements yet. The guard runs automatically after a successful runner
				rebuild, or on demand here.
			</p>
		{/if}
	</section>
</div>

<style>
	.tuning { display: flex; flex-direction: column; gap: 1rem; }
	section {
		background: #111827;
		border: 1px solid #263244;
		border-radius: 6px;
		padding: 0.9rem 1rem;
	}
	.section-head {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		flex-wrap: wrap;
		margin-bottom: 0.6rem;
	}
	.section-head h3 { margin: 0; font-size: 1rem; }
	h3 { margin: 0 0 0.6rem; font-size: 1rem; }
	.muted { color: #8b9bb0; font-size: 0.82rem; }
	.error { color: #e57373; margin: 0 0 0.5rem; }
	.bad { color: #e57373; }
	.good { color: #7dc98a; }

	.form-row {
		display: flex;
		flex-wrap: wrap;
		gap: 0.75rem 1rem;
		align-items: flex-end;
		margin-bottom: 0.6rem;
	}
	.form-row label,
	.prompt-label {
		display: flex;
		flex-direction: column;
		gap: 0.2rem;
		font-size: 0.8rem;
		color: #b9c6d6;
	}
	.form-row input[type="number"] { width: 5rem; }
	.toggle-label {
		flex-direction: row !important;
		align-items: center;
		gap: 0.35rem;
	}
	.prompt-label { margin-bottom: 0.75rem; }
	textarea, input, select {
		background: #0b0f14;
		border: 1px solid #263244;
		color: #e5e7eb;
		border-radius: 4px;
		padding: 0.35rem 0.5rem;
		font-family: inherit;
	}
	textarea { resize: vertical; }

	.knob-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(19rem, 1fr));
		gap: 0.6rem;
		margin-bottom: 0.8rem;
	}
	.knob {
		border: 1px solid #1d2735;
		border-radius: 4px;
		padding: 0.5rem 0.6rem;
	}
	.knob-head { display: flex; flex-direction: column; gap: 0.1rem; margin-bottom: 0.4rem; }
	.knob-head strong { font-size: 0.85rem; }
	.knob-values { display: flex; flex-wrap: wrap; gap: 0.3rem; }
	.chip {
		background: #0b0f14;
		border: 1px solid #263244;
		color: #b9c6d6;
		border-radius: 999px;
		padding: 0.15rem 0.6rem;
		font-size: 0.78rem;
		cursor: pointer;
	}
	.chip.on { background: #1d4ed8; border-color: #3b82f6; color: #fff; }

	.run-row { display: flex; align-items: center; gap: 0.75rem; flex-wrap: wrap; }
	.btn-primary {
		background: #1d4ed8;
		border: 1px solid #3b82f6;
		color: #fff;
		border-radius: 4px;
		padding: 0.35rem 0.9rem;
		cursor: pointer;
	}
	.btn-primary:disabled { opacity: 0.5; cursor: default; }
	button {
		background: #16202c;
		border: 1px solid #263244;
		color: #cbd5e1;
		border-radius: 4px;
		padding: 0.3rem 0.7rem;
		cursor: pointer;
	}

	.best {
		display: flex;
		align-items: center;
		gap: 0.6rem;
		flex-wrap: wrap;
		background: #14251b;
		border-left: 3px solid #7dc98a;
		padding: 0.5rem 0.7rem;
		border-radius: 4px;
		margin-bottom: 0.7rem;
	}

	table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
	th, td {
		text-align: left;
		padding: 0.3rem 0.5rem;
		border-bottom: 1px solid #1d2735;
	}
	th { color: #8b9bb0; font-weight: 600; }
	tr.skipped { opacity: 0.55; }
	tr.failed { background: #2b1a1a; }
	tr.winner { background: #14251b; }
	td.reason { color: #8b9bb0; font-size: 0.78rem; }

	.status-pill {
		font-size: 0.7rem;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		padding: 0.1rem 0.45rem;
		border-radius: 999px;
		background: #1d2735;
		color: #b9c6d6;
	}
	.status-pill.running, .status-pill.pending { background: #1e3a5f; color: #93c5fd; }
	.status-pill.done, .status-pill.ok, .status-pill.improved { background: #14351f; color: #7dc98a; }
	.status-pill.error, .status-pill.regressed { background: #3a1c1c; color: #e57373; }
	.status-pill.cancelled, .status-pill.unmeasured { background: #2b2517; color: #e0b155; }

	.past { display: flex; flex-direction: column; gap: 0.3rem; }
	.past-item {
		display: flex;
		gap: 0.6rem;
		align-items: center;
		text-align: left;
		width: 100%;
	}
</style>
