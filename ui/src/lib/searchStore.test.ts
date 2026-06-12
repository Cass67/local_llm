import { get } from "svelte/store";
import { describe, expect, it } from "vitest";
import { createSearchStore } from "./searchStore";
import type { InstallErrorDetail } from "./types";

function deferred<T>() {
	let resolve!: (value: T) => void;
	let reject!: (reason?: unknown) => void;
	const promise = new Promise<T>((res, rej) => {
		resolve = res;
		reject = rej;
	});
	return { promise, resolve, reject };
}

describe("createSearchStore", () => {
	it("keeps search results in module state after search completes", async () => {
		const store = createSearchStore({
			searchModels: async () => ({
				candidates: [
					{
						repo: "Org/Model-GGUF",
						score: 99,
						best_quant: "Q5_K_M",
						best_file: "model.gguf",
					},
				],
				error: null,
			}),
			installModel: async () => ({ status: "installed" }),
		});

		store.setQuery("qwen coding");
		await store.search();

		const state = get(store.state);
		expect(state.query).toBe("qwen coding");
		expect(state.candidates).toHaveLength(1);
		expect(state.candidates[0].repo).toBe("Org/Model-GGUF");
		expect(state.searching).toBe(false);
	});

	it("keeps structured install error details for modal display", async () => {
		const installError: InstallErrorDetail = {
			status: "error",
			phase: "download",
			repo: "Org/Model-GGUF",
			file: "model.Q5_K_M.gguf",
			profile: "balanced",
			detail:
				"download failed for Org/Model-GGUF / model.Q5_K_M.gguf: HTTP 502 Bad Gateway",
			logs: [
				"install balanced: Org/Model-GGUF / model.Q5_K_M.gguf",
				"download failed: HTTP 502 Bad Gateway",
			],
		};
		const store = createSearchStore({
			searchModels: async () => ({ candidates: [], error: null }),
			installModel: async () => installError,
		});
		const candidate = {
			repo: "Org/Model-GGUF",
			score: 99,
			best_quant: "Q5_K_M",
			best_file: "model.Q5_K_M.gguf",
		};

		await store.install(candidate, "balanced");

		const state = get(store.state);
		expect(state.installStatus["Org/Model-GGUF"]).toBe(installError);
	});

	it("keeps install running in background until promise resolves", async () => {
		const install = deferred<{ status: "installed" }>();
		const store = createSearchStore({
			searchModels: async () => ({ candidates: [], error: null }),
			installModel: async () => install.promise,
		});
		const candidate = {
			repo: "Org/Model-GGUF",
			score: 99,
			best_quant: "Q5_K_M",
			best_file: "model.gguf",
		};

		const installPromise = store.install(candidate, "balanced");
		expect(get(store.state).installingRepos["Org/Model-GGUF"]).toBe(true);
		expect(get(store.state).installStatus["Org/Model-GGUF"]).toBeUndefined();

		install.resolve({ status: "installed" });
		await installPromise;

		expect(get(store.state).installingRepos["Org/Model-GGUF"]).toBeUndefined();
		expect(get(store.state).installStatus["Org/Model-GGUF"]).toBe("installed");
	});
});
