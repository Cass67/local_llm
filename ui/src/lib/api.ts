import type {
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
	backend: "rocm" | "vulkan",
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
