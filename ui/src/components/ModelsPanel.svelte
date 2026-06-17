<script lang="ts">
	import { onMount } from "svelte";
	import { fetchModels, fetchCurrentModel, fetchClusters, startOnCluster, copyModelBackend } from "../lib/api";
	import type { Backend, ModelInfo, CurrentModelResponse, ClusterInfo } from "../lib/types";
	import ModelCard from "./ModelCard.svelte";
	import ModelDetail from "./ModelDetail.svelte";
	import EditModelForm from "./EditModelForm.svelte";
	import DeletePanel from "./DeletePanel.svelte";

	let models: ModelInfo[] = $state([]);
	let current: CurrentModelResponse | null = $state(null);
	let clusters: ClusterInfo[] = $state([]);
	let startingCluster: string | null = $state(null); // cluster id being started
	let selectedBackend: Backend = $state("rocm");
	let error: string = $state("");
	let loading: boolean = $state(true);
	let detailFamily: string | null = $state(null);
	let editFamily: string | null = $state(null);
	let deleteOpen = $state(false);

	async function load() {
		loading = true;
		error = "";
		try {
			const [modelData, currentData, clusterData] = await Promise.all([
				fetchModels(),
				fetchCurrentModel(),
				fetchClusters(),
			]);
			models = modelData.models;
			current = currentData;
			clusters = clusterData.clusters;
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
	}

	async function handleCopyBackend(family: string, backend: Backend) {
		error = "";
		try {
			await copyModelBackend(family, backend);
			selectedBackend = backend;
			await load();
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : String(e);
		}
	}

	async function handleStartOnCluster(family: string, clusterId: string, profile: string) {
		startingCluster = clusterId;
		error = "";
		try {
			await startOnCluster(clusterId, family, profile);
			await load();
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			startingCluster = null;
		}
	}

	onMount(load);

	let filteredModels = $derived(models.filter((m) => m.backend === selectedBackend));

	function clustersFor(model: ModelInfo) {
		return clusters.filter((c) => c.backend === model.backend);
	}

	function runningClusterIdsFor(model: ModelInfo): string[] {
		return (current?.instances ?? [])
			.filter((i) => i.family === model.family || i.model === model.alias)
			.map((i) => i.cluster_id);
	}
</script>

<div class="models-panel">
	{#if error}<div class="error">{error}</div>{/if}

	<div class="toolbar">
		<div class="backend-toggle">
			<button class:active={selectedBackend === "rocm"} onclick={() => (selectedBackend = "rocm")}>ROCm</button>
			<button class:active={selectedBackend === "vulkan"} onclick={() => (selectedBackend = "vulkan")}>Vulkan</button>
			<button class:active={selectedBackend === "cuda"} onclick={() => (selectedBackend = "cuda")}>CUDA</button>
		</div>
		<div class="toolbar-actions">
			<button class="delete" onclick={() => (deleteOpen = true)}>Delete</button>
			<button class="refresh" onclick={load} disabled={loading}>{loading ? "Loading..." : "Refresh"}</button>
		</div>
	</div>

	{#if current?.native_process_warning}
		<div class="native-warning">
			⚠ A native llama-server process is running on port 8080 outside the container runner. Stop it: <code>kill $(lsof -ti :8080)</code>
		</div>
	{/if}

	{#if current?.instances && current.instances.length > 0}
		<div class="instances-bar">
			{#each current.instances as inst}
				<span class="inst-chip">
					<span class="inst-dot"></span>
					{inst.model} <span class="inst-meta">on {inst.cluster_name} ({inst.backend})</span>
				</span>
			{/each}
		</div>
	{/if}

	<div class="model-grid">
		{#each filteredModels as model (model.family + "-" + model.backend)}
			<ModelCard
				{model}
				runningClusterIds={runningClusterIdsFor(model)}
				clusters={clustersFor(model)}
				starting={startingCluster !== null && clustersFor(model).some((c) => c.id === startingCluster)}
				onStartOnCluster={(clusterId, profile) => handleStartOnCluster(model.family, clusterId, profile)}
				onCopyBackend={(backend) => handleCopyBackend(model.family, backend)}
				onDetail={() => (detailFamily = model.family)}
				onEdit={() => (editFamily = model.family)}
			/>
		{/each}
	</div>

	{#if filteredModels.length === 0 && !loading}<div class="empty">No models accepted yet. Use Search to install.</div>{/if}
</div>

{#if detailFamily}<ModelDetail family={detailFamily} onClose={() => (detailFamily = null)} />{/if}
{#if editFamily}<EditModelForm family={editFamily} {clusters} onClose={() => (editFamily = null)} onSaved={load} onStartOnCluster={(cid, profile) => handleStartOnCluster(editFamily!, cid, profile)} />{/if}
{#if deleteOpen}<DeletePanel onClose={() => (deleteOpen = false)} onDeleted={load} />{/if}

<style>
	.models-panel { display: flex; flex-direction: column; gap: 1rem; }
	.error { background: var(--red); color: white; padding: 0.5rem; border-radius: 4px; }
	.native-warning { background: #f59e0b22; border: 1px solid #f59e0b66; color: #f59e0b; padding: 0.6rem 1rem; border-radius: 8px; font-size: 0.85rem; }
	.native-warning code { background: #0004; padding: 0.1rem 0.3rem; border-radius: 4px; font-size: 0.82rem; }
	.toolbar { display: flex; justify-content: space-between; align-items: center; gap: 1rem; }
	.toolbar-actions { display: flex; gap: 0.5rem; }
	.backend-toggle { display: flex; gap: 0; }
	.backend-toggle button {
		padding: 0.3rem 0.8rem;
		border: 1px solid var(--border);
		background: var(--bg-card);
		color: var(--text-muted);
		cursor: pointer;
		font-size: 0.85rem;
		transition: all 0.1s;
	}
	.backend-toggle button:first-child { border-radius: 6px 0 0 6px; }
	.backend-toggle button:last-child { border-radius: 0 6px 6px 0; }
	.backend-toggle button.active {
		background: var(--accent);
		color: var(--text);
		border-color: var(--accent);
		font-weight: bold;
	}
	.refresh, .delete {
		padding: 0.3rem 0.8rem;
		border: 1px solid var(--border);
		background: var(--bg-card);
		color: var(--text);
		cursor: pointer;
		border-radius: 6px;
		font-size: 0.85rem;
		transition: all 0.1s;
	}
	.refresh:hover { border-color: var(--text-muted); }
	.delete { background: #ef44441a; color: var(--red); border-color: #ef444433; }
	.delete:hover { background: #ef444433; }
	.instances-bar {
		display: flex;
		flex-wrap: wrap;
		gap: 0.5rem;
		padding: 0.5rem 0.75rem;
		background: var(--bg);
		border: 1px solid var(--border);
		border-radius: 8px;
		font-size: 0.85rem;
	}
	.inst-chip {
		display: flex;
		align-items: center;
		gap: 0.4rem;
	}
	.inst-dot {
		display: inline-block;
		width: 7px;
		height: 7px;
		border-radius: 50%;
		background: var(--green);
		box-shadow: 0 0 6px var(--green);
	}
	.inst-meta { color: var(--text-muted); }
	.model-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 1.2rem; }
	.empty { text-align: center; color: var(--text-muted); padding: 3rem; }
</style>
