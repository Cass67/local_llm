export interface ModelConfig {
	quant?: string;
	batch: number;
	ubatch: number;
	ngl: number;
	visible_devices?: string;
	split_mode?: string;
	tensor_split?: string;
}

export interface ModelInfo {
	family: string;
	alias: string;
	model_name: string;
	profile: string;
	context?: number;
	backend: "rocm" | "vulkan";
	reasoning: boolean;
	config: ModelConfig;
	launcher_file?: string;
	running: boolean;
}

export interface ModelListResponse {
	models: ModelInfo[];
}

export interface CurrentModelResponse {
	family: string;
	profile: string;
	alias: string;
	backend: string;
	running: boolean;
	llama_server: { status: string };
}

export interface SwitchRequest {
	family: string;
	profile: string;
	backend?: "rocm" | "vulkan";
}

export interface SwitchResponse {
	status: string;
	family: string;
	profile: string;
	alias: string;
	backend: string;
}

export interface SearchCandidate {
	repo: string;
	score: number;
	best_quant: string;
	best_file: string;
}

export interface SearchResponse {
	candidates: SearchCandidate[];
	error: string | null;
}

export interface InventoryModel {
	repo: string;
	path: string;
	file: string;
	disk_gb: string;
	gguf: string;
}

export interface StatusResponse {
	target: string;
	running: { status: string; family: string | null; ctx: number | null };
	accepted_count: number;
	default_set: boolean;
	downloads: Array<{ pid: string; repo: string }>;
}

export interface DeleteResponse {
	results: Array<{ repo: string; status: string }>;
}

export interface HFCardResponse {
	markdown: string;
	error: boolean;
}
