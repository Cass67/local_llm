import type {
	ModelListResponse,
	CurrentModelResponse,
	SwitchRequest,
	SwitchResponse,
	SearchResponse,
	InventoryModel,
	StatusResponse,
	DeleteResponse,
	HFCardResponse,
} from "./types";

const BASE = "";

// --- Models ---

export async function fetchModels(): Promise<ModelListResponse> {
	const res = await fetch(`${BASE}/api/models`);
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

export async function fetchCurrentModel(): Promise<CurrentModelResponse> {
	const res = await fetch(`${BASE}/api/models/current`);
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

export async function switchModel(req: SwitchRequest): Promise<SwitchResponse> {
	const res = await fetch(`${BASE}/api/models/switch`, {
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
	const res = await fetch(`${BASE}/api/models/stop`, { method: "POST" });
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

// --- Search & Install ---

export async function searchModels(
	query: string,
	limit = 30,
): Promise<SearchResponse> {
	const res = await fetch(
		`${BASE}/api/search?query=${encodeURIComponent(query)}&limit=${limit}`,
	);
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

export async function installModel(
	repo: string,
	file: string,
	profile: string,
): Promise<any> {
	const res = await fetch(`${BASE}/api/search/install`, {
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
	const res = await fetch(`${BASE}/api/inventory`);
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

export async function fetchStatus(): Promise<StatusResponse> {
	const res = await fetch(`${BASE}/api/status`);
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

// --- Model Management ---

export async function fetchModelDetail(family: string): Promise<any> {
	const res = await fetch(
		`${BASE}/api/models/${encodeURIComponent(family)}/detail`,
	);
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

export async function editModel(family: string, edits: any): Promise<any> {
	const res = await fetch(`${BASE}/api/models/${encodeURIComponent(family)}`, {
		method: "PUT",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(edits),
	});
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

export async function deleteModels(repos: string[]): Promise<DeleteResponse> {
	const res = await fetch(`${BASE}/api/models/delete`, {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({ repos }),
	});
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

// --- HF Card ---

export async function fetchHFCard(repo: string): Promise<HFCardResponse> {
	const res = await fetch(
		`${BASE}/api/hfcard?repo=${encodeURIComponent(repo)}`,
	);
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

// --- Init ---

export async function initTarget(target: string): Promise<any> {
	const res = await fetch(`${BASE}/api/init`, {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({ target }),
	});
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}
