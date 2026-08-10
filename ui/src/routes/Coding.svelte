<script lang="ts">
	import { onMount } from "svelte";

	type Agent = {
		id: string;
		name: string;
		description: string;
		port: number;
		auth: string;
	};

	let agents = $state<Agent[]>([]);
	let workdir = $state("");
	let error = $state("");

	const urlFor = (a: Agent) => `${location.protocol}//${location.hostname}:${a.port}/`;

	onMount(async () => {
		try {
			const res = await fetch("/api/local-llm/agents");
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const data = await res.json();
			agents = data.agents;
			workdir = data.workdir;
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
	});
</script>

<div class="route">
	<h2>Coding</h2>
	<p class="sub">
		Agentic coding in the browser, backed by the router. Both agents edit real files in
		{#if workdir}<code>{workdir}</code>{:else}the mounted directory{/if}.
	</p>

	{#if error}
		<p class="error">Could not load agents: {error}</p>
	{/if}

	<div class="grid">
		{#each agents as agent (agent.id)}
			<a class="card" href={urlFor(agent)} target="_blank" rel="noreferrer">
				<span class="name">{agent.name}</span>
				<span class="desc">{agent.description}</span>
				<span class="meta">:{agent.port} · {agent.auth}</span>
			</a>
		{/each}
	</div>
</div>

<style>
	.sub { color: var(--text-muted); margin: 0 0 1rem; }
	.error { color: var(--danger, #f87171); }
	code { background: var(--bg-card); padding: 0.1rem 0.3rem; border-radius: 4px; }
	.grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
		gap: 1rem;
	}
	.card {
		display: flex;
		flex-direction: column;
		gap: 0.35rem;
		padding: 1rem;
		background: var(--bg-card);
		border: 1px solid var(--border);
		border-radius: 8px;
		text-decoration: none;
		color: var(--text);
	}
	.card:hover { border-color: var(--accent, #60a5fa); }
	.name { font-weight: 600; }
	.desc { color: var(--text-muted); font-size: 0.9rem; }
	.meta { color: var(--text-muted); font-size: 0.8rem; font-family: ui-monospace, monospace; }
</style>
