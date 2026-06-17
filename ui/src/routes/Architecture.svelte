<script lang="ts">
	import { onMount } from "svelte";
	import type { GpuInfo, ClusterInfo, Backend, ModelInfo } from "../lib/types";
	import {
		fetchGpus,
		fetchClusters,
		createCluster,
		deleteCluster,
		startOnCluster,
		stopCluster,
		fetchModels,
	} from "../lib/api";

	let gpus = $state<GpuInfo[]>([]);
	let clusters = $state<ClusterInfo[]>([]);
	let models = $state<ModelInfo[]>([]);
	let gpuError = $state("");
	let clusterError = $state("");
	let loadingGpus = $state(false);
	let busy = $state<Record<string, boolean>>({});

	// create form
	let newName = $state("");
	let newBackend = $state<Backend>("rocm");
	let selectedPcis = $state<Set<string>>(new Set());

	// start form per cluster
	let startFamily = $state<Record<string, string>>({});
	let startProfile = $state<Record<string, string>>({});

	async function loadGpus() {
		loadingGpus = true;
		gpuError = "";
		try {
			const data = await fetchGpus();
			gpus = data.gpus;
		} catch (e: any) {
			gpuError = e.message;
		} finally {
			loadingGpus = false;
		}
	}

	async function loadClusters() {
		try {
			const data = await fetchClusters();
			clusters = data.clusters;
			for (const c of clusters) {
				if (!startFamily[c.id]) startFamily[c.id] = "";
				if (!startProfile[c.id]) startProfile[c.id] = "reliable";
			}
		} catch (e: any) {
			clusterError = e.message;
		}
	}

	async function loadModels() {
		try {
			const data = await fetchModels();
			models = data.models;
		} catch {
			// non-fatal
		}
	}

	onMount(() => {
		loadGpus();
		loadClusters();
		loadModels();
	});

	function togglePci(pci: string) {
		const s = new Set(selectedPcis);
		if (s.has(pci)) s.delete(pci);
		else s.add(pci);
		selectedPcis = s;
	}

	async function handleCreate() {
		if (!newName.trim() || selectedPcis.size === 0) return;
		clusterError = "";
		try {
			await createCluster({
				name: newName.trim(),
				gpu_pci_ids: [...selectedPcis],
				backend: newBackend,
			});
			newName = "";
			selectedPcis = new Set();
			await loadClusters();
		} catch (e: any) {
			clusterError = e.message;
		}
	}

	async function handleDelete(id: string) {
		clusterError = "";
		busy = { ...busy, [id]: true };
		try {
			await deleteCluster(id);
			await loadClusters();
		} catch (e: any) {
			clusterError = e.message;
		} finally {
			const b = { ...busy };
			delete b[id];
			busy = b;
		}
	}

	async function handleStart(id: string) {
		const family = startFamily[id];
		if (!family) return;
		clusterError = "";
		busy = { ...busy, [id]: true };
		try {
			await startOnCluster(id, family, startProfile[id] || "reliable");
			await loadClusters();
		} catch (e: any) {
			clusterError = e.message;
		} finally {
			const b = { ...busy };
			delete b[id];
			busy = b;
		}
	}

	async function handleStop(id: string) {
		clusterError = "";
		busy = { ...busy, [id]: true };
		try {
			await stopCluster(id);
			await loadClusters();
		} catch (e: any) {
			clusterError = e.message;
		} finally {
			const b = { ...busy };
			delete b[id];
			busy = b;
		}
	}

	function vramLabel(mb: number | null) {
		if (mb == null) return "?";
		return mb >= 1024 ? `${Math.round(mb / 1024)}GB` : `${mb}MB`;
	}

	function backendIndex(g: GpuInfo, backend: Backend) {
		if (backend === "rocm") return g.rocm_index;
		if (backend === "cuda") return g.cuda_index;
		return g.vulkan_index;
	}
</script>

