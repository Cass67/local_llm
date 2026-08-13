<script lang="ts">
	import { onMount } from "svelte";

	let currentRoute = $state(location.hash.replace("#", "") || "/architecture");

	onMount(() => {
		function update() {
			currentRoute = location.hash.replace("#", "") || "/architecture";
		}
		window.addEventListener("hashchange", update);
		return () => window.removeEventListener("hashchange", update);
	});
</script>

<header>
	<h1>local_llm</h1>
	<nav>
		<a href="#/architecture" class:active={currentRoute === "/architecture"}>Architecture</a>
		<a href="#/models" class:active={currentRoute === "/models"}>Models</a>
		<a href="#/profiles" class:active={currentRoute === "/profiles"}>Profiles</a>
		<a href="#/search" class:active={currentRoute === "/search"}>Search</a>
		<a href="#/status" class:active={currentRoute === "/status"}>Status</a>
		<a href="#/benchmarks" class:active={currentRoute === "/benchmarks"}>Benchmarks</a>
		<a href="#/tuning" class:active={currentRoute === "/tuning"}>Tuning</a>
		<a href="#/coding" class:active={currentRoute === "/coding"}>Coding</a>
		<a href="/chat/">Chat</a>
		<a href="/traces/" target="_blank" rel="noreferrer">Traces</a>
		<a href="/metrics/" target="_blank" rel="noreferrer">Metrics</a>
		<a href="#/logs" class:active={currentRoute === "/logs"}>Logs</a>
	</nav>
</header>

<style>
	header {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.5rem;
		padding: 0.5rem 1rem;
		background: color-mix(in srgb, var(--bg-card), transparent 20%);
		backdrop-filter: blur(12px);
		-webkit-backdrop-filter: blur(12px);
		border-bottom: 1px solid var(--border);
		position: sticky;
		top: 0;
		z-index: 10;
	}
	h1 { margin: 0; font-size: 1.2rem; }
	nav { display: flex; flex-wrap: wrap; gap: 1rem; }
	a { color: var(--text-muted); text-decoration: none; }
	a.active { color: var(--text); font-weight: bold; }
</style>
