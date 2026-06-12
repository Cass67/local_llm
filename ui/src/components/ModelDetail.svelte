<script lang="ts">
	import { onMount } from "svelte";
	import { fetchModelDetail } from "../lib/api";

	let { family, onClose }: { family: string; onClose: () => void } = $props();
	let data: any = $state(null);
	let error = $state("");
	let loading = $state(true);

	onMount(async () => {
		try {
			data = await fetchModelDetail(family);
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
	});
</script>

<div
	class="modal-overlay"
	role="button"
	tabindex="0"
	onclick={(e) => { if (e.target === e.currentTarget) onClose(); }}
	onkeydown={(e) => { if (e.key === "Escape") onClose(); }}
>
	<div class="modal" role="dialog" aria-modal="true">
		<div class="modal-header">
			<h3>Model Detail: {family}</h3>
			<button onclick={onClose}>✕</button>
		</div>
		<div class="modal-body">
			{#if loading}
				<p>Loading...</p>
			{:else if error}
				<div class="error">{error}</div>
			{:else if data}
				<div class="grid">
					<div><span>Repo</span><code>{data.repo || data.hf_repo || "-"}</code></div>
					<div><span>Alias</span><code>{data.alias || "-"}</code></div>
					<div><span>Quant</span><code>{data.quant || data.config?.quant || "-"}</code></div>
					<div><span>Profile</span><code>{data.profile || "-"}</code></div>
					<div><span>Backend</span><code>{data.config?.backend || data.backend || "-"}</code></div>
					<div><span>Ctx</span><code>{data.config?.ctx || data.context || "-"}</code></div>
					<div><span>Launcher</span><code>{data.launcher_file || data.remote_start || "-"}</code></div>
				</div>
				<h4>Raw Metadata</h4>
				<pre>{JSON.stringify(data, null, 2)}</pre>
			{/if}
		</div>
	</div>
</div>

<style>
	.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.7); display: flex; align-items: center; justify-content: center; z-index: 100; }
	.modal { background: var(--bg-card); border: 1px solid var(--border); border-radius: 8px; width: 90%; max-width: 900px; max-height: 85vh; display: flex; flex-direction: column; }
	.modal-header { display: flex; justify-content: space-between; align-items: center; padding: 0.7rem 1rem; border-bottom: 1px solid var(--border); }
	.modal-header h3 { margin: 0; }
	.modal-header button { background: none; border: none; color: var(--text-muted); cursor: pointer; font-size: 1.2rem; }
	.modal-body { overflow-y: auto; padding: 1rem; }
	.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 0.7rem; }
	.grid div { background: var(--bg); padding: 0.5rem; border-radius: 4px; }
	span { display: block; color: var(--text-muted); font-size: 0.75rem; margin-bottom: 0.2rem; }
	code { word-break: break-all; }
	pre { background: var(--bg); padding: 0.7rem; border-radius: 4px; overflow-x: auto; font-size: 0.8rem; }
	.error { color: var(--red); }
</style>
