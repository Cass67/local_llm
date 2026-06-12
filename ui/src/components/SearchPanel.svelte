<script lang="ts">
	import { fetchHFCard } from "../lib/api";
	import { installStatusView } from "../lib/installStatus";
	import { searchStore } from "../lib/searchStore";
	import type { SearchCandidate } from "../lib/types";

	type InstallErrorDetail = {
		status: "error";
		phase?: string;
		repo?: string;
		file?: string;
		profile?: string;
		detail: string;
		logs?: string[];
	};
	type InstallStatus = "installed" | string | InstallErrorDetail;

	const searchState = searchStore.state;
	let perPage = 15;
	let hfCardRepo: string | null = $state(null);
	let hfCardMarkdown = $state("");
	let hfCardLoading = $state(false);
	let installErrorDetail: InstallErrorDetail | null = $state(null);

	let filtered = $derived(
		$searchState.filter
			? $searchState.candidates.filter(
					(c) =>
						c.repo.toLowerCase().includes($searchState.filter.toLowerCase()) ||
						c.best_quant.toLowerCase().includes($searchState.filter.toLowerCase()),
				)
			: $searchState.candidates,
	);

	function getSorted(): SearchCandidate[] {
		const arr = [...filtered];
		if ($searchState.sortMode === "score") arr.sort((a, b) => b.score - a.score);
		else if ($searchState.sortMode === "repo") arr.sort((a, b) => a.repo.localeCompare(b.repo));
		else arr.sort((a, b) => a.best_quant.localeCompare(b.best_quant));
		return arr;
	}

	let sorted = $derived(getSorted());
	let totalPages = $derived(Math.max(1, Math.ceil(sorted.length / perPage)));
	let paged = $derived(sorted.slice(($searchState.page - 1) * perPage, $searchState.page * perPage));
	let baseIdx = $derived(($searchState.page - 1) * perPage);
	let latestInstallError = $derived(getLatestInstallError());

	async function doSearch() {
		await searchStore.search();
	}

	async function doInstall(candidate: SearchCandidate) {
		await searchStore.install(candidate, "balanced");
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
		searchStore.setSortMode(modes[(modes.indexOf($searchState.sortMode) + 1) % modes.length]);
	}

	function getStatus(repo: string): InstallStatus | undefined {
		return $searchState.installStatus[repo];
	}

	function getStatusView(status: InstallStatus) {
		if (typeof status === "object") {
			const prefix = status.phase ? `${status.phase}: ` : "";
			return { label: "✗ Failed", reason: `${prefix}${status.detail}` };
		}
		return installStatusView(status);
	}

	function isInstallError(status: InstallStatus | undefined): status is InstallErrorDetail {
		return typeof status === "object" && status?.status === "error";
	}

	function getLatestInstallError(): InstallErrorDetail | null {
		let latest: InstallErrorDetail | null = null;
		for (const status of Object.values($searchState.installStatus) as InstallStatus[]) {
			if (isInstallError(status)) latest = status;
		}
		return latest;
	}
</script>

