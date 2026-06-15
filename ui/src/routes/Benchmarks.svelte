<script lang="ts">
	import { onMount } from "svelte";
	import {
		createBenchmarkEndpoint,
		createBenchmarkPrompt,
		deleteBenchmarkEndpoint,
		deleteBenchmarkPrompt,
		fetchBenchmarkSummary,
		listBenchmarkEndpoints,
		listBenchmarkPrompts,
		listBenchmarkRuns,
		loadBenchmarkModels,
		runBenchmark,
	} from "../lib/benchmarkApi";
	import { formatMs, formatThroughput, runDelta } from "../lib/benchmarkMetrics";
	import type { BenchmarkEndpoint, BenchmarkPrompt, BenchmarkRun, BenchmarkSummary } from "../lib/benchmarkApi";

	let endpoints: BenchmarkEndpoint[] = $state([]);
	let prompts: BenchmarkPrompt[] = $state([]);
	let runs: BenchmarkRun[] = $state([]);
	let summary: BenchmarkSummary | null = $state(null);
	let models: string[] = $state([]);
	let latest: BenchmarkRun | null = $state(null);
	let selectedRun: BenchmarkRun | null = $state(null);
	let loading = $state(false);
	let running = $state(false);
	let error = $state("");

	let endpointName = $state("");
	let endpointUrl = $state("");
	let endpointKey = $state("");
	let promptName = $state("");
	let promptText = $state("Write a concise Python function that reverses a string and explain it.");
	let selectedEndpointId = $state("");
	let selectedPromptId = $state("");
	let selectedModel = $state("");
	let maxTokens = $state(256);
	let temperature = $state(0.2);
	let filterEndpointId = $state("");
	let filterPromptId = $state("");
	let filterModel = $state("");
	let filterStatus = $state("");
	let filterFrom = $state("");
	let filterTo = $state("");

	function selectedEndpoint(): BenchmarkEndpoint | undefined {
		return endpoints.find((endpoint) => String(endpoint.id) === selectedEndpointId);
	}

	function selectedPrompt(): BenchmarkPrompt | undefined {
		return prompts.find((prompt) => String(prompt.id) === selectedPromptId);
	}

	function sameRunBaseline(run: BenchmarkRun | null): BenchmarkRun[] {
		if (!run) return [];
		return runs.filter(
			(item) =>
				item.id !== run.id &&
				item.endpoint_name === run.endpoint_name &&
				item.model === run.model &&
				(item.prompt_name || item.prompt_text) === (run.prompt_name || run.prompt_text) &&
				item.status === "ok",
		);
	}

	function avg(values: Array<number | null>): number | null {
		const clean = values.filter((value): value is number => value != null && !Number.isNaN(value));
		if (clean.length === 0) return null;
		return clean.reduce((sum, value) => sum + value, 0) / clean.length;
	}

	function avgLatencyFor(run: BenchmarkRun | null): number | null {
		return avg(sameRunBaseline(run).map((item) => item.latency_ms));
	}

	function avgThroughputFor(run: BenchmarkRun | null): number | null {
		return avg(sameRunBaseline(run).map((item) => item.throughput_tps));
	}

	function trendPoints(field: "latency_ms" | "throughput_tps"): string {
		const values = (summary?.trends || [])
			.map((run) => run[field])
			.filter((value): value is number => value != null && !Number.isNaN(value));
		if (values.length === 0) return "";
		const min = Math.min(...values);
		const max = Math.max(...values);
		const spread = Math.max(max - min, 1);
		return values
			.map((value, index) => {
				const x = values.length === 1 ? 100 : (index / (values.length - 1)) * 100;
				const y = 90 - ((value - min) / spread) * 80;
				return `${x},${y}`;
			})
			.join(" ");
	}

	async function loadAll() {
		loading = true;
		error = "";
		try {
			const [endpointResult, promptResult, runResult, summaryResult] = await Promise.all([
				listBenchmarkEndpoints(),
				listBenchmarkPrompts(),
				listBenchmarkRuns({ limit: 100 }),
				fetchBenchmarkSummary(),
			]);
			endpoints = endpointResult.endpoints;
			prompts = promptResult.prompts;
			runs = runResult.runs;
			summary = summaryResult;
			if (!selectedEndpointId && endpoints[0]) selectedEndpointId = String(endpoints[0].id);
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
	}

	async function saveEndpoint() {
		error = "";
		const created = await createBenchmarkEndpoint({
			name: endpointName,
			base_url: endpointUrl,
			api_key: endpointKey || undefined,
		});
		endpointName = "";
		endpointUrl = "";
		endpointKey = "";
		selectedEndpointId = String(created.id);
		await loadAll();
	}

	async function savePrompt() {
		error = "";
		const created = await createBenchmarkPrompt({ name: promptName, text: promptText });
		promptName = "";
		selectedPromptId = String(created.id);
		await loadAll();
	}

	async function loadModels() {
		if (!selectedEndpointId) return;
		error = "";
		models = (await loadBenchmarkModels(Number(selectedEndpointId))).models;
		selectedModel = models[0] || "";
	}

	async function applyFilters() {
		const result = await listBenchmarkRuns({
			endpoint_id: filterEndpointId ? Number(filterEndpointId) : "",
			model: filterModel,
			prompt_id: filterPromptId ? Number(filterPromptId) : "",
			status: filterStatus,
			from_date: filterFrom,
			to_date: filterTo,
			limit: 100,
		});
		runs = result.runs;
	}

	async function executeRun() {
		if (!selectedEndpointId || !selectedModel || !promptText) return;
		running = true;
		error = "";
		try {
			const prompt = selectedPrompt();
			latest = await runBenchmark({
				endpoint_id: Number(selectedEndpointId),
				model: selectedModel,
				prompt_id: prompt?.id ?? null,
				prompt_name: prompt?.name ?? null,
				prompt_text: prompt?.text || promptText,
				max_tokens: maxTokens,
				temperature,
			});
			selectedRun = latest;
			await loadAll();
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			running = false;
		}
	}

	onMount(loadAll);
</script>

<div class="benchmarks">
	<div class="hero">
		<div>
			<p class="eyebrow">Benchmarks</p>
			<h2>LLM performance lab</h2>
			<p>Save llama-swap endpoints, run prompt presets, compare models, and track trends.</p>
		</div>
		<button onclick={loadAll} disabled={loading}>{loading ? "Refreshing..." : "Refresh"}</button>
	</div>

	{#if error}<div class="error">{error}</div>{/if}

	<div class="cards">
		<div class="metric"><span>Total runs</span><strong>{summary?.total_runs ?? 0}</strong></div>
		<div class="metric"><span>Avg latency</span><strong>{formatMs(summary?.avg_latency_ms)}</strong></div>
		<div class="metric"><span>Best throughput</span><strong>{formatThroughput(summary?.best_throughput_tps, null)}</strong></div>
		<div class="metric"><span>Error rate</span><strong>{(((summary?.error_rate ?? 0) * 100).toFixed(1))}%</strong></div>
	</div>

	<div class="grid two">
		<section class="panel">
			<h3>Endpoints</h3>
			<div class="form-row">
				<input bind:value={endpointName} placeholder="Name" />
				<input bind:value={endpointUrl} placeholder="http://host:port/v1" />
				<input bind:value={endpointKey} placeholder="API key (optional)" type="password" />
				<button onclick={saveEndpoint} disabled={!endpointName || !endpointUrl}>Save</button>
			</div>
			<div class="list">
				{#each endpoints as endpoint}
					<div class="list-item" class:active={selectedEndpointId === String(endpoint.id)}>
						<button class="select" onclick={() => (selectedEndpointId = String(endpoint.id))}>{endpoint.name}</button>
						<span>{endpoint.base_url}</span>
						{#if endpoint.api_key_set}<em>key saved</em>{/if}
						<button class="danger" onclick={async () => { await deleteBenchmarkEndpoint(endpoint.id); await loadAll(); }}>Delete</button>
					</div>
				{/each}
			</div>
		</section>

		<section class="panel">
			<h3>Prompt presets</h3>
			<div class="form-row">
				<input bind:value={promptName} placeholder="Preset name" />
				<button onclick={savePrompt} disabled={!promptName || !promptText}>Save current prompt</button>
			</div>
			<div class="list">
				{#each prompts as prompt}
					<div class="list-item" class:active={selectedPromptId === String(prompt.id)}>
						<button class="select" onclick={() => { selectedPromptId = String(prompt.id); promptText = prompt.text; }}>{prompt.name}</button>
						<span>{prompt.text.slice(0, 90)}</span>
						<button class="danger" onclick={async () => { await deleteBenchmarkPrompt(prompt.id); await loadAll(); }}>Delete</button>
					</div>
				{/each}
			</div>
		</section>
	</div>

	<section class="panel runner">
		<h3>Run benchmark</h3>
		<div class="form-row">
			<select bind:value={selectedEndpointId}>
				<option value="">Endpoint</option>
				{#each endpoints as endpoint}<option value={String(endpoint.id)}>{endpoint.name}</option>{/each}
			</select>
			<button onclick={loadModels} disabled={!selectedEndpointId}>Load models</button>
			<select bind:value={selectedModel}>
				<option value="">Model</option>
				{#each models as model}<option value={model}>{model}</option>{/each}
			</select>
			<input type="number" min="1" max="8192" bind:value={maxTokens} />
			<input type="number" min="0" max="2" step="0.1" bind:value={temperature} />
			<button onclick={executeRun} disabled={running || !selectedEndpointId || !selectedModel}>{running ? "Running..." : "Run"}</button>
		</div>
		<textarea bind:value={promptText} rows="5" placeholder="Benchmark prompt"></textarea>
		<p class="muted">Selected endpoint: {selectedEndpoint()?.name || "none"}</p>
	</section>

	{#if latest}
		<section class="panel result">
			<h3>Latest result</h3>
			<div class="cards compact">
				<div class="metric"><span>Status</span><strong>{latest.status}</strong></div>
				<div class="metric"><span>Latency</span><strong>{formatMs(latest.latency_ms)}</strong></div>
				<div class="metric"><span>Throughput</span><strong>{formatThroughput(latest.throughput_tps, latest.throughput_cps)}</strong></div>
				<div class="metric"><span>Tokens</span><strong>{latest.total_tokens ?? "-"}</strong></div>
			</div>
			<div class="compare">
				<span>vs same benchmark avg latency: {runDelta(latest.latency_ms, avgLatencyFor(latest))}</span>
				<span>vs same benchmark avg throughput: {runDelta(latest.throughput_tps, avgThroughputFor(latest))}</span>
				<span>baseline runs: {sameRunBaseline(latest).length}</span>
			</div>
			<pre>{latest.response_text || latest.error}</pre>
		</section>
	{/if}

	<div class="grid two">
		<section class="panel chart">
			<h3>Latency trend</h3>
			<svg viewBox="0 0 100 100" preserveAspectRatio="none"><polyline points={trendPoints("latency_ms")} /></svg>
		</section>
		<section class="panel chart">
			<h3>Throughput trend</h3>
			<svg viewBox="0 0 100 100" preserveAspectRatio="none"><polyline points={trendPoints("throughput_tps")} /></svg>
		</section>
	</div>

	<section class="panel">
		<h3>History</h3>
		<div class="form-row filters">
			<select bind:value={filterEndpointId}><option value="">All endpoints</option>{#each endpoints as endpoint}<option value={String(endpoint.id)}>{endpoint.name}</option>{/each}</select>
			<input bind:value={filterModel} placeholder="Model" />
			<select bind:value={filterPromptId}><option value="">All prompts</option>{#each prompts as prompt}<option value={String(prompt.id)}>{prompt.name}</option>{/each}</select>
			<select bind:value={filterStatus}><option value="">Any status</option><option value="ok">ok</option><option value="error">error</option></select>
			<input type="date" bind:value={filterFrom} />
			<input type="date" bind:value={filterTo} />
			<button onclick={applyFilters}>Filter</button>
		</div>
		<table>
			<thead><tr><th>Time</th><th>Endpoint</th><th>Model</th><th>Prompt</th><th>Latency</th><th>Throughput</th><th>Output</th><th>Status</th></tr></thead>
			<tbody>
				{#each runs as run}
					<tr onclick={() => (selectedRun = run)} class:active={selectedRun?.id === run.id}>
						<td>{new Date(run.created_at).toLocaleString()}</td>
						<td>{run.endpoint_name}</td>
						<td>{run.model}</td>
						<td>{run.prompt_name || run.prompt_text.slice(0, 32)}</td>
						<td>{formatMs(run.latency_ms)}</td>
						<td>{formatThroughput(run.throughput_tps, run.throughput_cps)}</td>
						<td>{run.output_chars.toLocaleString()} chars</td>
						<td>{run.status}</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</section>

	{#if selectedRun}
		<section class="panel detail">
			<h3>Run detail #{selectedRun.id}</h3>
			<div class="cards compact">
				<div class="metric"><span>Endpoint</span><strong>{selectedRun.endpoint_name}</strong></div>
				<div class="metric"><span>Model</span><strong>{selectedRun.model}</strong></div>
				<div class="metric"><span>Best run</span><strong>{summary?.best_run?.id ?? "-"}</strong></div>
				<div class="metric"><span>Worst latency</span><strong>{summary?.worst_run?.id ?? "-"}</strong></div>
			</div>
			<h4>Prompt</h4>
			<pre>{selectedRun.prompt_text}</pre>
			<h4>Response</h4>
			<pre>{selectedRun.response_text || selectedRun.error}</pre>
		</section>
	{/if}
</div>

<style>
	.benchmarks { display: flex; flex-direction: column; gap: 1rem; }
	.hero, .panel, .metric { background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px; }
	.hero { display: flex; justify-content: space-between; align-items: center; padding: 1rem; }
	.eyebrow, .muted { color: var(--text-muted); margin: 0; }
	h2, h3 { margin: 0 0 0.5rem; }
	button, input, select, textarea { border: 1px solid var(--border); background: var(--bg); color: var(--text); border-radius: 8px; padding: 0.55rem; }
	button { cursor: pointer; background: var(--accent); color: white; }
	button:disabled { opacity: 0.5; cursor: not-allowed; }
	textarea { width: 100%; box-sizing: border-box; margin-top: 0.7rem; font-family: inherit; }
	.grid.two { display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: 1rem; }
	.panel { padding: 1rem; overflow: hidden; }
	.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 0.75rem; }
	.cards.compact { grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); }
	.metric { padding: 0.9rem; display: flex; flex-direction: column; gap: 0.25rem; }
	.metric span, .list-item span { color: var(--text-muted); font-size: 0.8rem; }
	.metric strong { font-size: 1.1rem; overflow-wrap: anywhere; }
	.form-row { display: flex; gap: 0.5rem; flex-wrap: wrap; align-items: center; }
	.form-row input, .form-row select { min-width: 150px; flex: 1; }
	.list { display: flex; flex-direction: column; gap: 0.45rem; margin-top: 0.75rem; }
	.list-item { display: grid; grid-template-columns: auto 1fr auto auto; gap: 0.5rem; align-items: center; border: 1px solid var(--border); border-radius: 8px; padding: 0.45rem; }
	.list-item.active, tr.active { background: var(--accent11); }
	.select { background: transparent; color: var(--text); border-color: var(--border); }
	.danger { background: var(--red); }
	.error { background: var(--red); color: white; padding: 0.75rem; border-radius: 8px; }
	.compare { display: flex; gap: 0.8rem; flex-wrap: wrap; color: var(--text-muted); margin: 0.75rem 0; }
	pre { background: #000; border: 1px solid var(--border); border-radius: 8px; padding: 0.75rem; white-space: pre-wrap; max-height: 22rem; overflow: auto; }
	.chart svg { width: 100%; height: 180px; background: #000; border: 1px solid var(--border); border-radius: 8px; }
	polyline { fill: none; stroke: var(--accent); stroke-width: 2; vector-effect: non-scaling-stroke; }
	table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
	th, td { padding: 0.6rem 0.4rem; border-bottom: 1px solid var(--border); text-align: left; }
	th { color: var(--text-muted); font-weight: normal; }
	tr { cursor: pointer; }
	@media (max-width: 760px) { .hero { align-items: flex-start; flex-direction: column; gap: 0.75rem; } .list-item { grid-template-columns: 1fr; } }
</style>
