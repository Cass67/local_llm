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
	RouterConfig,
	RouterHealth,
	IdleUnloadConfig,
	UpdateStatus,
	CommitDetail,
	BuildStatus,
	AgentsUpdateStatus,
	ServiceUpdate,
	ModelProfile,
	FamilyProfiles,
	ProfilesData,
	GpuStatusResponse,
	ProfileLintResponse,
	SaveProfileResponse,
	SweepSnapshot,
	SweepListEntry,
	QualityReport,
	QualityCase,
	RegressionResponse,
	RegressionReport,
	RouteLogResponse,
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
	vramGb?: number,
): Promise<SearchResponse> {
	const params = new URLSearchParams({ query, limit: String(limit) });
	if (vramGb) params.set("vram_gb", String(vramGb));
	const res = await fetch(`${BASE}/search?${params}`);
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

export async function cancelDownload(repo: string): Promise<void> {
	await fetch(`${BASE}/search/cancel`, {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({ repo }),
	});
}

export async function fetchUnregistered(): Promise<{ models: Array<{ repo: string; file: string; path: string }> }> {
	const res = await fetch(`${BASE}/search/unregistered`);
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

export async function acceptModel(repo: string, file: string, path: string): Promise<{ status: string; family: string }> {
	const res = await fetch(`${BASE}/search/accept`, {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({ repo, file, path }),
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

export async function fetchStatsHistory(
	limit = 50,
): Promise<{ metrics: ChatMetric[] }> {
	const res = await fetch(`${BASE}/stats/history?limit=${limit}`);
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

export async function fetchRunnerHealth(): Promise<RunnerHealth> {
	const res = await fetch(`${BASE}/runner/health`);
	if (!res.ok) return { error: `HTTP ${res.status}` };
	return res.json();
}

// --- GPU status (fdinfo engine occupancy) ---

export async function fetchGpuStatus(): Promise<GpuStatusResponse> {
	const res = await fetch(`${BASE}/gpu-status`);
	if (!res.ok) return { ts: Date.now() / 1000, runners: [] };
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
	const res = await fetch(`${BASE}/clusters/${encodeURIComponent(id)}`, {
		method: "DELETE",
	});
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
	const res = await fetch(
		`${BASE}/clusters/${encodeURIComponent(clusterId)}/start`,
		{
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({ family, profile }),
		},
	);
	if (!res.ok) {
		const err = await res.json().catch(() => ({ detail: "Unknown error" }));
		throw new Error(err.detail || `HTTP ${res.status}`);
	}
	return res.json();
}

export async function stopCluster(
	clusterId: string,
): Promise<{ status: string }> {
	const res = await fetch(
		`${BASE}/clusters/${encodeURIComponent(clusterId)}/stop`,
		{
			method: "POST",
		},
	);
	if (!res.ok) {
		const err = await res.json().catch(() => ({ detail: "Unknown error" }));
		throw new Error(err.detail || `HTTP ${res.status}`);
	}
	return res.json();
}

// --- Router ---

export async function fetchRouterConfig(): Promise<RouterConfig> {
	const res = await fetch(`${BASE}/router/config`);
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

export async function saveRouterConfig(cfg: RouterConfig): Promise<void> {
	const res = await fetch(`${BASE}/router/config`, {
		method: "PUT",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(cfg),
	});
	if (!res.ok) {
		const err = await res.json().catch(() => ({ detail: "Unknown error" }));
		throw new Error(err.detail || `HTTP ${res.status}`);
	}
}

export async function fetchRouterHealth(): Promise<RouterHealth> {
	const res = await fetch(`${BASE}/router/health`);
	if (!res.ok) return { running: false, detail: `HTTP ${res.status}` };
	return res.json();
}

export async function fetchIdleUnload(): Promise<IdleUnloadConfig> {
	const res = await fetch(`${BASE}/idle-unload`);
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

export async function saveIdleUnload(cfg: IdleUnloadConfig): Promise<void> {
	const res = await fetch(`${BASE}/idle-unload`, {
		method: "PUT",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(cfg),
	});
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
}

// --- Audit ---

export async function auditModels(): Promise<{
	orphaned: Array<{ family: string; alias: string; label: string | null; model_name: string; profile: string }>;
	total: number;
}> {
	const res = await fetch(`${BASE}/models/audit`);
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

export async function cleanupOrphanedModels(): Promise<{ deleted: string[]; count: number }> {
	const res = await fetch(`${BASE}/models/audit`, { method: "POST" });
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

// --- Profiles ---

export async function importProfilesFromModels(): Promise<{ imported: number }> {
	const res = await fetch(`${BASE}/profiles/import`, { method: "POST" });
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

export async function fetchAllProfiles(): Promise<ProfilesData> {
	const res = await fetch(`${BASE}/profiles`);
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

export async function fetchFamilyProfiles(family: string): Promise<FamilyProfiles> {
	const res = await fetch(`${BASE}/profiles/${encodeURIComponent(family)}`);
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

export async function upsertProfile(
	family: string,
	name: string,
	profile: ModelProfile,
): Promise<SaveProfileResponse> {
	const res = await fetch(
		`${BASE}/profiles/${encodeURIComponent(family)}/${encodeURIComponent(name)}`,
		{
			method: "PUT",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify(profile),
		},
	);
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

export async function lintProfile(
	family: string,
	name: string,
	clusterId = "",
): Promise<ProfileLintResponse> {
	const qs = clusterId ? `?cluster_id=${encodeURIComponent(clusterId)}` : "";
	const res = await fetch(
		`${BASE}/profiles/${encodeURIComponent(family)}/${encodeURIComponent(name)}/lint${qs}`,
	);
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

export async function deleteProfile(family: string, name: string): Promise<void> {
	const res = await fetch(
		`${BASE}/profiles/${encodeURIComponent(family)}/${encodeURIComponent(name)}`,
		{ method: "DELETE" },
	);
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
}

export async function cloneProfile(
	family: string,
	name: string,
	newName: string,
): Promise<void> {
	const res = await fetch(
		`${BASE}/profiles/${encodeURIComponent(family)}/${encodeURIComponent(name)}/clone`,
		{
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({ new_name: newName }),
		},
	);
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
}

export async function setDefaultProfile(family: string, name: string): Promise<void> {
	const res = await fetch(
		`${BASE}/profiles/${encodeURIComponent(family)}/default/${encodeURIComponent(name)}`,
		{ method: "PUT" },
	);
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
}

// --- Profile snapshots (backup / restore) ---

export interface ProfileSnapshot {
	id: string;
	created_at: string;
	label: string;
	families: number;
	profiles: number;
	bytes: number;
}

export async function fetchProfileSnapshots(): Promise<ProfileSnapshot[]> {
	const res = await fetch(`${BASE}/profiles/snapshots`);
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return (await res.json()).snapshots;
}

export async function createProfileSnapshot(label = ""): Promise<{ id: string }> {
	const res = await fetch(`${BASE}/profiles/snapshots`, {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({ label }),
	});
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

export async function restoreProfileSnapshot(id: string): Promise<{ restored: string }> {
	const res = await fetch(
		`${BASE}/profiles/snapshots/${encodeURIComponent(id)}/restore`,
		{ method: "POST" },
	);
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

export async function fetchProfileSnapshot(id: string): Promise<ProfilesData> {
	const res = await fetch(`${BASE}/profiles/snapshots/${encodeURIComponent(id)}`);
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

export async function deleteProfileSnapshot(id: string): Promise<void> {
	const res = await fetch(`${BASE}/profiles/snapshots/${encodeURIComponent(id)}`, {
		method: "DELETE",
	});
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
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

// --- llama.cpp updates ---

export async function fetchUpdateStatus(): Promise<UpdateStatus> {
	const res = await fetch(`${BASE}/update/status`);
	if (!res.ok) {
		const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
		throw new Error(err.detail || `HTTP ${res.status}`);
	}
	return res.json();
}

export async function fetchCommitDetail(sha: string): Promise<CommitDetail> {
	const res = await fetch(`${BASE}/update/commit/${sha}`);
	if (!res.ok) {
		const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
		throw new Error(err.detail || `HTTP ${res.status}`);
	}
	return res.json();
}

export async function startRunnerBuild(backends: string[]): Promise<{ status: string; ref: string }> {
	const res = await fetch(`${BASE}/update/build`, {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({ backends }),
	});
	if (!res.ok) {
		const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
		throw new Error(err.detail || `HTTP ${res.status}`);
	}
	return res.json();
}

export async function fetchBuildStatus(): Promise<BuildStatus> {
	const res = await fetch(`${BASE}/update/build/status`);
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

export async function fetchAgentsUpdateStatus(): Promise<AgentsUpdateStatus> {
	const res = await fetch(`${BASE}/update/agents`);
	if (!res.ok) {
		const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
		throw new Error(err.detail || `HTTP ${res.status}`);
	}
	return res.json();
}

export async function startAgentsBuild(): Promise<{ status: string; versions: Record<string, string> }> {
	const res = await fetch(`${BASE}/update/agents/build`, { method: "POST" });
	if (!res.ok) {
		const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
		throw new Error(err.detail || `HTTP ${res.status}`);
	}
	return res.json();
}

export async function fetchServiceUpdates(): Promise<{ services: ServiceUpdate[] }> {
	const res = await fetch(`${BASE}/update/services`);
	if (!res.ok) {
		const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
		throw new Error(err.detail || `HTTP ${res.status}`);
	}
	return res.json();
}

export async function startServiceUpdate(id: string): Promise<{ status: string; ref: string | null }> {
	const res = await fetch(`${BASE}/update/services/${id}/build`, { method: "POST" });
	if (!res.ok) {
		const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
		throw new Error(err.detail || `HTTP ${res.status}`);
	}
	return res.json();
}

// --- Sweep (profile autotuner) ---

export interface SweepRequest {
	family: string;
	cluster_id: string;
	base_profile: string;
	grid: Record<string, unknown[]>;
	prompt_text: string;
	system_prompt?: string;
	max_tokens?: number;
	repeats?: number;
	warmup?: number;
	objective?: string;
	quality_gate?: boolean;
	min_pass_rate?: number;
	judge_url?: string;
	judge_model?: string;
}

export async function startSweep(
	req: SweepRequest,
): Promise<{ id: string; total: number; status: string }> {
	const res = await fetch(`${BASE}/sweep`, {
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

export async function fetchSweeps(): Promise<{ sweeps: SweepListEntry[] }> {
	const res = await fetch(`${BASE}/sweep`);
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

export async function fetchSweep(id: string): Promise<SweepSnapshot> {
	const res = await fetch(`${BASE}/sweep/${encodeURIComponent(id)}`);
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

export async function cancelSweep(id: string): Promise<void> {
	const res = await fetch(`${BASE}/sweep/${encodeURIComponent(id)}/cancel`, {
		method: "POST",
	});
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
}

export async function promoteSweepResult(
	id: string,
	newProfile: string,
	index?: number,
): Promise<{ profile: string; config: Record<string, unknown> }> {
	const res = await fetch(`${BASE}/sweep/${encodeURIComponent(id)}/promote`, {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({ new_profile: newProfile, index }),
	});
	if (!res.ok) {
		const err = await res.json().catch(() => ({ detail: "Unknown error" }));
		throw new Error(err.detail || `HTTP ${res.status}`);
	}
	return res.json();
}

// --- Quality (golden prompt set) ---

export async function fetchQualityCases(): Promise<{
	cases: QualityCase[];
	is_default: boolean;
}> {
	const res = await fetch(`${BASE}/quality/cases`);
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

/** Replace the golden set. An empty list restores the built-in defaults. */
export async function saveQualityCases(
	cases: QualityCase[],
): Promise<{ status: string; count: number }> {
	const res = await fetch(`${BASE}/quality/cases`, {
		method: "PUT",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({ cases }),
	});
	if (!res.ok) {
		const err = await res.json().catch(() => ({ detail: "Unknown error" }));
		throw new Error(err.detail || `HTTP ${res.status}`);
	}
	return res.json();
}

export async function runQualitySet(
	clusterId: string,
	judgeUrl = "",
	judgeModel = "",
): Promise<QualityReport> {
	const res = await fetch(`${BASE}/quality/run`, {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({
			cluster_id: clusterId,
			judge_url: judgeUrl,
			judge_model: judgeModel,
		}),
	});
	if (!res.ok) {
		const err = await res.json().catch(() => ({ detail: "Unknown error" }));
		throw new Error(err.detail || `HTTP ${res.status}`);
	}
	return res.json();
}

// --- Regression guard ---

export async function fetchRegression(): Promise<RegressionResponse> {
	const res = await fetch(`${BASE}/update/regression`);
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

export async function runRegressionGuard(): Promise<RegressionReport> {
	const res = await fetch(`${BASE}/update/regression/run`, { method: "POST" });
	if (!res.ok) {
		const err = await res.json().catch(() => ({ detail: "Unknown error" }));
		throw new Error(err.detail || `HTTP ${res.status}`);
	}
	return res.json();
}

export async function acceptRegressionBaseline(): Promise<{ updated: number }> {
	const res = await fetch(`${BASE}/update/regression/accept`, { method: "POST" });
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

// --- Router decision log ---

export async function fetchRouteLog(differingOnly = false): Promise<RouteLogResponse> {
	const res = await fetch(
		`${BASE}/router/log?limit=50&differing_only=${differingOnly}`,
	);
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}