<div class="search-panel">
	<div class="search-bar">
		<input
			type="text"
			value={$searchState.query}
			oninput={(e) => searchStore.setQuery(e.currentTarget.value)}
			placeholder="Search models (e.g. qwen coding gguf)"
			onkeydown={(e) => e.key === "Enter" && doSearch()}
			disabled={$searchState.searching}
		/>
		<button onclick={doSearch} disabled={$searchState.searching || !$searchState.query.trim()}>
			{$searchState.searching ? "Searching..." : "Search"}
		</button>
	</div>

	{#if $searchState.error}
		<div class="error">{$searchState.error}</div>
	{/if}

	{#if latestInstallError}
		<div class="install-error-card">
			<strong>Install failed</strong>
			<span>{getStatusView(latestInstallError).reason}</span>
			<button onclick={() => (installErrorDetail = latestInstallError)}>Details</button>
		</div>
	{/if}

	{#if $searchState.candidates.length > 0}
		<div class="toolbar">
			<input type="text" value={$searchState.filter} oninput={(e) => searchStore.setFilter(e.currentTarget.value)} placeholder="Filter by repo/quant" />
			<button onclick={cycleSort}>Sort: {$searchState.sortMode}</button>
			<button onclick={() => searchStore.setPage(Math.max(1, $searchState.page - 1))} disabled={$searchState.page <= 1}>← Prev</button>
			<span class="page-info">{$searchState.page}/{totalPages} ({sorted.length})</span>
			<button onclick={() => searchStore.setPage(Math.min(totalPages, $searchState.page + 1))} disabled={$searchState.page >= totalPages}>Next →</button>
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
					{@const statusView = status ? getStatusView(status) : null}
					<tr>
						<td>{idx + 1}</td>
						<td class="repo-cell" title={candidate.repo}>{candidate.repo}</td>
						<td class="score">{candidate.score}</td>
						<td><code>{candidate.best_quant}</code></td>
						<td class="actions">
							{#if statusView?.label === "✓ Installed"}
								<span class="installed">{statusView.label}</span>
							{:else if statusView}
								<span class="err" title={statusView.reason}>{statusView.label}: <span class="fail-reason">{statusView.reason}</span></span>
								{#if isInstallError(status)}
									<button class="details-btn" onclick={() => (installErrorDetail = status)}>Details</button>
								{/if}
							{:else if $searchState.installingRepos[candidate.repo]}
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
	{:else if !$searchState.searching && $searchState.query}
		<div class="empty">No results. Try a different query.</div>
	{/if}
</div>

{#if installErrorDetail}
	<div
		class="modal-overlay"
		role="button"
		tabindex="0"
		onclick={(e) => { if (e.target === e.currentTarget) installErrorDetail = null; }}
		onkeydown={(e) => { if (e.key === "Escape") installErrorDetail = null; }}
	>
		<div class="modal" role="dialog" aria-modal="true">
			<div class="modal-header">
				<h3>Install failed: {installErrorDetail.repo ?? "unknown repo"}</h3>
				<button onclick={() => (installErrorDetail = null)}>✕</button>
			</div>
			<div class="modal-body">
				<dl class="error-details">
					<dt>Phase</dt><dd>{installErrorDetail.phase ?? "unknown"}</dd>
					<dt>File</dt><dd>{installErrorDetail.file ?? "unknown"}</dd>
					<dt>Profile</dt><dd>{installErrorDetail.profile ?? "unknown"}</dd>
					<dt>Error</dt><dd>{installErrorDetail.detail}</dd>
				</dl>
				{#if installErrorDetail.logs?.length}
					<h4>Install log</h4>
					<pre>{installErrorDetail.logs.join("\n")}</pre>
				{/if}
			</div>
		</div>
	</div>
{/if}

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
	.card-btn, .details-btn { padding: 0.2rem 0.5rem; background: var(--bg); color: var(--text-muted); border: 1px solid var(--border); border-radius: 3px; cursor: pointer; font-size: 0.75rem; }
	.installed { color: var(--green); font-size: 0.8rem; }
	.installing { color: var(--yellow); font-size: 0.8rem; }
	.err { color: var(--red); font-size: 0.8rem; max-width: 360px; display: inline-block; }
	.fail-reason { color: var(--text-muted); }
	.empty { text-align: center; color: var(--text-muted); padding: 2rem; }
	.error { background: var(--red); color: white; padding: 0.5rem; border-radius: 4px; }
	.install-error-card { display: flex; align-items: center; gap: 0.75rem; background: #f443361a; border: 1px solid var(--red); color: var(--text); padding: 0.75rem; border-radius: 6px; }
	.install-error-card span { flex: 1; color: var(--text-muted); }
	.install-error-card button { padding: 0.25rem 0.6rem; background: var(--red); color: white; border: none; border-radius: 3px; cursor: pointer; }
	.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.7); display: flex; align-items: center; justify-content: center; z-index: 100; }
	.modal { background: var(--bg-card); border: 1px solid var(--border); border-radius: 8px; width: 90%; max-width: 800px; max-height: 80vh; display: flex; flex-direction: column; }
	.modal-header { display: flex; justify-content: space-between; align-items: center; padding: 0.5rem 1rem; border-bottom: 1px solid var(--border); }
	.modal-header h3 { margin: 0; font-size: 0.9rem; }
	.modal-header button { background: none; border: none; color: var(--text-muted); cursor: pointer; font-size: 1.2rem; }
	.modal-body { flex: 1; overflow-y: auto; padding: 1rem; }
	.modal-body pre { white-space: pre-wrap; word-break: break-word; font-size: 0.8rem; line-height: 1.5; }
	.error-details { display: grid; grid-template-columns: max-content 1fr; gap: 0.4rem 0.75rem; font-size: 0.85rem; }
	.error-details dt { color: var(--text-muted); }
	.error-details dd { margin: 0; word-break: break-word; }
</style>
