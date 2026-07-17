<script lang="ts">
	import { onMount, onDestroy } from "svelte";
	import { fetchUpdateStatus, startRunnerBuild, fetchBuildStatus } from "../lib/api";
	import type { UpdateStatus, BuildStatus } from "../lib/types";

	let status: UpdateStatus | null = $state(null);
	let build: BuildStatus | null = $state(null);
	let checking = $state(false);
	let starting = $state(false);
	let error = $state("");
	let selected: Record<string, boolean> = $state({});
	let showCommits = $state(false);
	let pollId: ReturnType<typeof setInterval> | null = null;

	async function check() {
		checking = true;
		error = "";
		try {
			status = await fetchUpdateStatus();
			for (const b of status.backends) {
				if (!(b.backend in selected)) selected[b.backend] = b.present;
			}
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			checking = false;
		}
	}

	async function pollBuild() {
		try {
			build = await fetchBuildStatus();
			if (!build.running && pollId) {
				clearInterval(pollId);
				pollId = null;
			}
		} catch {
			// backend briefly unreachable; keep polling
		}
	}

	function startPolling() {
		if (!pollId) pollId = setInterval(pollBuild, 3000);
	}

	async function rebuild() {
		const backends = Object.keys(selected).filter((b) => selected[b]);
		if (backends.length === 0) return;
		starting = true;
		error = "";
		try {
			await startRunnerBuild(backends);
			await pollBuild();
			startPolling();
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			starting = false;
		}
	}

	function fmtDate(iso: string): string {
		return new Date(iso).toLocaleString();
	}

	onMount(async () => {
		await pollBuild();
		if (build?.running) startPolling();
	});
	onDestroy(() => {
		if (pollId) clearInterval(pollId);
	});
</script>

<div class="update-panel">
	<div class="header">
		<h3>llama.cpp Updates</h3>
		<button onclick={check} disabled={checking}>{checking ? "Checking…" : "Check for updates"}</button>
	</div>

	{#if error}
		<div class="error">{error}</div>
	{/if}

	{#if status}
		<div class="latest">
			Upstream master: <code>{status.latest.sha.slice(0, 12)}</code>
			· {status.latest.message}
			· <span class="muted">{fmtDate(status.latest.date)}</span>
		</div>

		<table>
			<thead><tr><th></th><th>Backend</th><th>Image</th><th>Built commit</th><th>Behind</th></tr></thead>
			<tbody>
				{#each status.backends as b}
					<tr>
						<td><input type="checkbox" bind:checked={selected[b.backend]} disabled={build?.running} /></td>
						<td>{b.backend}</td>
						<td><code>{b.image}</code>{#if !b.present}<span class="missing"> (not built)</span>{/if}</td>
						<td>{b.commit ?? "unknown"}</td>
						<td>
							{#if b.behind === 0}<span class="uptodate">up to date</span>
							{:else if b.behind != null}<span class="behind">{b.behind} commits</span>
							{:else}-{/if}
						</td>
					</tr>
				{/each}
			</tbody>
		</table>

		{#if status.commits.length > 0}
			<button class="link" onclick={() => (showCommits = !showCommits)}>
				{showCommits ? "▾" : "▸"} {status.commits.length} recent upstream commits
			</button>
			{#if showCommits}
				<div class="commits">
					{#each status.commits as c}
						<div class="commit">
							<code>{c.sha.slice(0, 8)}</code>
							<span class="msg">{c.message}</span>
							<span class="muted">{c.author} · {fmtDate(c.date)}</span>
						</div>
					{/each}
				</div>
			{/if}
		{/if}

		<div class="actions">
			<button class="rebuild" onclick={rebuild} disabled={starting || build?.running}>
				{build?.running ? "Build running…" : starting ? "Starting…" : "Update & rebuild selected"}
			</button>
			<span class="muted">Running models keep the old image until relaunched.</span>
		</div>
	{/if}

	{#if build && (build.running || Object.keys(build.results).length > 0)}
		<div class="build-status">
			<div>
				{#if build.running}
					<strong>Building {build.current ?? "…"}</strong> ({build.backends.join(", ")})
				{:else}
					<strong>Last build:</strong>
					{#each Object.entries(build.results) as [backend, code]}
						<span class={code === 0 ? "uptodate" : "behind"}> {backend}: {code === 0 ? "ok" : `failed (${code})`}</span>
					{/each}
				{/if}
			</div>
			{#if build.log_tail}
				<pre>{build.log_tail}</pre>
			{/if}
		</div>
	{/if}
</div>

<style>
	.update-panel { display: flex; flex-direction: column; gap: 0.75rem; background: var(--bg-card); border: 1px solid var(--border); border-radius: 8px; padding: 1rem; }
	.header { display: flex; justify-content: space-between; align-items: center; }
	.header h3 { margin: 0; }
	button { padding: 0.3rem 0.6rem; border: 1px solid var(--border); background: var(--bg-card); color: var(--text); border-radius: 4px; cursor: pointer; }
	button:disabled { opacity: 0.5; cursor: default; }
	.rebuild { border-color: #3b82f633; background: #3b82f61a; color: #3b82f6; }
	.rebuild:hover:not(:disabled) { background: #3b82f633; }
	.link { border: none; background: none; padding: 0; color: var(--accent); text-align: left; }
	table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
	th, td { padding: 0.4rem; border-bottom: 1px solid var(--border); text-align: left; }
	th { color: var(--text-muted); font-weight: normal; }
	code { font-size: 0.8rem; }
	.latest { font-size: 0.85rem; }
	.muted { color: var(--text-muted); font-size: 0.8rem; }
	.missing { color: var(--text-muted); font-style: italic; }
	.uptodate { color: #4caf50; }
	.behind { color: #f59e0b; }
	.error { background: var(--red); color: white; padding: 0.5rem; border-radius: 4px; }
	.commits { max-height: 260px; overflow-y: auto; display: flex; flex-direction: column; gap: 0.3rem; font-size: 0.8rem; }
	.commit { display: flex; gap: 0.5rem; align-items: baseline; }
	.commit .msg { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.actions { display: flex; align-items: center; gap: 0.75rem; }
	.build-status { display: flex; flex-direction: column; gap: 0.4rem; font-size: 0.85rem; }
	pre { background: #000; border: 1px solid var(--border); border-radius: 4px; padding: 0.5rem; max-height: 240px; overflow: auto; font-size: 0.7rem; margin: 0; }
</style>
