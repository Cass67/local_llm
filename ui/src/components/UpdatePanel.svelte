<script lang="ts">
	import { onMount, onDestroy } from "svelte";
	import {
		fetchUpdateStatus,
		startRunnerBuild,
		fetchBuildStatus,
		fetchCommitDetail,
		fetchAgentsUpdateStatus,
		startAgentsBuild,
		fetchServiceUpdates,
		startServiceUpdate,
	} from "../lib/api";
	import type {
		UpdateStatus,
		BuildStatus,
		CommitDetail,
		AgentsUpdateStatus,
		ServiceUpdate,
	} from "../lib/types";

	let status: UpdateStatus | null = $state(null);
	let build: BuildStatus | null = $state(null);
	let checking = $state(false);
	let starting = $state(false);
	let error = $state("");
	let selected: Record<string, boolean> = $state({});
	let showCommits = $state(false);
	let detailSha: string | null = $state(null);
	let detail: CommitDetail | null = $state(null);
	let detailError = $state("");
	let pollId: ReturnType<typeof setInterval> | null = null;

	let agents: AgentsUpdateStatus | null = $state(null);
	let agentsError = $state("");
	let agentsStarting = $state(false);

	let jobsRunning = $derived.by(
		() => new Set((build?.jobs ?? []).filter((j) => j.running).map((j) => j.id)),
	);

	let services: ServiceUpdate[] = $state([]);
	let servicesError = $state("");
	let serviceStarting = $state("");

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
		await checkAgents();
		await checkServices();
	}

	async function checkServices() {
		servicesError = "";
		try {
			services = (await fetchServiceUpdates()).services;
		} catch (e: unknown) {
			servicesError = e instanceof Error ? e.message : String(e);
		}
	}

	async function updateService(id: string) {
		serviceStarting = id;
		servicesError = "";
		try {
			await startServiceUpdate(id);
			await pollBuild();
			startPolling();
		} catch (e: unknown) {
			servicesError = e instanceof Error ? e.message : String(e);
		} finally {
			serviceStarting = "";
		}
	}

	async function checkAgents() {
		agentsError = "";
		try {
			agents = await fetchAgentsUpdateStatus();
		} catch (e: unknown) {
			agentsError = e instanceof Error ? e.message : String(e);
		}
	}

	async function rebuildAgents() {
		agentsStarting = true;
		agentsError = "";
		try {
			await startAgentsBuild();
			await pollBuild();
			startPolling();
		} catch (e: unknown) {
			agentsError = e instanceof Error ? e.message : String(e);
		} finally {
			agentsStarting = false;
		}
	}

	async function pollBuild() {
		try {
			const was = [...jobsRunning];
			build = await fetchBuildStatus();
			// Jobs are independent, so refresh each one's versions as it lands rather
			// than waiting for the slowest build to finish.
			const done = was.filter((id) => !jobsRunning.has(id));
			if (done.includes("agents")) await checkAgents();
			if (done.some((id) => services.some((s) => s.id === id))) await checkServices();
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

	async function openCommit(sha: string) {
		detailSha = sha;
		detail = null;
		detailError = "";
		try {
			const d = await fetchCommitDetail(sha);
			if (detailSha === sha) detail = d;
		} catch (e: unknown) {
			if (detailSha === sha) detailError = e instanceof Error ? e.message : String(e);
		}
	}

	function closeCommit() {
		detailSha = null;
		detail = null;
		detailError = "";
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
			Upstream master:
			<button class="sha" onclick={() => status && openCommit(status.latest.sha)}>{status.latest.sha.slice(0, 12)}</button>
			· {status.latest.message}
			· <span class="muted">{fmtDate(status.latest.date)}</span>
		</div>

		<table>
			<thead><tr><th></th><th>Backend</th><th>Image</th><th>Built commit</th><th>Behind</th></tr></thead>
			<tbody>
				{#each status.backends as b}
					<tr>
						<td><input type="checkbox" bind:checked={selected[b.backend]} disabled={jobsRunning.has("runners")} /></td>
						<td>{b.backend}</td>
						<td><code>{b.image}</code>{#if !b.present}<span class="missing"> (not built)</span>{/if}</td>
						<td>
							{#if b.commit}<button class="sha" onclick={() => openCommit(b.commit!)}>{b.commit}</button>
							{:else}unknown{/if}
						</td>
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
						<button class="commit" onclick={() => openCommit(c.sha)} title="Show details">
							<code>{c.sha.slice(0, 8)}</code>
							<span class="msg">{c.message}</span>
							<span class="muted">{c.author} · {fmtDate(c.date)}</span>
						</button>
					{/each}
				</div>
			{/if}
		{/if}

		<div class="actions">
			<button class="rebuild" onclick={rebuild} disabled={starting || jobsRunning.has("runners")}>
				{jobsRunning.has("runners") ? "Build running…" : starting ? "Starting…" : "Update & rebuild selected"}
			</button>
			<span class="muted">Running models keep the old image until relaunched.</span>
		</div>
	{/if}

	{#if agentsError}
		<div class="error">{agentsError}</div>
	{/if}

	{#if agents}
		<div class="agents">
			<h3>Coding agents</h3>
			<div class="muted">
				<code>{agents.image}</code>{#if !agents.present}<span class="missing"> (not built)</span>{/if}
			</div>
			<table>
				<thead><tr><th>Agent</th><th>Package</th><th>Installed</th><th>Latest</th><th></th></tr></thead>
				<tbody>
					{#each agents.packages as p}
						<tr>
							<td>{p.id}</td>
							<td><code>{p.package}</code></td>
							<td>{p.current ?? "unknown"}</td>
							<td>{p.latest ?? "?"}</td>
							<td>
								{#if p.outdated}<span class="behind">update available</span>
								{:else if p.current && p.latest}<span class="uptodate">up to date</span>
								{:else}-{/if}
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
			<div class="actions">
				<button class="rebuild" onclick={rebuildAgents} disabled={agentsStarting || jobsRunning.has("agents")}>
					{jobsRunning.has("agents")
						? "Build running…"
						: agentsStarting
							? "Starting…"
							: "Update & rebuild agents"}
				</button>
				<span class="muted">Rebuilds at the latest npm releases, then restarts pi and opencode (running sessions are lost).</span>
			</div>
		</div>
	{/if}

	{#if servicesError}
		<div class="error">{servicesError}</div>
	{/if}

	{#if services.length > 0}
		<div class="agents">
			<h3>Chat &amp; tracing</h3>
			<table>
				<thead><tr><th>Service</th><th>Image</th><th>Installed</th><th>Latest</th><th></th><th></th></tr></thead>
				<tbody>
					{#each services as s}
						<tr>
							<td>{s.name}</td>
							<td>
								<code>{s.image}</code>{#if !s.present}<span class="missing"> (not built)</span>{/if}
							</td>
							<td>{s.current ?? "unknown"}</td>
							<td>{s.latest ?? "?"}</td>
							<td>
								{#if s.outdated}
									<span class="behind">{s.behind != null ? `${s.behind} commits behind` : "update available"}</span>
								{:else if s.current && s.latest}<span class="uptodate">up to date</span>
								{:else}-{/if}
								{#if s.note}<span class="muted"> · {s.note}</span>{/if}
							</td>
							<td>
								<button onclick={() => updateService(s.id)} disabled={jobsRunning.has(s.id)}>
									{#if jobsRunning.has(s.id)}Building…
									{:else if serviceStarting === s.id}Starting…
									{:else if s.kind === "pull"}Pull &amp; restart
									{:else}Rebuild &amp; restart{/if}
								</button>
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
			<span class="muted">Each restarts its container at the new image; chat sessions and traces are kept in volumes.</span>
		</div>
	{/if}

	{#each build?.jobs ?? [] as job}
		<div class="build-status">
			<div>
				{#if job.running}
					<strong>Building {job.current ?? "…"}</strong> ({job.targets.join(", ")})
				{:else}
					<strong>Last {job.id} build:</strong>
					{#each Object.entries(job.results) as [target, code]}
						<span class={code === 0 ? "uptodate" : "behind"}> {target}: {code === 0 ? "ok" : `failed (${code})`}</span>
					{/each}
				{/if}
			</div>
			{#if job.log_tail}
				<pre>{job.log_tail}</pre>
			{/if}
		</div>
	{/each}
</div>

<svelte:window onkeydown={(e) => e.key === "Escape" && closeCommit()} />

{#if detailSha}
	<!-- svelte-ignore a11y_click_events_have_key_events -->
	<div class="overlay" role="presentation" onclick={closeCommit}>
		<!-- svelte-ignore a11y_click_events_have_key_events -->
		<div class="modal" role="dialog" aria-modal="true" tabindex="-1" onclick={(e) => e.stopPropagation()}>
			<div class="modal-head">
				<code>{detailSha.slice(0, 12)}</code>
				<button class="link" onclick={closeCommit}>✕</button>
			</div>
			{#if detailError}
				<div class="error">{detailError}</div>
			{:else if !detail}
				<div class="muted">Loading…</div>
			{:else}
				<h4>{detail.subject}</h4>
				<div class="muted">
					{detail.author} · {fmtDate(detail.date)}
					· <a href={detail.url} target="_blank" rel="noreferrer">view on GitHub</a>
					{#if detail.stats.additions != null}
						· <span class="uptodate">+{detail.stats.additions}</span>
						<span class="behind">−{detail.stats.deletions}</span>
					{/if}
				</div>
				{#if detail.body}<pre class="msgbody">{detail.body}</pre>{/if}

				{#if detail.pull}
					<div class="pr">
						<div>
							<strong>PR #{detail.pull.number}</strong> {detail.pull.title}
							<span class="muted">
								· {detail.pull.user}
								· {detail.pull.merged_at ? "merged" : detail.pull.state}
								· <a href={detail.pull.url} target="_blank" rel="noreferrer">open</a>
							</span>
						</div>
						{#if detail.pull.body}<pre class="msgbody">{detail.pull.body}</pre>{/if}
						{#each detail.pull.comments as c}
							<div class="comment">
								<div class="muted">
									{c.user} · {fmtDate(c.date)}{#if c.path} · <code>{c.path}</code>{/if}
								</div>
								<pre class="msgbody">{c.body}</pre>
							</div>
						{/each}
						{#if detail.pull.comments.length === 0}
							<div class="muted">No discussion on the PR.</div>
						{/if}
					</div>
				{:else}
					<div class="muted">No pull request found for this commit (pushed directly).</div>
				{/if}

				{#if detail.files.length > 0}
					<div class="files">
						<div class="muted">{detail.files.length} files changed</div>
						{#each detail.files as f}
							<div class="file">
								<code class="msg">{f.filename}</code>
								<span class="muted">{f.status}</span>
								<span class="uptodate">+{f.additions}</span>
								<span class="behind">−{f.deletions}</span>
							</div>
						{/each}
					</div>
				{/if}
			{/if}
		</div>
	</div>
{/if}

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
	.commit { display: flex; gap: 0.5rem; align-items: baseline; border: none; background: none; padding: 0.1rem 0.2rem; text-align: left; font: inherit; color: inherit; border-radius: 4px; }
	.commit:hover { background: var(--bg-hover, #ffffff14); }
	.commit .msg { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.sha { border: none; background: none; padding: 0; font-family: monospace; font-size: 0.8rem; color: var(--accent); text-decoration: underline; }
	.overlay { position: fixed; inset: 0; background: #000000aa; display: flex; align-items: center; justify-content: center; z-index: 50; padding: 2rem; }
	.modal { background: var(--bg-card); border: 1px solid var(--border); border-radius: 8px; padding: 1rem; width: min(820px, 100%); max-height: 80vh; overflow-y: auto; display: flex; flex-direction: column; gap: 0.6rem; font-size: 0.85rem; text-align: left; }
	.modal h4 { margin: 0; }
	.modal-head { display: flex; justify-content: space-between; align-items: center; }
	.msgbody { background: var(--bg); border: 1px solid var(--border); border-radius: 4px; padding: 0.5rem; white-space: pre-wrap; word-break: break-word; max-height: 260px; overflow: auto; font-size: 0.78rem; margin: 0; }
	.pr, .files { display: flex; flex-direction: column; gap: 0.4rem; border-top: 1px solid var(--border); padding-top: 0.6rem; }
	.comment { display: flex; flex-direction: column; gap: 0.2rem; }
	.file { display: flex; gap: 0.5rem; align-items: baseline; font-size: 0.78rem; }
	.file .msg { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.actions { display: flex; align-items: center; gap: 0.75rem; }
	.agents { display: flex; flex-direction: column; gap: 0.5rem; border-top: 1px solid var(--border); padding-top: 0.75rem; }
	.agents h3 { margin: 0; }
	.build-status { display: flex; flex-direction: column; gap: 0.4rem; font-size: 0.85rem; }
	pre { background: #000; border: 1px solid var(--border); border-radius: 4px; padding: 0.5rem; max-height: 240px; overflow: auto; font-size: 0.7rem; margin: 0; }
</style>
