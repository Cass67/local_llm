import type {
	Backend,
	ModelListResponse,
	CurrentModelResponse,
	SwitchRequest,
	SwitchResponse,
	CopyBackendResponse,
	SearchResponse,
	InventoryModel,
	StatusResponse,
	StatsResponse,
	DeleteResponse,
	HFCardResponse,
	InstallResult,
	BenchmarkEndpoint,
	BenchmarkPrompt,
	BenchmarkRun,
	BenchmarkRunFilters,
	BenchmarkSummary,
	ChatMetric,
	RunnerHealth,
	GpuInfo,
	ClusterInfo,
} from "./types";

const BASE = "/api/local-llm";

// --- Models ---

export async function fetchModels(): Promise<ModelListResponse> {
	const res = await fetch(`${BASE}/models`);
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

export async function fetchCurrentModel(): Promise<CurrentModelResponse> {
	const res = await fetch(`${BASE}/models/current`);
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

export async function switchModel(req: SwitchRequest): Promise<SwitchResponse> {
	const res = await fetch(`${BASE}/models/switch`, {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(req),
	});
	if (!res.ok) {
		const err = await res.json().catch(() => ({ detail: "Unknown error" }));
		throw new Error(err.detail || `HTTP ${res.status}`);
	}
	return res.json();
}

export async function stopServer(): Promise<{ status: string }> {
	const res = await fetch(`${BASE}/models/stop`, { method: "POST" });
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

export async function copyModelBackend(
	family: string,
	backend: Backend,
): Promise<CopyBackendResponse> {
	const res = await fetch(
		`${BASE}/models/${encodeURIComponent(family)}/copy-backend`,
		{
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({ backend }),
		},
	);
	if (!res.ok) {
		const err = await res.json().catch(() => ({ detail: "Unknown error" }));
		throw new Error(err.detail || `HTTP ${res.status}`);
	}
	return res.json();
}

// --- Search & Install ---

export async function searchModels(
	query: string,
	limit = 30,
): Promise<SearchResponse> {
	const res = await fetch(
		`${BASE}/search?query=${encodeURIComponent(query)}&limit=${limit}`,
	);
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

export async function installModel(
	repo: string,
	file: string,
	profile: string,
): Promise<InstallResult> {
	const res = await fetch(`${BASE}/search/install`, {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({ repo, file, profile }),
	});
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

// --- Inventory & Status ---

export async function fetchInventory(): Promise<{
	models: InventoryModel[];
}> {
	const res = await fetch(`${BASE}/inventory`);
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

export async function fetchStatus(): Promise<StatusResponse> {
	const res = await fetch(`${BASE}/status`);
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

export async function fetchStats(): Promise<StatsResponse> {
	const res = await fetch(`${BASE}/stats`);
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

export async function fetchStatsHistory(limit = 50): Promise<{ metrics: ChatMetric[] }> {
	const res = await fetch(`${BASE}/stats/history?limit=${limit}`);
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

export async function fetchRunnerHealth(): Promise<RunnerHealth> {
	const res = await fetch(`${BASE}/runner/health`);
	if (!res.ok) return { error: `HTTP ${res.status}` };
	return res.json();
}

// --- Benchmarks ---

export async function listBenchmarkEndpoints(): Promise<{
	endpoints: BenchmarkEndpoint[];
}> {
	const res = await fetch(`${BASE}/benchmark/endpoints`);
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

export async function createBenchmarkEndpoint(req: {
	name: string;
	base_url: string;
	api_key?: string;
}): Promise<BenchmarkEndpoint> {
	const res = await fetch(`${BASE}/benchmark/endpoints`, {
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
	const res = await fetch(`${BASE}/benchmark/endpoints/${id}`, {
		method: "DELETE",
	});
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

export async function listBenchmarkPrompts(): Promise<{
	prompts: BenchmarkPrompt[];
}> {
	const res = await fetch(`${BASE}/benchmark/prompts`);
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

export async function createBenchmarkPrompt(req: {
	name: string;
	text: string;
}): Promise<BenchmarkPrompt> {
	const res = await fetch(`${BASE}/benchmark/prompts`, {
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
	const res = await fetch(`${BASE}/benchmark/prompts/${id}`, {
		method: "DELETE",
	});
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

export async function loadBenchmarkModels(
	endpoint_id: number,
): Promise<{ models: string[] }> {
	const res = await fetch(`${BASE}/benchmark/models`, {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({ endpoint_id }),
	});
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

export async function runBenchmark(req: {
	endpoint_id: number;
	model: string;
	prompt_text: string;
	prompt_id?: number | null;
	prompt_name?: string | null;
	temperature?: number;
	max_tokens?: number;
}): Promise<BenchmarkRun> {
	const res = await fetch(`${BASE}/benchmark/runs`, {
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
	const res = await fetch(`${BASE}/benchmark/runs${query ? `?${query}` : ""}`);
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

export async function fetchBenchmarkSummary(): Promise<BenchmarkSummary> {
	const res = await fetch(`${BASE}/benchmark/summary`);
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

// --- Model Management ---

export async function fetchModelDetail(family: string): Promise<any> {
	const res = await fetch(
		`${BASE}/models/${encodeURIComponent(family)}/detail`,
	);
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

export async function editModel(family: string, edits: any): Promise<any> {
	const res = await fetch(`${BASE}/models/${encodeURIComponent(family)}`, {
		method: "PUT",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(edits),
	});
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

export async function deleteModels(repos: string[]): Promise<DeleteResponse> {
	const res = await fetch(`${BASE}/models/delete`, {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({ repos }),
	});
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

// --- HF Card ---

export async function fetchHFCard(repo: string): Promise<HFCardResponse> {
	const res = await fetch(`${BASE}/hfcard?repo=${encodeURIComponent(repo)}`);
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

// --- GPU Clusters ---

export async function fetchGpus(): Promise<{ gpus: GpuInfo[] }> {
	const res = await fetch(`${BASE}/gpus`);
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

export async function fetchClusters(): Promise<{ clusters: ClusterInfo[] }> {
	const res = await fetch(`${BASE}/clusters`);
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

export async function createCluster(req: {
	name: string;
	gpu_pci_ids: string[];
	backend: Backend;
}): Promise<ClusterInfo> {
	const res = await fetch(`${BASE}/clusters`, {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(req),
	});
	if (!res.ok) {
		const err = await res.json().catch(() => ({ detail: "Unknown error" }));
		throw new Error(err.detail || `HTTP ${res.status}`);
	}
	return res.json();
}

export async function deleteCluster(id: string): Promise<{ status: string }> {
	const res = await fetch(`${BASE}/clusters/${encodeURIComponent(id)}`, { method: "DELETE" });
	if (!res.ok) {
		const err = await res.json().catch(() => ({ detail: "Unknown error" }));
		throw new Error(err.detail || `HTTP ${res.status}`);
	}
	return res.json();
}

export async function startOnCluster(
	clusterId: string,
	family: string,
	profile: string,
): Promise<{ status: string }> {
	const res = await fetch(`${BASE}/clusters/${encodeURIComponent(clusterId)}/start`, {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({ family, profile }),
	});
	if (!res.ok) {
		const err = await res.json().catch(() => ({ detail: "Unknown error" }));
		throw new Error(err.detail || `HTTP ${res.status}`);
	}
	return res.json();
}

export async function stopCluster(clusterId: string): Promise<{ status: string }> {
	const res = await fetch(`${BASE}/clusters/${encodeURIComponent(clusterId)}/stop`, {
		method: "POST",
	});
	if (!res.ok) {
		const err = await res.json().catch(() => ({ detail: "Unknown error" }));
		throw new Error(err.detail || `HTTP ${res.status}`);
	}
	return res.json();
}

// --- Init ---

export async function initTarget(target: string): Promise<any> {
	const res = await fetch(`${BASE}/init`, {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({ target }),
	});
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}
