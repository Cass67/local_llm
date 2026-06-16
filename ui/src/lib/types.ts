export type Backend = "rocm" | "vulkan" | "cuda";

export interface MtpConfig {
	enabled: boolean;
	draft_n_max: number;
	draft_n_min: number;
	draft_p_min: number;
}

export interface ModelConfig {
	quant?: string;
	batch: number;
	ubatch: number;
	ngl: number;
	visible_devices?: string;
	split_mode?: string;
	tensor_split?: string;
	mtp?: MtpConfig;
}

export interface ModelInfo {
	family: string;
	alias: string;
	model_name: string;
	profile: string;
	context?: number;
	backend: Backend;
	reasoning: boolean;
	config: ModelConfig;
	running: boolean;
	downloaded: boolean;
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
	native_process_warning: boolean;
	llama_server: { status: string };
}

export interface SwitchRequest {
	family: string;
	profile: string;
	backend?: Backend;
}

export interface SwitchResponse {
	status: string;
	family: string;
	profile: string;
	alias: string;
	backend: string;
}

export interface CopyBackendResponse {
	status: string;
	family: string;
	backend: Backend;
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

export interface InstallErrorDetail {
	status: "error";
	phase?: string;
	repo?: string;
	file?: string;
	profile?: string;
	detail: string;
	logs?: string[];
}

export type InstallResult =
	| { status: "installed"; family?: string; alias?: string; path?: string }
	| InstallErrorDetail;

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

export interface StatsResponse {
	model?: string;
	predicted_per_second?: number;
	prompt_per_second?: number;
	draft_n?: number;
	draft_n_accepted?: number;
}

export interface DeleteResponse {
	results: Array<{ repo: string; status: string }>;
}

export interface HFCardResponse {
	markdown: string;
	error: boolean;
}

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
	status: string;
	error: string | null;
	created_at: string;
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

export interface ChatMetric {
	id: number;
	ts: number;
	model: string | null;
	predicted_per_second: number | null;
	prompt_per_second: number | null;
	draft_n: number | null;
	draft_n_accepted: number | null;
}

export interface RunnerHealth {
	error?: string;
	// llama.cpp /health fields
	status?: string;
	slots_idle?: number;
	slots_processing?: number;
}

export interface BenchmarkRunFilters {
	endpoint_id?: number | "";
	model?: string;
	prompt_id?: number | "";
	status?: string;
	from_date?: string;
	to_date?: string;
	limit?: number;
	offset?: number;
}
