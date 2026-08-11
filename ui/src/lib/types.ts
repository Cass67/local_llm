export type Backend = "rocm" | "rocmfp4" | "vulkan" | "cuda";

export interface ModelProfile {
	batch: number;
	ubatch: number;
	ngl: number;
	context: number | null;
	split_mode?: string | null;
	tensor_split?: string | null;
}

export interface FamilyProfiles {
	default: string;
	profiles: Record<string, ModelProfile>;
}

export interface ProfilesData {
	families: Record<string, FamilyProfiles>;
}

export interface ModelConfig {
	quant?: string;
	batch: number;
	ubatch: number;
	ngl: number;
	visible_devices?: string;
	split_mode?: string;
	tensor_split?: string;
	mtp_enabled?: boolean;
	mtp_draft_n_max?: number;
	mtp_draft_n_min?: number;
	mtp_draft_p_min?: number;
	spec_type?: string;
}

export interface ModelInfo {
	family: string;
	alias: string;
	model_name: string;
	label?: string;
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

export interface ActiveInstance {
	cluster_id: string;
	cluster_name: string;
	model: string;
	family: string;
	profile: string;
	backend: string;
	port: number;
}

export interface CurrentModelResponse {
	family: string;
	profile: string;
	alias: string;
	backend: string;
	running: boolean;
	native_process_warning: boolean;
	llama_server: { status: string };
	instances?: ActiveInstance[];
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

export type FitLevel = "perfect" | "good" | "marginal" | "too_tight";

export interface CandidateFile {
	name: string;
	quant: string;
	size_gb: number;
}

export interface SearchCandidate {
	repo: string;
	score: number;
	best_quant: string;
	best_file: string;
	fit_level?: FitLevel;
	memory_required_gb?: number;
	memory_available_gb?: number;
	size_class?: string;
	params_b?: number | null;
	all_files?: CandidateFile[];
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
	running_clusters: Array<{ cluster_name: string; family: string; profile: string; backend: string }>;
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
	ts?: number;
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
	psu_avg_w?: number | null;
	psu_peak_w?: number | null;
	gpu_avg_w?: number | null;
	tps_per_watt?: number | null;
	profile?: string | null;
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

export interface GpuInfo {
	pci_id: string;
	vendor: string;
	model_name: string;
	vram_mb: number | null;
	rocm_index: number | null;
	cuda_index: number | null;
	vulkan_index: number | null;
}

export interface ClusterActive {
	model: string | null;
	family: string | null;
	label: string | null;
	profile: string | null;
	running: boolean;
	warnings?: StartupWarning[];
}

export interface ClusterInfo {
	id: string;
	name: string;
	gpu_pci_ids: string[];
	backend: Backend;
	port: number;
	container_name: string;
	active: ClusterActive | null;
	desired: { family: string; profile: string } | null;
	startup: ClusterStartup | null;
}

export interface ClusterStartup {
	stage: "stopping" | "creating" | "loading" | "ready" | "failed";
	detail: string;
	model: string;
	profile: string;
	elapsed_s: number;
	error: string | null;
}

export interface RouterRule {
	name: string;
	keywords: string[];
	cluster?: string;
	model?: string;
	fallback?: string[];
}

export interface RouterConfig {
	backend_url: string;
	default_model: string | null;
	health_check_interval_s: number;
	enabled: boolean;
	prefer_idle?: boolean;
	shadow?: boolean;
	cluster_remap?: Record<string, string>;
	rules: RouterRule[];
}

export interface RouterHealth {
	running: boolean;
	detail?: string;
	healthy_models?: string[];
	cluster_map?: Record<string, string>;
	default_model?: string;
}

export interface IdleUnloadConfig {
	enabled: boolean;
	timeout_minutes: number;
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

export interface UpdateBackendStatus {
	backend: string;
	image: string;
	present: boolean;
	commit: string | null;
	behind: number | null;
}

export interface UpdateCommit {
	sha: string;
	message: string;
	date: string;
	author: string;
}

export interface UpdateStatus {
	latest: { sha: string; message: string; date: string };
	backends: UpdateBackendStatus[];
	commits: UpdateCommit[];
}

export interface CommitDetail {
	sha: string;
	url: string;
	subject: string;
	body: string;
	author: string;
	date: string;
	stats: { additions?: number; deletions?: number; total?: number };
	files: { filename: string; status: string; additions: number; deletions: number }[];
	pull: {
		number: number;
		title: string;
		body: string;
		url: string;
		state: string;
		merged_at: string | null;
		user: string;
		comments: { user: string; body: string; date: string; path: string | null }[];
	} | null;
}

export interface BuildStatus {
	running: boolean;
	backends: string[];
	current: string | null;
	started: number | null;
	results: Record<string, number>;
	log_tail: string;
}

// --- GPU status (fdinfo) ---

export interface GpuEngineSample {
	engine_busy: number | null;
	mem_busy?: number | null;
	per_engine: Record<string, number>;
	vram_bytes: number;
	vram_human: string;
	clients: number;
}

export interface GpuRunnerStatus {
	cluster_id: string | null;
	cluster_name: string;
	container: string;
	split_config: {
		split_mode?: string;
		tensor_split?: string;
		ngl?: string;
		parallel?: string;
	};
	gpus: Record<string, GpuEngineSample>;
	aggregate_gpu_equiv: number | null;
	gpu_count: number;
	verdict: string;
}

export interface GpuDeviceMetrics {
	pci_id: string;
	gpu_busy_percent: number | null;
	mem_busy_percent: number | null;
	vram_used: number | null;
	vram_total: number | null;
	temp_c: number | null;
	junction_temp_c: number | null;
	power_w: number | null;
	power_cap_w: number | null;
	fan_rpm: number | null;
	fan_pct: number | null;
	sclk: string | null;
	mclk: string | null;
}

export interface SystemMetrics {
	ts?: number;
	cpu_percent?: number | null;
	cpu_cores?: number[];
	cpu_count?: number | null;
	load?: number[];
	mem_total?: number | null;
	mem_used?: number | null;
	swap_total?: number | null;
	swap_used?: number | null;
	cpu_temp_c?: number;
	fan_rpms?: number[];
	psu_power_w?: number;
}

export interface GpuStatusResponse {
	ts: number;
	error?: string;
	runners: GpuRunnerStatus[];
	devices?: GpuDeviceMetrics[];
	system?: SystemMetrics;
}

// --- Profile lint ---

export interface LintFinding {
	level: "error" | "warn";
	field: string;
	message: string;
}

export interface VramEstimate {
	weights_mb: number;
	kv_mb: number;
	compute_mb: number;
	total_mb: number;
	n_layers: number;
	ctx: number;
}

export interface ProfileLintResponse {
	lint: LintFinding[];
	vram_estimate: VramEstimate | null;
	vram_available_mb: number | null;
}

export interface SaveProfileResponse {
	status: string;
	restarted_clusters: string[];
	lint: LintFinding[];
}

// --- Startup warnings ---

export interface StartupWarning {
	id: string;
	message: string;
	line: string;
}

// --- Sweep ---

export interface SweepResult {
	index: number;
	combo: Record<string, unknown>;
	status: "ok" | "error" | "skipped";
	error?: string;
	lint?: LintFinding[];
	reload_s?: number;
	decode_tps?: number | null;
	prompt_tps?: number | null;
	wall_s?: number | null;
	completion_tokens?: number | null;
	psu_avg_w?: number | null;
	psu_peak_w?: number | null;
	gpu_avg_w?: number | null;
	tps_per_watt?: number | null;
	quality?: QualityReport;
	quality_gate?: string;
	sample_text?: string;
}

export interface SweepSnapshot {
	id: string;
	status: "pending" | "running" | "done" | "error" | "cancelled";
	error: string | null;
	family: string;
	cluster_id: string;
	base_profile: string;
	objective: string;
	grid: Record<string, unknown[]>;
	total: number;
	completed: number;
	started_at: number;
	finished_at: number | null;
	results: SweepResult[];
	best: SweepResult | null;
}

export interface SweepListEntry {
	id: string;
	status: string;
	family: string;
	completed: number;
	total: number;
	started_at: number;
}

// --- Quality ---

export interface QualityCaseResult {
	id: string;
	passed: boolean;
	failures: string[];
	words: number;
	repetition_ratio: number;
	sample?: string;
	judge_score?: number | null;
}

export interface QualityReport {
	cases: QualityCaseResult[];
	passed: number;
	total: number;
	pass_rate: number;
	judge_mean: number | null;
	model?: string;
	profile?: string;
}

// --- Regression guard ---

export interface RegressionEntry {
	cluster_id: string;
	cluster_name: string;
	family: string;
	profile: string;
	baseline_tps: number | null;
	baseline_commit: string | null;
	decode_tps?: number | null;
	prompt_tps?: number | null;
	verdict: "baseline" | "ok" | "improved" | "regressed" | "unmeasured";
	delta_pct: number | null;
	error?: string;
	warnings?: StartupWarning[];
}

export interface RegressionReport {
	ts: number;
	commit: string;
	threshold_pct: number;
	clusters: RegressionEntry[];
	regressions: RegressionEntry[];
}

export interface RegressionResponse {
	report: RegressionReport | null;
	baselines: Record<string, { decode_tps: number; commit: string; ts: number }>;
}

// --- Router decision log ---

export interface RouteDecision {
	ts: number;
	prompt: string;
	dispatched: string;
	reason?: string;
	rule?: string;
	matched_keyword?: string;
	shadow?: boolean;
	would_route_to?: string;
	would_differ?: boolean;
	busy_primary?: string;
}

export interface RouteLogResponse {
	entries: RouteDecision[];
	total: number;
	shadow: boolean;
	shadow_would_differ: number;
	shadow_total: number;
	detail?: string;
}
