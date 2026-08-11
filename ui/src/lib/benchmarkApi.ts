export interface BenchmarkEndpoint {
	id: number;
	name: string;
	base_url: string;
	api_key_set: boolean;
	created_at: string;
	updated_at: string;
}

export interface BenchmarkPrompt {
	id: number;
	name: string;
	text: string;
	created_at: string;
	updated_at: string;
}

export interface BenchmarkRun {
	id: number;
	endpoint_id: number | null;
	endpoint_name: string;
	endpoint_base_url: string;
	model: string;
	prompt_id: number | null;
	prompt_name: string | null;
	prompt_text: string;
	response_text: string;
	latency_ms: number | null;
	duration_ms: number | null;
	output_chars: number;
	output_words: number;
	prompt_tokens: number | null;
	completion_tokens: number | null;
	total_tokens: number | null;
	throughput_tps: number | null;
	throughput_cps: number | null;
	psu_avg_w?: number | null;
	psu_peak_w?: number | null;
	gpu_avg_w?: number | null;
	tps_per_watt?: number | null;
	profile?: string | null;
	status: string;
	error: string | null;
	benchmark_type: string;
	run_id: string | null;
	created_at: string;
}

export interface BenchmarkType {
	name: string;
	description: string;
}

export interface BenchmarkRunRequest {
	endpoint_id: number;
	model: string;
	prompt_text: string;
	system_prompt?: string;
	prompt_id?: number;
	prompt_name?: string;
	temperature?: number;
	max_tokens?: number;
	seed?: number;
	top_p?: number;
	top_k?: number;
	repeat_penalty?: number;
}

export interface BenchmarkSummary {
	total_runs: number;
	avg_latency_ms: number | null;
	best_throughput_tps: number | null;
	avg_throughput_tps: number | null;
	error_rate: number;
	best_run: BenchmarkRun | null;
	worst_run: BenchmarkRun | null;
	trends: Array<
		Pick<
			BenchmarkRun,
			| "id"
			| "created_at"
			| "endpoint_name"
			| "model"
			| "prompt_name"
			| "latency_ms"
			| "throughput_tps"
			| "throughput_cps"
			| "status"
		>
	>;
}

export interface BenchmarkRunFilters {
	endpoint_id?: number | "";
	model?: string;
	prompt_id?: number | "";
	status?: string;
	benchmark_type?: string;
	from_date?: string;
	to_date?: string;
	limit?: number;
	offset?: number;
}

const BASE = "/api/local-llm/benchmark";

