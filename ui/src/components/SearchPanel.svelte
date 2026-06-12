<script lang="ts">
	import {
		searchModels,
		installModel,
		fetchHFCard,
	} from "../lib/api";
	import type { SearchCandidate } from "../lib/types";

	let query = $state("coding gguf");
	let filter = $state("");
	let candidates: SearchCandidate[] = $state([]);
	let searching = $state(false);
	let error = $state("");
	let sortMode: "score" | "repo" | "quant" = $state("score");
	let page = $state(1);
	let perPage = 15;
	let installing: string | null = $state(null);
	let installStatus: Map<string, string> = $state(new Map());
	let hfCardRepo: string | null = $state(null);
	let hfCardMarkdown = $state("");
	let hfCardLoading = $state(false);

	let filtered = $derived(
		filter
			? candidates.filter(
					(c) =>
						c.repo.toLowerCase().includes(filter.toLowerCase()) ||
						c.best_quant.toLowerCase().includes(filter.toLowerCase()),
				)
			: candidates,
	);

	function getSorted(): SearchCandidate[] {
		const arr = [...filtered];
		if (sortMode === "score") arr.sort((a, b) => b.score - a.score);
		else if (sortMode === "repo") arr.sort((a, b) => a.repo.localeCompare(b.repo));
		else arr.sort((a, b) => a.best_quant.localeCompare(b.best_quant));
		return arr;
	}

	let sorted = $derived(getSorted());
	let totalPages = $derived(Math.max(1, Math.ceil(sorted.length / perPage)));
	let paged = $derived(sorted.slice((page - 1) * perPage, page * perPage));
	let baseIdx = $derived((page - 1) * perPage);

	async function doSearch() {
		if (!query.trim()) return;
		searching = true;
		error = "";
		candidates = [];
		page = 1;
		installStatus = new Map();
		try {
			const result = await searchModels(query);
			candidates = result.candidates;
			if (result.error) error = result.error;
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			searching = false;
		}
	}

	async function doInstall(candidate: SearchCandidate) {
		installing = candidate.repo;
		try {
			const result = await installModel(candidate.repo, candidate.best_file, "balanced");
			installStatus = new Map([...installStatus, [candidate.repo, result.status === "error" ? result.detail : "installed"]]);
		} catch (e: unknown) {
			installStatus = new Map([...installStatus, [candidate.repo, e instanceof Error ? e.message : "failed"]]);
		} finally {
			installing = null;
		}
	}

	async function showHFCard(repo: string) {
		hfCardRepo = repo;
		hfCardLoading = true;
		hfCardMarkdown = "";
		try {
			const result = await fetchHFCard(repo);
			hfCardMarkdown = result.markdown;
		} catch {
			hfCardMarkdown = "Failed to load model card.";
		} finally {
			hfCardLoading = false;
		}
	}

	function closeHFCard() {
		hfCardRepo = null;
		hfCardMarkdown = "";
	}

	function cycleSort() {
		const modes: Array<"score" | "repo" | "quant"> = ["score", "repo", "quant"];
		sortMode = modes[(modes.indexOf(sortMode) + 1) % modes.length];
		page = 1;
	}

	function getStatus(repo: string): string | undefined {
		return installStatus.get(repo);
	}
</script>

