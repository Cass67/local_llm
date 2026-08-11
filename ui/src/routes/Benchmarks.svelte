<script lang="ts">
	import { onMount, tick } from "svelte";
	import {
		createBenchmarkEndpoint,
		createBenchmarkPrompt,
		deleteBenchmarkEndpoint,
		deleteBenchmarkPrompt,
		fetchBenchmarkSummary,
		listBenchmarkEndpoints,
		listBenchmarkPrompts,
		listBenchmarkRuns,
		runBenchmark,
		loadBenchmarkModels,
		syncClusterBenchmarkEndpoints,
		listBenchmarkTypes,
		listBenchmarkTasks,
		startBenchmarkByType,
		getBenchmarkJob,
		cancelBenchmarkJob,
		benchmarkReportUrl,
		listBenchmarkRunFiles,
		getBenchmarkRunFile,
		listActiveBenchmarkJobs,
	} from "../lib/benchmarkApi";
	import { fetchClusters } from "../lib/api";
	import BakeoffPanel from "../components/BakeoffPanel.svelte";
	import LeaderboardTable from "../components/LeaderboardTable.svelte";
	import { formatMs, formatThroughput, runDelta } from "../lib/benchmarkMetrics";
	import type { BenchmarkEndpoint, BenchmarkPrompt, BenchmarkRun, BenchmarkSummary, BenchmarkJobProgress } from "../lib/benchmarkApi";
	import type { ClusterInfo } from "../lib/types";

	const DEFAULT_PROMPT = "Write a concise Python function that reverses a string and explain it.";

	let leaderboard = $state<{ load: () => void } | null>(null);
	let endpoints: BenchmarkEndpoint[] = $state([]);
	let prompts: BenchmarkPrompt[] = $state([]);
	let runs: BenchmarkRun[] = $state([]);
	let summary: BenchmarkSummary | null = $state(null);
	let clusters: ClusterInfo[] = $state([]);
	let latest: BenchmarkRun | null = $state(null);
	let selectedRun: BenchmarkRun | null = $state(null);
	let loading = $state(false);
	let running = $state(false);
	let error = $state("");

	let endpointName = $state("");
	let endpointUrl = $state("");
	let endpointKey = $state("");
	let promptName = $state("");
	let promptText = $state(DEFAULT_PROMPT);
	let selectedEndpointId = $state("");
	let endpointModels: string[] = $state([]);
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
	let benchmarkType = $state("standard");
	let benchmarkTypes: Array<{ name: string; description: string }> = $state([]);
	let consoleLog = $state("");
	let consoleVisible = $state(false);
	let consoleJobId = $state("");
	let consoleType = $state("");
	let progressPhase: "generating" | "evaluating" | null = $state(null);
	let progressDone = $state(0);
	let progressTotal = $state(0);
	let benchmarkTasks: string[] = $state([]);
	let firstNCount = $state("");
	let tasksLoading = $state(false);
	let reportModalOpen = $state(false);
	let reportModalTitle = $state("");
	let reportModalContent = $state("");
	let reportModalError = $state("");
	let reportModalType = $state("");
	let reportModalRunId = $state("");
	let reportModalFiles: string[] = $state([]);
	let reportModalSelectedFile = $state("");
	let reportInstanceStatus: Record<string, "resolved" | "unresolved" | "error"> = $state({});
	let reportInstanceFiles: Record<string, string[]> = $state({});
	let reportOtherFiles: string[] = $state([]);
	let modalFilesEl: HTMLDivElement | undefined = $state();
	let reportSearch = $state("");
	let expandedInstances: Record<string, boolean> = $state({});

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
		const candidates = list.filter((p) => p !== promptText);
		promptText = (candidates.length ? candidates : list)[Math.floor(Math.random() * (candidates.length || list.length))];
		if (size === "small") maxTokens = 128;
		else if (size === "medium") maxTokens = 512;
		else maxTokens = 1024;
		latest = null;
		selectedRun = null;
		error = "";
	}
	let filterPromptId = $state("");
	let filterModel = $state("");
	let filterStatus = $state("");
	let benchmarkTypeFilter = $state("");
	let filterFrom = $state("");
	let filterTo = $state("");

	function selectedEndpoint(): BenchmarkEndpoint | undefined {
		return endpoints.find((endpoint) => String(endpoint.id) === selectedEndpointId);
	}

	function selectedPrompt(): BenchmarkPrompt | undefined {
		return prompts.find((prompt) => String(prompt.id) === selectedPromptId);
	}

	async function loadEndpointModels() {
		if (!selectedEndpointId || selectedEndpointId === "") {
			endpointModels = [];
			return;
		}
		try {
			const result = await loadBenchmarkModels(Number(selectedEndpointId));
			endpointModels = result.models;
		} catch {
			endpointModels = [];
		}
	}

	$effect(() => {
		loadEndpointModels();
		return () => { /* cleanup if needed */ };
	});

	function modelLabel(alias: string): string {
		return alias;
	}

	function scoreLabel(run: BenchmarkRun): string {
		const match = run.response_text?.match(/(\d+)\/(\d+)/);
		if (match) return `${match[1]}/${match[2]}`;
		return run.status === "error" ? "0/1" : "-";
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

	function typeLabel(benchmarkType: string): string {
		if (benchmarkType === 'standard') return 'Standard';
		return benchmarkType;
	}

	async function syncEndpointsFromClusters() {
		try {
			const [clustersResult, endpointsResult] = await Promise.all([
				fetchClusters(),
				syncClusterBenchmarkEndpoints(),
			]);
			clusters = clustersResult.clusters;
			endpoints = endpointsResult.endpoints;
		} catch { /* non-blocking */ }
	}

	async function loadAll() {
		loading = true;
		error = "";
		try {
			const [endpointResult, promptResult, runResult, summaryResult, typesResult] =
				await Promise.all([
					listBenchmarkEndpoints(),
					listBenchmarkPrompts(),
					listBenchmarkRuns({ limit: 100 }),
					fetchBenchmarkSummary(benchmarkType === 'standard' ? undefined : benchmarkType),
					listBenchmarkTypes(),
				]);
			endpoints = endpointResult.endpoints;
			prompts = promptResult.prompts;
			runs = runResult.runs;
			summary = summaryResult;
			benchmarkTypes = typesResult.types;
			await syncEndpointsFromClusters();
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


	async function applyFilters() {
		const result = await listBenchmarkRuns({
			endpoint_id: filterEndpointId ? Number(filterEndpointId) : "",
			model: filterModel,
			prompt_id: filterPromptId ? Number(filterPromptId) : "",
			status: filterStatus,
			benchmark_type: benchmarkType === 'standard' ? undefined : benchmarkType,
			from_date: filterFrom,
			to_date: filterTo,
			limit: 100,
		});
		runs = result.runs;
	}

	async function onBenchmarkTypeChange() {
		firstNCount = "";
		if (benchmarkType === 'standard') {
			if (promptText.trim() === "") promptText = DEFAULT_PROMPT;
			benchmarkTasks = [];
		} else {
			if (promptText === DEFAULT_PROMPT || promptText.trim() === "") {
				promptText = " ";
			}
			benchmarkTasks = [];
			tasksLoading = true;
			try {
				const result = await listBenchmarkTasks(benchmarkType);
				benchmarkTasks = result.tasks;
			} catch {
				benchmarkTasks = [];
			} finally {
				tasksLoading = false;
			}
		}
		loadAll();
	}

	function formatSummary(type: string, data: unknown): string {
		if (type === 'swe-bench' && data && typeof data === 'object' && 'resolved_ids' in data) {
			const d = data as Record<string, any>;
			const lines: string[] = [
				`Score: ${d.resolved_instances}/${d.submitted_instances} resolved`,
				"",
				`✓ Resolved (${d.resolved_ids.length}):`,
				...d.resolved_ids.map((id: string) => `  ${id}`),
			];
			if (d.unresolved_ids?.length) {
				lines.push("", `✗ Unresolved (${d.unresolved_ids.length}):`);
				lines.push(...d.unresolved_ids.map((id: string) => `  ${id}`));
			}
			if (d.error_ids?.length) {
				lines.push("", `⚠ Errored (${d.error_ids.length}):`);
				lines.push(...d.error_ids.map((id: string) => `  ${id}`));
			}
			if (d.empty_patch_ids?.length) {
				lines.push("", `(empty patch, ${d.empty_patch_ids.length}):`);
				lines.push(...d.empty_patch_ids.map((id: string) => `  ${id}`));
			}
			return lines.join("\n");
		}
		if (type === 'terminal-bench' && data && typeof data === 'object' && Array.isArray((data as any).results)) {
			const trials = (data as any).results as Array<Record<string, any>>;
			const resolved = trials.filter((t) => t.is_resolved);
			const unresolved = trials.filter((t) => !t.is_resolved);
			const lines: string[] = [
				`Score: ${resolved.length}/${trials.length} resolved`,
				"",
				`✓ Resolved (${resolved.length}):`,
				...resolved.map((t) => `  ${t.task_id}`),
			];
			if (unresolved.length) {
				lines.push("", `✗ Unresolved (${unresolved.length}):`);
				lines.push(...unresolved.map((t) => `  ${t.task_id}${t.failure_mode ? ` (${t.failure_mode})` : ""}`));
			}
			return lines.join("\n");
		}
		return JSON.stringify(data, null, 2);
	}

	function instanceStatusFromSummary(type: string, data: unknown): Record<string, "resolved" | "unresolved" | "error"> {
		const status: Record<string, "resolved" | "unresolved" | "error"> = {};
		if (type === 'swe-bench' && data && typeof data === 'object' && 'resolved_ids' in data) {
			const d = data as Record<string, any>;
			for (const id of d.resolved_ids || []) status[id] = "resolved";
			for (const id of d.unresolved_ids || []) status[id] = "unresolved";
			for (const id of [...(d.error_ids || []), ...(d.empty_patch_ids || [])]) status[id] = "error";
		} else if (type === 'terminal-bench' && data && typeof data === 'object' && Array.isArray((data as any).results)) {
			for (const t of (data as any).results as Array<Record<string, any>>) {
				status[t.task_id] = t.is_resolved ? "resolved" : "unresolved";
			}
		}
		return status;
	}

	function instanceIdForFile(path: string): string | null {
		const parts = path.split("/");
		// top-level pattern: "<instance_id>/<instance_id>.traj.json"
		if (parts.length === 2 && parts[1].startsWith(`${parts[0]}.`)) {
			return parts[0];
		}
		// harness pattern: "logs/run_evaluation/<run_id>/<model>/<instance_id>/<file>"
		if (parts[0] === "logs" && parts[1] === "run_evaluation" && parts.length >= 5) {
			return parts[4];
		}
		return null;
	}

	function groupFilesByInstance(files: string[]): { groups: Record<string, string[]>; other: string[] } {
		const groups: Record<string, string[]> = {};
		const other: string[] = [];
		for (const file of files) {
			const id = instanceIdForFile(file);
			if (id) {
				(groups[id] ||= []).push(file);
			} else {
				other.push(file);
			}
		}
		return { groups, other };
	}

	async function openReport(type: string, runId: string) {
		reportModalOpen = true;
		reportModalType = type;
		reportModalRunId = runId;
		reportModalTitle = `${type} report — ${runId}`;
		reportModalContent = "";
		reportModalError = "";
		reportModalFiles = [];
		reportModalSelectedFile = "";
		reportInstanceStatus = {};
		reportOtherFiles = [];
		reportSearch = "";
		expandedInstances = {};
		try {
			const res = await fetch(benchmarkReportUrl(type, runId));
			if (res.status === 404) {
				reportModalContent = "No final report yet — this run has no completed evaluation (it may still be running, or was interrupted before finishing).";
			} else if (!res.ok) {
				throw new Error(`HTTP ${res.status}`);
			} else {
				const data = await res.json();
				reportModalContent = formatSummary(type, data);
				reportInstanceStatus = instanceStatusFromSummary(type, data);
			}
		} catch (e: unknown) {
			reportModalError = e instanceof Error ? e.message : String(e);
		}
		try {
			const { files } = await listBenchmarkRunFiles(type, runId);
			reportModalFiles = files;
			const { groups, other } = groupFilesByInstance(files);
			reportInstanceFiles = groups;
			reportOtherFiles = other;
		} catch {
			reportModalFiles = [];
		}
		await tick();
		if (modalFilesEl) modalFilesEl.scrollTop = 0;
	}

	async function selectReportFile(path: string) {
		reportModalSelectedFile = path;
		reportModalError = "";
		reportModalContent = "loading…";
		try {
			const raw = await getBenchmarkRunFile(reportModalType, reportModalRunId, path);
			if (path.endsWith(".json")) {
				try {
					reportModalContent = JSON.stringify(JSON.parse(raw), null, 2);
					return;
				} catch {
					// not valid JSON despite the extension — fall through to raw text
				}
			}
			reportModalContent = raw;
		} catch (e: unknown) {
			reportModalContent = "";
			reportModalError = e instanceof Error ? e.message : String(e);
		}
	}

	function toggleInstance(id: string) {
		expandedInstances = { ...expandedInstances, [id]: !expandedInstances[id] };
	}

	function statusIcon(status: "resolved" | "unresolved" | "error" | undefined): string {
		if (status === "resolved") return "✓";
		if (status === "unresolved") return "✗";
		if (status === "error") return "⚠";
		return "•";
	}

	function updateProgress(progress: BenchmarkJobProgress | null) {
		if (!progress || progress.total <= 1) {
			progressPhase = null;
			return;
		}
		if (progress.evaluated > 0) {
			progressPhase = "evaluating";
			progressDone = progress.evaluated;
		} else {
			progressPhase = "generating";
			progressDone = progress.generated;
		}
		progressTotal = progress.total;
	}

	async function pollJob(type: string, jobId: string): Promise<BenchmarkRun | null> {
		consoleVisible = true;
		consoleLog = "";
		consoleJobId = jobId;
		consoleType = type;
		progressPhase = null;
		progressDone = 0;
		progressTotal = 0;
		while (true) {
			const job = await getBenchmarkJob(type, jobId);
			consoleLog = job.log || consoleLog;
			updateProgress(job.progress);
			if (job.status === "done") return job.result;
			if (job.status === "error") throw new Error(job.error || "benchmark job failed");
			await new Promise((resolve) => setTimeout(resolve, 2000));
		}
	}

	let cancelling = $state(false);

	async function cancelJob() {
		if (!consoleJobId || cancelling) return;
		cancelling = true;
		try {
			await cancelBenchmarkJob(consoleType, consoleJobId);
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			cancelling = false;
		}
	}

	async function attachToJob(type: string, jobId: string) {
		running = true;
		error = "";
		try {
			const result = await pollJob(type, jobId);
			if (result) {
				latest = result;
				selectedRun = result;
			}
			await loadAll();
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			running = false;
		}
	}

	async function executeRun() {
		if (!selectedEndpointId || !selectedModel || !promptText) return;
		running = true;
		error = "";
		consoleVisible = false;
		consoleLog = "";
		try {
			const prompt = selectedPrompt();
			const firstN = parseInt(firstNCount, 10);
			const effectivePromptText =
				benchmarkType !== 'standard' && firstN > 0
					? `__first_${firstN}__`
					: prompt?.text || promptText;
			const req = {
				endpoint_id: Number(selectedEndpointId),
				model: selectedModel,
				prompt_id: prompt?.id ?? undefined,
				prompt_name: prompt?.name || undefined,
				prompt_text: effectivePromptText,
				system_prompt: systemPrompt || undefined,
				max_tokens: maxTokens,
				temperature,
				seed: seed >= 0 ? seed : undefined,
				top_p: topP,
				top_k: topK,
				repeat_penalty: repeatPenalty,
			};
			if (benchmarkType === 'standard') {
				let result: BenchmarkRun | null = null;
				for (let i = 0; i < Math.max(1, repeatCount); i++) {
					result = await runBenchmark(req);
				}
				if (result) {
					latest = result;
					selectedRun = result;
				}
				await loadAll();
				leaderboard?.load();
				running = false;
			} else {
				const { job_id } = await startBenchmarkByType(benchmarkType, req);
				await attachToJob(benchmarkType, job_id);
			}
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : String(e);
			running = false;
		}
	}

	async function reconnectToActiveJob() {
		try {
			const { jobs } = await listActiveBenchmarkJobs();
			const active = jobs.find((j) => j.status === "running");
			if (active) {
				benchmarkType = active.benchmark_type;
				await attachToJob(active.benchmark_type, active.job_id);
			}
		} catch {
			// no active job to reconnect to — not an error worth surfacing
		}
	}

	onMount(async () => {
		await loadAll();
		await reconnectToActiveJob();
	});
</script>

<div class="benchmarks">
	<div class="hero">
		<div>
			<p class="eyebrow">Benchmarks</p>
			<h2>LLM performance lab</h2>
			<p>Run a prompt, bake models off against each other, and compare everything measured so far.</p>
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

	<details class="setup">
		<summary>Endpoints &amp; prompt presets</summary>
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
	</details>

	<section class="panel runner">
		<h3>Run benchmark</h3>
		<div class="form-row">
			<select bind:value={benchmarkType} onchange={onBenchmarkTypeChange}>
				<option value="standard">Standard</option>
				{#each benchmarkTypes as type}<option value={type.name}>{type.name}</option>{/each}
			</select>
			<select bind:value={selectedEndpointId}>
				<option value="">Endpoint</option>
				{#each endpoints as endpoint}<option value={String(endpoint.id)}>{endpoint.name}</option>{/each}
			</select>
			<select bind:value={selectedModel}>
				<option value="">Select model</option>
				{#each endpointModels as m}
					<option value={m}>{m}</option>
				{/each}
			</select>
			<button onclick={executeRun} disabled={running || !selectedEndpointId || !selectedModel}>{running ? "Running…" : "Run"}</button>
		</div>
		{#if benchmarkType !== 'standard'}
			<div class="form-row params" style="background: var(--bg-card); padding: 0.75rem; border-radius: 8px; margin-top: 0.5rem;">
				<p style="margin: 0; color: var(--text-muted); font-size: 0.85rem;">
					<b>{benchmarkType} mode:</b> runs the real {benchmarkType} harness against your model. This can take several minutes (task containers are built on first run) — watch the console below for live progress.
				</p>
			</div>
		{/if}
		{#if benchmarkType === 'standard'}
			<div class="form-row params">
				<label>Max tokens<input type="number" min="1" max="8192" bind:value={maxTokens} /></label>
				<label>Temperature<input type="number" min="0" max="2" step="0.05" bind:value={temperature} /></label>
				<label>Seed (-1=rand)<input type="number" min="-1" bind:value={seed} /></label>
				<label>Top-P<input type="number" min="0" max="1" step="0.05" bind:value={topP} /></label>
				<label>Top-K<input type="number" min="0" max="200" bind:value={topK} /></label>
				<label>Repeat penalty<input type="number" min="1" max="2" step="0.05" bind:value={repeatPenalty} /></label>
				<label>Runs<input type="number" min="1" max="20" bind:value={repeatCount} /></label>
			</div>
		{/if}
		{#if benchmarkType === 'standard'}
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
		{:else}
			<label class="muted" for="task-id-filter">Task / instance to run</label>
			{#if tasksLoading}
				<p class="muted">Loading available tasks…</p>
			{:else if benchmarkTasks.length > 0}
				<div class="form-row">
					<select id="task-id-filter" bind:value={promptText} style="flex: 1;">
						<option value=" ">(first/default task)</option>
						<option value="__all__">All {benchmarkTasks.length} tasks (full dataset — can take hours, produces a score)</option>
						{#each benchmarkTasks as task}<option value={task}>{task}</option>{/each}
					</select>
					<input
						type="number"
						min="1"
						max={benchmarkTasks.length}
						bind:value={firstNCount}
						placeholder="or run first N…"
						style="width: 140px;"
					/>
				</div>
				{#if firstNCount && Number(firstNCount) > 0}
					<p class="muted" style="margin: 0.25rem 0 0;">Will run the first {firstNCount} tasks instead of the dropdown selection.</p>
				{/if}
			{:else}
				<textarea id="task-id-filter" bind:value={promptText} rows="2" placeholder="e.g. pytorch-model-cli.easy"></textarea>
			{/if}
		{/if}
	</section>

	<BakeoffPanel onfinish={() => { leaderboard?.load(); loadAll(); }} />

	{#if consoleVisible}
		<section class="panel">
			<h3>
				Console {running ? "(running…)" : ""}
				{#if running && consoleJobId}
					<button class="size-btn" onclick={cancelJob} disabled={cancelling}>{cancelling ? "Cancelling…" : "Kill run"}</button>
				{/if}
				{#if !running}
					<button class="size-btn" onclick={() => openReport(consoleType, consoleJobId)}>View full report</button>
				{/if}
			</h3>
			{#if progressPhase && progressTotal > 0}
				<div class="progress-row">
					<div class="progress-bar"><div class="progress-fill" style="width: {Math.min(100, (progressDone / progressTotal) * 100)}%"></div></div>
					<span class="muted">{progressPhase === 'generating' ? 'Generating patches' : 'Evaluating'}: {progressDone}/{progressTotal}</span>
				</div>
			{/if}
			<pre class="console-log">{consoleLog || "waiting for output…"}</pre>
		</section>
	{/if}

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

	<LeaderboardTable bind:this={leaderboard} />

	{#if benchmarkTypes.length > 0}
		<section class="panel">
			<h3>Trends</h3>
			<p class="muted">Which benchmark the charts and the tiles above are showing.</p>
			<div class="form-row" style="margin-bottom: 1rem;">
				{#each benchmarkTypes as type}
					<button
						class="size-btn"
						onclick={() => { benchmarkType = type.name; loadAll(); }}
						class:active={benchmarkType === type.name}
					>
						{type.name}
					</button>
				{/each}
			</div>
		</section>

		<div class="grid two">
			<section class="panel chart">
				<h3>Latency trend ({typeLabel(benchmarkType)})</h3>
				{#if trendPoints("latency_ms")}
					<svg viewBox="0 0 100 100" preserveAspectRatio="none"><polyline points={trendPoints("latency_ms")} /></svg>
				{:else}
					<div class="chart-empty"><span class="muted">Need ≥2 runs to show trend</span></div>
				{/if}
			</section>
			<section class="panel chart">
				<h3>Throughput trend ({typeLabel(benchmarkType)})</h3>
				{#if trendPoints("throughput_tps")}
					<svg viewBox="0 0 100 100" preserveAspectRatio="none"><polyline points={trendPoints("throughput_tps")} /></svg>
				{:else}
					<div class="chart-empty"><span class="muted">Need ≥2 runs to show trend</span></div>
				{/if}
			</section>
		</div>
	{/if}

	<section class="panel">
		<h3>History</h3>
		<div class="form-row filters">
			<select bind:value={filterEndpointId}><option value="">All endpoints</option>{#each endpoints as endpoint}<option value={String(endpoint.id)}>{endpoint.name}</option>{/each}</select>
			<input bind:value={filterModel} placeholder="Model" />
			<select bind:value={filterPromptId}><option value="">All prompts</option>{#each prompts as prompt}<option value={String(prompt.id)}>{prompt.name}</option>{/each}</select>
			<select bind:value={filterStatus}><option value="">Any status</option><option value="ok">ok</option><option value="error">error</option></select>
			<select bind:value={benchmarkTypeFilter}>
				<option value="">All benchmark types</option>
				{#each benchmarkTypes as type}
					<option value={type.name}>{type.name}</option>
				{/each}
			</select>
			<input type="date" bind:value={filterFrom} />
			<input type="date" bind:value={filterTo} />
			<button onclick={applyFilters}>Filter</button>
		</div>
		<table>
			<thead><tr><th>Time</th><th>Endpoint</th><th>Model</th><th>Prompt</th><th>Latency</th><th>Throughput</th><th>tok/s/W</th><th>Output</th><th>Status</th><th>Type</th><th>Score</th><th>Report</th></tr></thead>
			<tbody>
				{#each runs as run}
					<tr onclick={() => (selectedRun = run)} class:active={selectedRun?.id === run.id}>
						<td>{new Date(run.created_at).toLocaleString()}</td>
						<td>{run.endpoint_name}</td>
						<td>{modelLabel(run.model)}</td>
						<td>{run.prompt_name || run.prompt_text.slice(0, 32)}</td>
						<td>{formatMs(run.latency_ms)}</td>
						<td>{formatThroughput(run.throughput_tps, run.throughput_cps)}</td>
						<td title={run.psu_avg_w ? `${run.psu_avg_w.toFixed(0)} W wall draw` : "no PSU sensor"}>
							{run.tps_per_watt ? run.tps_per_watt.toFixed(3) : "—"}
						</td>
						<td>{run.output_chars.toLocaleString()} chars</td>
						<td>{run.status}</td>
						<td style="font-size: 0.75rem; color: var(--text-muted);">{run.benchmark_type}</td>
						<td class="score-cell">
							{#if run.benchmark_type !== 'standard'}
								{scoreLabel(run)}
							{/if}
						</td>
						<td>
							{#if run.run_id && run.benchmark_type !== 'standard'}
								<button class="size-btn" onclick={(e) => { e.stopPropagation(); openReport(run.benchmark_type, run.run_id ?? ""); }}>↗</button>
							{/if}
						</td>
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
				<div class="metric"><span>Model</span><strong>{modelLabel(selectedRun.model)}</strong></div>
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

{#if reportModalOpen}
	<div
		class="modal-backdrop"
		role="button"
		tabindex="0"
		onclick={() => (reportModalOpen = false)}
		onkeydown={(e) => e.key === "Escape" && (reportModalOpen = false)}
	>
		<div class="modal" role="dialog" aria-modal="true" tabindex="-1" onclick={(e) => e.stopPropagation()} onkeydown={(e) => e.stopPropagation()}>
			<div class="modal-header">
				<h3>{reportModalTitle}</h3>
				<button class="size-btn" onclick={() => (reportModalOpen = false)}>Close</button>
			</div>
			<div class="modal-columns">
				{#if reportModalFiles.length > 0}
					<div class="modal-files" bind:this={modalFilesEl}>
						<button
							class="size-btn"
							class:active={reportModalSelectedFile === ""}
							onclick={() => { reportModalSelectedFile = ""; openReport(reportModalType, reportModalRunId); }}
						>Summary</button>
						{#if Object.keys(reportInstanceFiles).length > 0}
							<input type="search" placeholder="Filter instances…" bind:value={reportSearch} class="report-search" />
							{#each Object.keys(reportInstanceFiles).sort() as id}
								{#if id.toLowerCase().includes(reportSearch.toLowerCase())}
									<div class="instance-group">
										<button class="size-btn instance-header" onclick={() => toggleInstance(id)}>
											<span class="status-icon status-{reportInstanceStatus[id] || 'unknown'}">{statusIcon(reportInstanceStatus[id])}</span>
											{id}
										</button>
										{#if expandedInstances[id]}
											{#each reportInstanceFiles[id] as file}
												<button
													class="size-btn instance-file"
													class:active={reportModalSelectedFile === file}
													onclick={() => selectReportFile(file)}
												>{file.split("/").pop()}</button>
											{/each}
										{/if}
									</div>
								{/if}
							{/each}
						{/if}
						{#if reportOtherFiles.length > 0}
							<p class="muted" style="margin: 0.5rem 0 0.25rem;">Other files</p>
							{#each reportOtherFiles as file}
								<button
									class="size-btn other-file"
									class:active={reportModalSelectedFile === file}
									onclick={() => selectReportFile(file)}
									title={file}
								>{file.split("/").pop()}</button>
							{/each}
						{/if}
					</div>
				{/if}
				<div class="modal-viewer">
					{#if reportModalError}
						<div class="error">{reportModalError}</div>
					{:else if reportModalContent}
						<pre class="modal-body">{reportModalContent}</pre>
					{:else}
						<p class="muted">Loading…</p>
					{/if}
				</div>
			</div>
		</div>
	</div>
{/if}

<style>
	.benchmarks { display: flex; flex-direction: column; gap: 1rem; }
	.hero, .panel, .metric { background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px; }
	.setup > summary { cursor: pointer; color: var(--text-muted); padding: 0.5rem 0; }
	.setup[open] > summary { margin-bottom: 0.5rem; }
	.hero { display: flex; justify-content: space-between; align-items: center; padding: 1rem; }
	.eyebrow, .muted { color: var(--text-muted); margin: 0; }
	h2, h3 { margin: 0 0 0.5rem; }
	button, input, select, textarea { border: 1px solid var(--border); background: var(--bg); color: var(--text); border-radius: 8px; padding: 0.55rem; }
	button { cursor: pointer; background: var(--accent); color: white; }
	button:disabled { opacity: 0.5; cursor: not-allowed; }
	textarea { width: 100%; box-sizing: border-box; margin-top: 0.4rem; font-family: inherit; }
	.prompt-header { display: flex; align-items: center; justify-content: space-between; margin-top: 0.7rem; }
	.prompt-sizes { display: flex; gap: 0.3rem; }
	.size-btn { background: var(--bg); color: var(--text); font-size: 0.78rem; padding: 0.25rem 0.6rem; border: 1px solid var(--border); }
	.size-btn.active, .size-btn:hover.active { background: var(--accent); color: white; border-color: var(--accent); }
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
	.modal-backdrop { position: fixed; inset: 0; background: rgba(0, 0, 0, 0.6); display: flex; align-items: center; justify-content: center; z-index: 100; }
	.modal { background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px; width: min(95vw, 1200px); height: 85vh; display: flex; flex-direction: column; padding: 1rem; }
	.modal-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem; }
	.modal-columns { display: flex; gap: 0.75rem; flex: 1; min-height: 0; }
	.modal-files { display: flex; flex-direction: column; gap: 0.25rem; width: 300px; flex-shrink: 0; overflow: auto; }
	.modal-files .size-btn { text-align: left; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
	.modal-files .size-btn.active { background: var(--accent); color: #fff; }
	.modal-viewer { flex: 1; min-width: 0; overflow: auto; }
	.modal-body { overflow: auto; background: #000; border: 1px solid var(--border); border-radius: 8px; padding: 0.75rem; white-space: pre-wrap; height: 100%; box-sizing: border-box; }
	.report-search { margin: 0.25rem 0; }
	.instance-group { display: flex; flex-direction: column; gap: 0.15rem; }
	.instance-header { font-weight: 600; }
	.instance-file { padding-left: 1.5rem; font-size: 0.8rem; color: var(--text-muted); }
	.status-icon { display: inline-block; width: 1.1rem; text-align: center; }
	.status-resolved { color: #4caf50; }
	.status-unresolved { color: #e57373; }
	.status-error { color: #ffb74d; }
	.score-cell { font-weight: 600; font-variant-numeric: tabular-nums; }
	.progress-row { display: flex; align-items: center; gap: 0.75rem; margin-bottom: 0.5rem; }
	.progress-bar { flex: 1; height: 8px; border-radius: 4px; background: var(--border); overflow: hidden; }
	.progress-fill { height: 100%; background: var(--accent); transition: width 0.3s ease; }
</style>