export async function listBenchmarkEndpoints(): Promise<{
	endpoints: BenchmarkEndpoint[];
}> {
	const res = await fetch(`${BASE}/endpoints`);
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

export async function syncClusterBenchmarkEndpoints(): Promise<{
	endpoints: BenchmarkEndpoint[];
}> {
	const res = await fetch(`${BASE}/endpoints/sync-clusters`, {
		method: "POST",
	});
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

export async function createBenchmarkEndpoint(req: {
	name: string;
	base_url: string;
	api_key?: string;
}): Promise<BenchmarkEndpoint> {
	const res = await fetch(`${BASE}/endpoints`, {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(req),
	});
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

export async function deleteBenchmarkEndpoint(
	id: number,
): Promise<{ deleted: boolean }> {
	const res = await fetch(`${BASE}/endpoints/${id}`, { method: "DELETE" });
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

export async function listBenchmarkPrompts(): Promise<{
	prompts: BenchmarkPrompt[];
}> {
	const res = await fetch(`${BASE}/prompts`);
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

export async function createBenchmarkPrompt(req: {
	name: string;
	text: string;
}): Promise<BenchmarkPrompt> {
	const res = await fetch(`${BASE}/prompts`, {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(req),
	});
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

export async function deleteBenchmarkPrompt(
	id: number,
): Promise<{ deleted: boolean }> {
	const res = await fetch(`${BASE}/prompts/${id}`, { method: "DELETE" });
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

export async function loadBenchmarkModels(
	endpoint_id: number,
): Promise<{ models: string[] }> {
	const res = await fetch(`${BASE}/models`, {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({ endpoint_id }),
	});
	if (!res.ok) {
		const err = await res.json().catch(() => ({ detail: "" }));
		throw new Error(err.detail || `HTTP ${res.status}`);
	}
	return res.json();
}

export async function runBenchmark(req: {
	endpoint_id: number;
	model: string;
	prompt_text: string;
	system_prompt?: string;
	prompt_id?: number | null;
	prompt_name?: string | null;
	temperature?: number;
	max_tokens?: number;
	seed?: number;
	top_p?: number;
	top_k?: number;
	repeat_penalty?: number;
}): Promise<BenchmarkRun> {
	const res = await fetch(`${BASE}/runs`, {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(req),
	});
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

export async function listBenchmarkRuns(
	filters: BenchmarkRunFilters = {},
): Promise<{
	total: number;
	runs: BenchmarkRun[];
}> {
	const params = new URLSearchParams();
	for (const [key, value] of Object.entries(filters)) {
		if (value !== undefined && value !== null && value !== "")
			params.set(key, String(value));
	}
	const query = params.toString();
	const res = await fetch(`${BASE}/runs${query ? `?${query}` : ""}`);
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

export async function fetchBenchmarkSummary(benchmark_type?: string): Promise<BenchmarkSummary> {
	const params = benchmark_type ? `?benchmark_type=${encodeURIComponent(benchmark_type)}` : "";
	const res = await fetch(`${BASE}/summary${params}`);
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

export async function listBenchmarkTypes(): Promise<{ types: BenchmarkType[] }> {
	const res = await fetch(`${BASE}/types`);
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

export async function listBenchmarkTasks(benchmark_type: string): Promise<{ tasks: string[] }> {
	const res = await fetch(`${BASE}/types/${benchmark_type}/tasks`);
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

export interface RunBenchmarkByTypeRequest extends Omit<BenchmarkRunRequest, 'endpoint_id'> {
	endpoint_id: number;
	model: string;
	prompt_text: string;
}

export async function runBenchmarkByType(
	benchmark_type: string,
	req: RunBenchmarkByTypeRequest,
): Promise<BenchmarkRun> {
	const res = await fetch(`${BASE}/runs/${benchmark_type}`, {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(req),
	});
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

export async function startBenchmarkByType(
	benchmark_type: string,
	req: RunBenchmarkByTypeRequest,
): Promise<{ job_id: string }> {
	const res = await fetch(`${BASE}/runs/${benchmark_type}/start`, {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(req),
	});
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

export interface BenchmarkJobProgress {
	total: number;
	generated: number;
	evaluated: number;
}

export interface BenchmarkJob {
	status: "running" | "done" | "error";
	log: string;
	result: BenchmarkRun | null;
	error: string | null;
	progress: BenchmarkJobProgress | null;
}

export async function getBenchmarkJob(
	benchmark_type: string,
	job_id: string,
): Promise<BenchmarkJob> {
	const res = await fetch(`${BASE}/runs/${benchmark_type}/jobs/${job_id}`);
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

export async function cancelBenchmarkJob(
	benchmark_type: string,
	job_id: string,
): Promise<{ cancelled: boolean }> {
	const res = await fetch(`${BASE}/runs/${benchmark_type}/jobs/${job_id}/cancel`, {
		method: "POST",
	});
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

export interface ActiveBenchmarkJob {
	job_id: string;
	benchmark_type: string;
	status: string;
}

export async function listActiveBenchmarkJobs(): Promise<{ jobs: ActiveBenchmarkJob[] }> {
	const res = await fetch(`${BASE}/jobs`);
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

export function benchmarkReportUrl(benchmark_type: string, run_id: string): string {
	return `${BASE}/runs/${benchmark_type}/report/${run_id}`;
}

export async function listBenchmarkRunFiles(
	benchmark_type: string,
	run_id: string,
): Promise<{ files: string[] }> {
	const res = await fetch(`${BASE}/runs/${benchmark_type}/report/${run_id}/files`);
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

export async function getBenchmarkRunFile(
	benchmark_type: string,
	run_id: string,
	path: string,
): Promise<string> {
	const res = await fetch(
		`${BASE}/runs/${benchmark_type}/report/${run_id}/file?path=${encodeURIComponent(path)}`,
	);
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.text();
}