<div class="search-panel">
	<div class="search-bar">
		<input
			type="text"
			bind:value={query}
			placeholder="Search models (e.g. qwen coding gguf)"
			onkeydown={(e) => e.key === "Enter" && doSearch()}
			disabled={searching}
		/>
		<button onclick={doSearch} disabled={searching || !query.trim()}>
			{searching ? "Searching..." : "Search"}
		</button>
	</div>

	{#if error}
		<div class="error">{error}</div>
	{/if}

	{#if candidates.length > 0}
		<div class="toolbar">
			<input type="text" bind:value={filter} placeholder="Filter by repo/quant" />
			<button onclick={cycleSort}>Sort: {sortMode}</button>
			<button onclick={() => (page = Math.max(1, page - 1))} disabled={page <= 1}>← Prev</button>
			<span class="page-info">{page}/{totalPages} ({sorted.length})</span>
			<button onclick={() => (page = Math.min(totalPages, page + 1))} disabled={page >= totalPages}>Next →</button>
		</div>

		<table>
			<thead>
				<tr>
					<th>#</th>
					<th>Repo</th>
					<th>Score</th>
					<th>Quant</th>
					<th>Actions</th>
				</tr>
			</thead>
			<tbody>
				{#each paged as candidate, i}
					{@const idx = baseIdx + i}
					{@const status = getStatus(candidate.repo)}
					<tr>
						<td>{idx + 1}</td>
						<td class="repo-cell" title={candidate.repo}>{candidate.repo}</td>
						<td class="score">{candidate.score}</td>
						<td><code>{candidate.best_quant}</code></td>
						<td class="actions">
							{#if status === "installed"}
								<span class="installed">✓ Installed</span>
							{:else if status}
								<span class="err" title={status}>✗ Failed</span>
							{:else if installing === candidate.repo}
								<span class="installing">Installing...</span>
							{:else}
								<button class="install-btn" onclick={() => doInstall(candidate)}>Install</button>
							{/if}
							<button class="card-btn" onclick={() => showHFCard(candidate.repo)}>Card</button>
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	{:else if !searching && query}
		<div class="empty">No results. Try a different query.</div>
	{/if}
</div>

{#if hfCardRepo}
	<div
		class="modal-overlay"
		role="button"
		tabindex="0"
		onclick={(e) => { if (e.target === e.currentTarget) closeHFCard(); }}
		onkeydown={(e) => { if (e.key === "Escape") closeHFCard(); }}
	>
		<div class="modal" role="dialog" aria-modal="true">
			<div class="modal-header">
				<h3>{hfCardRepo}</h3>
				<button onclick={closeHFCard}>✕</button>
			</div>
			<div class="modal-body">
				{#if hfCardLoading}
					<p>Loading model card...</p>
				{:else}
					<pre>{hfCardMarkdown}</pre>
				{/if}
			</div>
		</div>
	</div>
{/if}

<style>
	.search-panel { display: flex; flex-direction: column; gap: 0.5rem; }
	.search-bar { display: flex; gap: 0.5rem; }
	.search-bar input { flex: 1; padding: 0.5rem; border: 1px solid var(--border); border-radius: 4px; background: var(--bg-card); color: var(--text); }
	.search-bar button { padding: 0.5rem 1rem; background: var(--accent); color: var(--text); border: none; border-radius: 4px; cursor: pointer; }
	.toolbar { display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; }
	.toolbar input { flex: 1; min-width: 150px; padding: 0.3rem; border: 1px solid var(--border); border-radius: 4px; background: var(--bg-card); color: var(--text); }
	.toolbar button { padding: 0.3rem 0.6rem; border: 1px solid var(--border); background: var(--bg-card); color: var(--text); border-radius: 4px; cursor: pointer; font-size: 0.8rem; }
	.page-info { color: var(--text-muted); font-size: 0.8rem; }
	table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
	th { text-align: left; padding: 0.4rem; border-bottom: 1px solid var(--border); color: var(--text-muted); }
	td { padding: 0.4rem; border-bottom: 1px solid var(--border); }
	.repo-cell { max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.score { color: var(--green); font-weight: bold; }
	code { background: var(--bg); padding: 0.1rem 0.3rem; border-radius: 3px; font-size: 0.8rem; }
	.actions { display: flex; gap: 0.3rem; align-items: center; }
	.install-btn { padding: 0.2rem 0.5rem; background: var(--accent); color: var(--text); border: none; border-radius: 3px; cursor: pointer; font-size: 0.75rem; }
	.card-btn { padding: 0.2rem 0.5rem; background: var(--bg); color: var(--text-muted); border: 1px solid var(--border); border-radius: 3px; cursor: pointer; font-size: 0.75rem; }
	.installed { color: var(--green); font-size: 0.8rem; }
	.installing { color: var(--yellow); font-size: 0.8rem; }
	.err { color: var(--red); font-size: 0.8rem; }
	.empty { text-align: center; color: var(--text-muted); padding: 2rem; }
	.error { background: var(--red); color: white; padding: 0.5rem; border-radius: 4px; }
	.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.7); display: flex; align-items: center; justify-content: center; z-index: 100; }
	.modal { background: var(--bg-card); border: 1px solid var(--border); border-radius: 8px; width: 90%; max-width: 800px; max-height: 80vh; display: flex; flex-direction: column; }
	.modal-header { display: flex; justify-content: space-between; align-items: center; padding: 0.5rem 1rem; border-bottom: 1px solid var(--border); }
	.modal-header h3 { margin: 0; font-size: 0.9rem; }
	.modal-header button { background: none; border: none; color: var(--text-muted); cursor: pointer; font-size: 1.2rem; }
	.modal-body { flex: 1; overflow-y: auto; padding: 1rem; }
	.modal-body pre { white-space: pre-wrap; word-break: break-word; font-size: 0.8rem; line-height: 1.5; }
</style>