<div class="arch">
	<h2>Architecture</h2>

	<!-- GPU Inventory -->
	<section>
		<div class="section-head">
			<h3>GPU Inventory</h3>
			<button onclick={loadGpus} disabled={loadingGpus}>
				{loadingGpus ? "Detecting…" : "Detect"}
			</button>
		</div>
		{#if gpuError}<p class="error">{gpuError}</p>{/if}
		{#if gpus.length === 0 && !loadingGpus}
			<p class="muted">No GPUs detected yet — click Detect.</p>
		{:else}
			<table>
				<thead>
					<tr>
						<th>GPU</th>
						<th>VRAM</th>
						<th>ROCm</th>
						<th>CUDA</th>
						<th>Vulkan</th>
						<th>PCI ID</th>
					</tr>
				</thead>
				<tbody>
					{#each gpus as g}
						<tr>
							<td>{g.model_name}</td>
							<td>{vramLabel(g.vram_mb)}</td>
							<td>{g.rocm_index ?? "—"}</td>
							<td>{g.cuda_index ?? "—"}</td>
							<td>{g.vulkan_index ?? "—"}</td>
							<td class="mono">{g.pci_id}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		{/if}
	</section>

	<!-- Create Cluster -->
	<section>
		<h3>Create Cluster</h3>
		{#if gpus.length > 0}
			<div class="create-form">
				<input bind:value={newName} placeholder="Cluster name" />
				<select bind:value={newBackend}>
					<option value="rocm">ROCm</option>
					<option value="vulkan">Vulkan</option>
					<option value="cuda">CUDA</option>
				</select>
				<div class="gpu-picks">
					{#each gpus as g}
						<label class="gpu-pick" class:selected={selectedPcis.has(g.pci_id)}>
							<input
								type="checkbox"
								checked={selectedPcis.has(g.pci_id)}
								onchange={() => togglePci(g.pci_id)}
							/>
							{g.model_name} ({vramLabel(g.vram_mb)})
							{#if backendIndex(g, newBackend) != null}
								<span class="idx">idx {backendIndex(g, newBackend)}</span>
							{/if}
						</label>
					{/each}
				</div>
				<button
					onclick={handleCreate}
					disabled={!newName.trim() || selectedPcis.size === 0}
				>
					Create
				</button>
			</div>
		{:else}
			<p class="muted">Detect GPUs first.</p>
		{/if}
	</section>

	<!-- Cluster List -->
	<section>
		<h3>Clusters</h3>
		{#if clusterError}<p class="error">{clusterError}</p>{/if}
		{#if clusters.length === 0}
			<p class="muted">No clusters defined.</p>
		{:else}
			{#each clusters as c}
				<div class="cluster-card" class:running={c.active?.running}>
					<div class="cluster-head">
						<span class="cluster-name">{c.name}</span>
						<span class="badge badge-{c.backend}">{c.backend}</span>
						<span class="muted">:{c.port}</span>
						{#if c.active?.running}
							<span class="badge badge-running">running</span>
						{/if}
					</div>

					<div class="cluster-gpus">
						{#each c.gpu_pci_ids as pci}
							{@const g = gpus.find((x) => x.pci_id === pci)}
							<span class="gpu-tag">{g ? g.model_name : pci}</span>
						{/each}
					</div>

					{#if c.active?.running}
						<div class="cluster-active">
							<span>Model: <strong>{c.active.model ?? "unknown"}</strong></span>
							<span class="muted">profile: {c.active.profile}</span>
							<button
								class="btn-stop"
								onclick={() => handleStop(c.id)}
								disabled={busy[c.id]}
							>
								{busy[c.id] ? "Stopping…" : "Stop"}
							</button>
						</div>
					{:else}
						<div class="cluster-start">
							<select bind:value={startFamily[c.id]}>
								<option value="">— pick model —</option>
								{#each models.filter((m) => m.backend === c.backend) as m}
									<option value={m.family}>{m.label ?? m.model_name ?? m.family}</option>
								{/each}
							</select>
							<select bind:value={startProfile[c.id]}>
								<option value="reliable">reliable</option>
								<option value="fast">fast</option>
								<option value="quality">quality</option>
							</select>
							<button
								onclick={() => handleStart(c.id)}
								disabled={!startFamily[c.id] || busy[c.id]}
							>
								{busy[c.id] ? "Starting…" : "Start"}
							</button>
							<button
								class="btn-del"
								onclick={() => handleDelete(c.id)}
								disabled={busy[c.id]}
							>
								Delete
							</button>
						</div>
					{/if}
				</div>
			{/each}
		{/if}
	</section>
</div>

<style>
	.arch {
		max-width: 900px;
		margin: 0 auto;
	}
	section {
		margin-bottom: 2rem;
	}
	.section-head {
		display: flex;
		align-items: center;
		gap: 1rem;
	}
	h3 {
		margin: 0 0 0.75rem;
	}
	.section-head h3 {
		margin: 0;
	}
	table {
		width: 100%;
		border-collapse: collapse;
		font-size: 0.9rem;
	}
	th,
	td {
		padding: 0.4rem 0.6rem;
		text-align: left;
		border-bottom: 1px solid var(--border);
	}
	th {
		color: var(--text-muted);
		font-weight: normal;
	}
	.mono {
		font-family: monospace;
		font-size: 0.8rem;
		color: var(--text-muted);
	}
	.create-form {
		display: flex;
		flex-wrap: wrap;
		gap: 0.5rem;
		align-items: flex-start;
	}
	.create-form input {
		padding: 0.3rem 0.5rem;
		background: var(--bg-card);
		border: 1px solid var(--border);
		color: var(--text);
		border-radius: 4px;
	}
	.create-form select {
		padding: 0.3rem 0.5rem;
		background: var(--bg-card);
		border: 1px solid var(--border);
		color: var(--text);
		border-radius: 4px;
	}
	.gpu-picks {
		display: flex;
		flex-direction: column;
		gap: 0.3rem;
		width: 100%;
	}
	.gpu-pick {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		cursor: pointer;
		padding: 0.3rem 0.5rem;
		border-radius: 4px;
		border: 1px solid var(--border);
	}
	.gpu-pick.selected {
		border-color: var(--accent, #6c8ebf);
		background: color-mix(in srgb, var(--accent, #6c8ebf) 10%, transparent);
	}
	.idx {
		color: var(--text-muted);
		font-size: 0.8rem;
		margin-left: auto;
	}
	.cluster-card {
		border: 1px solid var(--border);
		border-radius: 6px;
		padding: 0.75rem 1rem;
		margin-bottom: 0.75rem;
		background: var(--bg-card);
	}
	.cluster-card.running {
		border-color: #4caf50;
	}
	.cluster-head {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		margin-bottom: 0.5rem;
	}
	.cluster-name {
		font-weight: bold;
	}
	.cluster-gpus {
		display: flex;
		flex-wrap: wrap;
		gap: 0.3rem;
		margin-bottom: 0.5rem;
	}
	.gpu-tag {
		background: var(--bg);
		border: 1px solid var(--border);
		border-radius: 3px;
		padding: 0.15rem 0.4rem;
		font-size: 0.8rem;
	}
	.cluster-active,
	.cluster-start {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		flex-wrap: wrap;
	}
	.cluster-start select {
		padding: 0.25rem 0.4rem;
		background: var(--bg);
		border: 1px solid var(--border);
		color: var(--text);
		border-radius: 4px;
		font-size: 0.85rem;
	}
	.badge {
		font-size: 0.7rem;
		padding: 0.15rem 0.4rem;
		border-radius: 3px;
		font-weight: bold;
		text-transform: uppercase;
	}
	.badge-rocm {
		background: #c13333;
		color: #fff;
	}
	.badge-vulkan {
		background: #b84a00;
		color: #fff;
	}
	.badge-cuda {
		background: #4a7c59;
		color: #fff;
	}
	.badge-running {
		background: #4caf50;
		color: #fff;
	}
	.btn-stop {
		background: #c13333;
		color: #fff;
		border: none;
		border-radius: 4px;
		padding: 0.25rem 0.6rem;
		cursor: pointer;
		font-size: 0.85rem;
	}
	.btn-del {
		background: transparent;
		color: var(--text-muted);
		border: 1px solid var(--border);
		border-radius: 4px;
		padding: 0.25rem 0.6rem;
		cursor: pointer;
		font-size: 0.85rem;
	}
	button:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
	.error {
		color: #e57373;
	}
	.muted {
		color: var(--text-muted);
		font-size: 0.9rem;
	}
</style>
