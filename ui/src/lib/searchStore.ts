import { writable } from "svelte/store";
import { installModel, searchModels } from "./api";
import type {
	InstallErrorDetail,
	InstallResult,
	SearchCandidate,
	SearchResponse,
} from "./types";

export interface DownloadProgress {
	downloaded: number;
	total: number;
	speed: number;
}

export type SortMode = "score" | "repo" | "quant";

export interface SearchState {
	query: string;
	filter: string;
	candidates: SearchCandidate[];
	searching: boolean;
	error: string;
	sortMode: SortMode;
	page: number;
	installingRepos: Record<string, true>;
	installingFiles: Record<string, string>;
	installStatus: Record<string, "installed" | string | InstallErrorDetail>;
	vramGb: number | null;
	downloadProgress: Record<string, DownloadProgress>;
}

interface SearchApi {
	searchModels: (
		query: string,
		limit?: number,
		vramGb?: number,
	) => Promise<SearchResponse>;
	installModel: (
		repo: string,
		file: string,
		profile: string,
	) => Promise<InstallResult>;
	fetchDownloadProgress: () => Promise<Record<string, DownloadProgress>>;
}

interface SearchStore {
	state: ReturnType<typeof writable<SearchState>>;
	setQuery: (query: string) => void;
	setFilter: (filter: string) => void;
	setSortMode: (sortMode: SortMode) => void;
	setPage: (page: number) => void;
	search: (targetVramGb?: number) => Promise<void>;
	install: (candidate: SearchCandidate, profile: string) => Promise<void>;
}

const initialState: SearchState = {
	query: "coding gguf",
	filter: "",
	candidates: [],
	searching: false,
	error: "",
	sortMode: "score",
	page: 1,
	installingRepos: {},
	installingFiles: {},
	installStatus: {},
	vramGb: null,
	downloadProgress: {},
};

export function createSearchStore(api: SearchApi): SearchStore {
	const state = writable<SearchState>({ ...initialState });
	const installs = new Map<string, Promise<void>>();
	let progressInterval: ReturnType<typeof setInterval> | null = null;

	function patch(update: Partial<SearchState>) {
		state.update((current) => ({ ...current, ...update }));
	}

	function startProgressPoll() {
		if (progressInterval) return;
		progressInterval = setInterval(async () => {
			try {
				const progress = await api.fetchDownloadProgress();
				patch({ downloadProgress: progress });
			} catch {
				// ignore poll failures
			}
		}, 800);
	}

	function stopProgressPoll() {
		if (progressInterval) {
			clearInterval(progressInterval);
			progressInterval = null;
		}
		patch({ downloadProgress: {} });
	}

	return {
		state,
		setQuery: (query: string) => patch({ query }),
		setFilter: (filter: string) => patch({ filter, page: 1 }),
		setSortMode: (sortMode: SortMode) => patch({ sortMode, page: 1 }),
		setPage: (page: number) => patch({ page }),
		async search(targetVramGb?: number) {
			let query = "";
			let vramGb: number | null = null;
			state.update((current) => {
				query = current.query.trim();
				vramGb = targetVramGb ?? current.vramGb;
				if (!query) return current;
				return {
					...current,
					searching: true,
					error: "",
					candidates: [],
					page: 1,
				};
			});
			if (!query) return;
			try {
				const result = await api.searchModels(query, 30, vramGb ?? undefined);
				state.update((current) => ({
					...current,
					candidates: result.candidates,
					error: result.error || "",
				}));
			} catch (e: unknown) {
				patch({ error: e instanceof Error ? e.message : String(e) });
			} finally {
				patch({ searching: false });
			}
		},
		install(candidate: SearchCandidate, profile: string) {
			const existing = installs.get(candidate.repo);
			if (existing) return existing;
			state.update((current) => ({
				...current,
				installingRepos: { ...current.installingRepos, [candidate.repo]: true },
				installingFiles: { ...current.installingFiles, [candidate.repo]: candidate.best_file },
			}));
			startProgressPoll();
			const promise = api
				.installModel(candidate.repo, candidate.best_file, profile)
				.then((result) => {
					state.update((current) => ({
						...current,
						installStatus: {
							...current.installStatus,
							[candidate.repo]:
								result.status === "error" ? result : "installed",
						},
					}));
				})
				.catch((e: unknown) => {
					state.update((current) => ({
						...current,
						installStatus: {
							...current.installStatus,
							[candidate.repo]: e instanceof Error ? e.message : "failed",
						},
					}));
				})
				.finally(() => {
					installs.delete(candidate.repo);
					state.update((current) => {
						const { [candidate.repo]: _done, ...installingRepos } = current.installingRepos;
						const { [candidate.repo]: _file, ...installingFiles } = current.installingFiles;
						return { ...current, installingRepos, installingFiles };
					});
					if (installs.size === 0) stopProgressPoll();
				});
			installs.set(candidate.repo, promise);
			return promise;
		},
	};
}

async function fetchDownloadProgress(): Promise<Record<string, DownloadProgress>> {
	const res = await fetch("/api/local-llm/search/progress");
	if (!res.ok) return {};
	const data = await res.json();
	return data.progress ?? {};
}

export const searchStore = createSearchStore({ searchModels, installModel, fetchDownloadProgress });
