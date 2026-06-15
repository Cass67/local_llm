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
	let maxTokens = $state(512);
	let temperature = $state(0.2);
	let seed = $state(-1);
	let topP = $state(0.95);
	let topK = $state(40);
	let repeatPenalty = $state(1.0);
	let systemPrompt = $state("");
	let repeatCount = $state(1);
	let filterEndpointId = $state("");

	const PROMPTS = {
		small: [
			"What is a mutex?",
			"Reverse a string in Python. One-liner only.",
			"What does SOLID stand for?",
			"Write a SQL query to count rows per group.",
			"What is the difference between TCP and UDP?",
			"What is a pointer in C?",
			"Name three HTTP status codes and what they mean.",
			"What is memoization?",
		],
		medium: [
			"Write a Python function that finds all prime numbers up to n using the Sieve of Eratosthenes.",
			"Explain how async/await works in JavaScript with a practical example.",
			"Implement a binary search tree in Python with insert and in-order traversal.",
			"Write a SQL query to find the top 5 customers by total order value from tables: orders(id, customer_id, amount) and customers(id, name).",
			"Write a Dockerfile for a Python FastAPI app that runs on port 8080.",
			"Implement a debounce function in TypeScript with a configurable delay.",
			"Write a bash script that monitors CPU usage and alerts if it exceeds 90%.",
			"Implement merge sort in Python and explain the time and space complexity.",
			"Write a React hook that fetches data with loading and error states.",
			"Implement an LRU cache in Python using only built-in data structures.",
		],
		large: [
			"Design a distributed rate limiter that works across multiple servers. Cover the data structures, coordination strategy, failure modes, and trade-offs between accuracy and performance.",
			"Explain how transformers work — cover self-attention, multi-head attention, positional encoding, the encoder/decoder structure, and why they replaced RNNs for most tasks. Include the intuition behind each component.",
			"Implement a complete REST API in Python (FastAPI) for a task management system with users, projects, and tasks. Include authentication, pagination, filtering, and proper error handling. Show the models, routes, and key implementation decisions.",
			"Explain the CAP theorem in depth: what consistency, availability, and partition tolerance mean, why you can only have two, real-world examples of databases that make each trade-off, and how modern systems blur these boundaries.",
			"Write a production-ready Kubernetes deployment for a stateful application. Include the Deployment, Service, PersistentVolumeClaim, ConfigMap, HorizontalPodAutoscaler, and explain the key decisions around resource limits, health checks, and rolling updates.",
			"Explain how modern language models are trained: pre-training objectives, tokenization, the transformer architecture, RLHF/DPO alignment, and the compute/data trade-offs. Include what happens at inference time with KV cache and speculative decoding.",
			"Design a system to process 1 million events per second. Cover ingestion, stream processing, storage tiers, backpressure handling, exactly-once semantics, and monitoring. Compare Kafka + Flink vs a simpler approach.",
		],
	};

	function randomPrompt(size: "small" | "medium" | "large") {
		const list = PROMPTS[size];
		promptText = list[Math.floor(Math.random() * list.length)];
		if (size === "small") maxTokens = 128;
		else if (size === "medium") maxTokens = 512;
		else maxTokens = 1024;
	}
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
		if (values.length < 2) return "";
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
		try {
			models = (await loadBenchmarkModels(Number(selectedEndpointId))).models;
			selectedModel = models[0] || "";
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : String(e);
		}
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
			const req = {
				endpoint_id: Number(selectedEndpointId),
				model: selectedModel,
				prompt_id: prompt?.id ?? null,
				prompt_name: prompt?.name ?? null,
				prompt_text: prompt?.text || promptText,
				system_prompt: systemPrompt || undefined,
				max_tokens: maxTokens,
				temperature,
				seed: seed >= 0 ? seed : undefined,
				top_p: topP,
				top_k: topK,
				repeat_penalty: repeatPenalty,
			};
			for (let i = 0; i < Math.max(1, repeatCount); i++) {
				latest = await runBenchmark(req);
			}
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
			<p>Save endpoints, run prompt presets, compare models, and track trends.</p>
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
			<button onclick={executeRun} disabled={running || !selectedEndpointId || !selectedModel}>{running ? "Running…" : "Run"}</button>
		</div>
		<div class="form-row params">
			<label>Max tokens<input type="number" min="1" max="8192" bind:value={maxTokens} /></label>
			<label>Temperature<input type="number" min="0" max="2" step="0.05" bind:value={temperature} /></label>
			<label>Seed (-1=rand)<input type="number" min="-1" bind:value={seed} /></label>
			<label>Top-P<input type="number" min="0" max="1" step="0.05" bind:value={topP} /></label>
			<label>Top-K<input type="number" min="0" max="200" bind:value={topK} /></label>
			<label>Repeat penalty<input type="number" min="1" max="2" step="0.05" bind:value={repeatPenalty} /></label>
			<label>Runs<input type="number" min="1" max="20" bind:value={repeatCount} /></label>
		</div>
		<textarea bind:value={systemPrompt} rows="2" placeholder="System prompt (optional)"></textarea>
		<div class="prompt-header">
			<span class="muted">Prompt</span>
			<div class="prompt-sizes">
				<button class="size-btn" onclick={() => randomPrompt("small")}>Small</button>
				<button class="size-btn" onclick={() => randomPrompt("medium")}>Medium</button>
				<button class="size-btn" onclick={() => randomPrompt("large")}>Large</button>
			</div>
		</div>
		<textarea bind:value={promptText} rows="5" placeholder="Benchmark prompt"></textarea>
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
			{#if trendPoints("latency_ms")}
				<svg viewBox="0 0 100 100" preserveAspectRatio="none"><polyline points={trendPoints("latency_ms")} /></svg>
			{:else}
				<div class="chart-empty"><span class="muted">Need ≥2 runs to show trend</span></div>
			{/if}
		</section>
		<section class="panel chart">
			<h3>Throughput trend</h3>
			{#if trendPoints("throughput_tps")}
				<svg viewBox="0 0 100 100" preserveAspectRatio="none"><polyline points={trendPoints("throughput_tps")} /></svg>
			{:else}
				<div class="chart-empty"><span class="muted">Need ≥2 runs to show trend</span></div>
			{/if}
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
	textarea { width: 100%; box-sizing: border-box; margin-top: 0.4rem; font-family: inherit; }
	.prompt-header { display: flex; align-items: center; justify-content: space-between; margin-top: 0.7rem; }
	.prompt-sizes { display: flex; gap: 0.3rem; }
	.size-btn { background: var(--bg); color: var(--text); font-size: 0.78rem; padding: 0.25rem 0.6rem; }
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
	.chart svg, .chart-empty { width: 100%; height: 180px; background: #000; border: 1px solid var(--border); border-radius: 8px; }
	.chart-empty { display: flex; align-items: center; justify-content: center; }
	.form-row.params label { display: flex; flex-direction: column; gap: 0.2rem; font-size: 0.78rem; color: var(--text-muted); flex: 1; min-width: 90px; }
	.form-row.params label input { width: 100%; }
	polyline { fill: none; stroke: var(--accent); stroke-width: 2; vector-effect: non-scaling-stroke; }
	table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
	th, td { padding: 0.6rem 0.4rem; border-bottom: 1px solid var(--border); text-align: left; }
	th { color: var(--text-muted); font-weight: normal; }
	tr { cursor: pointer; }
	@media (max-width: 760px) { .hero { align-items: flex-start; flex-direction: column; gap: 0.75rem; } .list-item { grid-template-columns: 1fr; } }
</style>
