import { writable } from "svelte/store";
import { installModel, searchModels } from "./api";
import type {
	InstallErrorDetail,
	InstallResult,
	SearchCandidate,
	SearchResponse,
} from "./types";

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
	installStatus: Record<string, "installed" | string | InstallErrorDetail>;
}

interface SearchApi {
	searchModels: (query: string, limit?: number) => Promise<SearchResponse>;
	installModel: (
		repo: string,
		file: string,
		profile: string,
	) => Promise<InstallResult>;
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
	installStatus: {},
};

export function createSearchStore(api: SearchApi) {
	const state = writable<SearchState>({ ...initialState });
	const installs = new Map<string, Promise<void>>();

	function patch(update: Partial<SearchState>) {
		state.update((current) => ({ ...current, ...update }));
	}

	return {
		state,
		setQuery: (query: string) => patch({ query }),
		setFilter: (filter: string) => patch({ filter, page: 1 }),
		setSortMode: (sortMode: SortMode) => patch({ sortMode, page: 1 }),
		setPage: (page: number) => patch({ page }),
		async search() {
			let query = "";
			state.update((current) => {
				query = current.query.trim();
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
				const result = await api.searchModels(query);
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
			}));
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
						const { [candidate.repo]: _done, ...installingRepos } =
							current.installingRepos;
						return { ...current, installingRepos };
					});
				});
			installs.set(candidate.repo, promise);
			return promise;
		},
	};
}

export const searchStore = createSearchStore({ searchModels, installModel });
