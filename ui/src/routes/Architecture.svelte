<script lang="ts">
	import { onMount } from "svelte";
	import type { GpuInfo, ClusterInfo, Backend, ModelInfo, IdleUnloadConfig, FamilyProfiles } from "../lib/types";
	import {
		fetchGpus,
		fetchClusters,
		createCluster,
		deleteCluster,
		startOnCluster,
		stopCluster,
		fetchModels,
		fetchRouterConfig,
		saveRouterConfig,
		fetchRouterHealth,
		fetchIdleUnload,
		saveIdleUnload,
		fetchAllProfiles,
	} from "../lib/api";
	import type { RouterConfig, RouterRule } from "../lib/types";

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
	let allProfiles = $state<Record<string, FamilyProfiles>>({});

	// idle unload
	let idleCfg = $state<IdleUnloadConfig | null>(null);
	let idleError = $state("");
	let idleSaving = $state(false);

	// router
	let routerCfg = $state<RouterConfig | null>(null);
	let routerHealth = $state<{ running: boolean; cluster_map?: Record<string, string> } | null>(null);
	let routerError = $state("");
	let routerSaving = $state(false);
	let editingRule = $state<RouterRule & { _idx: number } | null>(null);
	let newRule = $state<RouterRule>({ name: "", keywords: [], cluster: "", model: "", fallback: [] });
	let showAddRule = $state(false);
	async function loadRouter() {
		try {
			routerCfg = await fetchRouterConfig();
		} catch (e: any) {
			routerError = e.message;
		}
		// Health check is slow (3s timeout if router offline) — fire separately
		// so config + rules render immediately.
		fetchRouterHealth().then(h => routerHealth = h).catch(() => {
			routerHealth = { running: false };
		});
	}

	async function saveRouter() {
		if (!routerCfg) return;
		routerSaving = true;
		routerError = "";
		try {
			await saveRouterConfig(routerCfg);
			await loadRouter();
		} catch (e: any) {
			routerError = e.message;
		} finally {
			routerSaving = false;
		}
	}

	function toggleRouter() {
		if (!routerCfg) return;
		routerCfg = { ...routerCfg, enabled: !routerCfg.enabled };
		saveRouter();
	}

	let remapFrom = $state("");
	let remapTo = $state("");

	// Unique cluster values currently used in rules (for remap "from" dropdown)
	let ruleClusterValues = $derived([...new Set((routerCfg?.rules ?? []).flatMap(r => [r.cluster, ...(r.fallback ?? [])]).filter(Boolean))].sort());

	function applyRemap() {
		if (!routerCfg || !remapFrom || !remapTo || remapFrom === remapTo) return;
		// Find-replace cluster names in rules
		routerCfg = {
			...routerCfg,
			rules: routerCfg.rules.map(rule => ({
				...rule,
				cluster: rule.cluster === remapFrom ? remapTo : rule.cluster,
				fallback: (rule.fallback ?? []).map(f => f === remapFrom ? remapTo : f),
			})),
		};
		// Clear the separate remap dict too
		routerCfg = { ...routerCfg, cluster_remap: {} };
		remapFrom = "";
		remapTo = "";
		saveRouter();
	}

	function effectiveCluster(name?: string) {
		if (!name) return "—";
		return name;
	}

	function effectiveFallback(fallback?: string[]) {
		return (fallback ?? []).join(", ") || "—";
	}

	function deleteRule(idx: number) {
		if (!routerCfg) return;
		const rules = [...routerCfg.rules];
		rules.splice(idx, 1);
		routerCfg = { ...routerCfg, rules };
		saveRouter();
	}

	function startEditRule(idx: number) {
		if (!routerCfg) return;
		editingRule = { ...routerCfg.rules[idx], _idx: idx };
	}

	function saveEditRule() {
		if (!routerCfg || !editingRule) return;
		const rules = [...routerCfg.rules];
		const { _idx, ...rule } = editingRule;
		rules[_idx] = rule;
		routerCfg = { ...routerCfg, rules };
		editingRule = null;
		saveRouter();
	}

	function addRule() {
		if (!routerCfg || !newRule.name || !newRule.keywords.length || (!newRule.cluster && !newRule.model)) return;
		routerCfg = { ...routerCfg, rules: [...routerCfg.rules, { ...newRule }] };
		newRule = { name: "", keywords: [], cluster: "", model: "", fallback: [] };
		showAddRule = false;
		saveRouter();
	}

	function parseKeywords(s: string): string[] {
		return s.split(",").map((k) => k.trim()).filter(Boolean);
	}

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
				if (!startFamily[c.id]) startFamily[c.id] = c.desired?.family ?? "";
				if (!startProfile[c.id]) startProfile[c.id] = c.desired?.profile ?? "reliable";
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

	async function loadProfiles() {
		try {
			const data = await fetchAllProfiles();
			allProfiles = data.families;
		} catch {
			// non-fatal
		}
	}

	function familyProfileOptions(family: string): string[] {
		const fam = allProfiles[family];
		if (fam && Object.keys(fam.profiles).length > 0) return Object.keys(fam.profiles).sort();
		return ["reliable", "balanced", "speed"];
	}

	function onFamilyChange(cid: string, family: string) {
		startFamily[cid] = family;
		const fam = allProfiles[family];
		startProfile[cid] = fam?.default || familyProfileOptions(family)[0];
	}

	async function loadIdle() {
		try {
			idleCfg = await fetchIdleUnload();
		} catch (e: any) {
			idleError = e.message;
		}
	}

	async function saveIdle() {
		if (!idleCfg) return;
		idleSaving = true;
		try {
			await saveIdleUnload(idleCfg);
		} catch (e: any) {
			idleError = e.message;
		} finally {
			idleSaving = false;
		}
	}

	function toggleIdle() {
		if (!idleCfg) return;
		idleCfg = { ...idleCfg, enabled: !idleCfg.enabled };
		saveIdle();
	}

	function setIdleTimeout(minutes: number) {
		if (!idleCfg) return;
		idleCfg = { ...idleCfg, timeout_minutes: minutes };
		saveIdle();
	}

	onMount(() => {
		Promise.all([loadClusters(), loadModels(), loadRouter(), loadIdle(), loadProfiles()]);
		loadGpus(); // potentially slow hardware detection — runs in parallel but last
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
		if (backend === "rocm" || backend === "rocmfp4") return g.rocm_index;
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
					<option value="rocmfp4">ROCmFP4</option>
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

	<!-- Model Router -->
	<section>
		<div class="section-head">
			<h3>Model Router</h3>
			<span class="router-status" class:online={routerHealth?.running}>
				{routerHealth?.running ? "● online :3200" : "○ offline"}
			</span>
			<button onclick={loadRouter}>Refresh</button>
		</div>

		{#if routerError}<p class="error">{routerError}</p>{/if}

		{#if routerCfg}
			<div class="router-toolbar">
				<label class="toggle-label">
					<input type="checkbox" checked={routerCfg.enabled} onchange={toggleRouter} />
					Routing enabled
				</label>
				<span class="muted">backend: {routerCfg.backend_url}</span>
				{#if routerHealth?.cluster_map && Object.keys(routerHealth.cluster_map).length > 0}
					<span class="muted">
						{Object.entries(routerHealth.cluster_map).map(([k, v]) => `${k} → ${v}`).join(" · ")}
					</span>
				{/if}
			</div>

			{#if clusters.length > 0}
				<div class="remap-row">
					<span class="muted">Replace cluster in rules:</span>
					<select bind:value={remapFrom}>
						<option value="">— from —</option>
						{#each ruleClusterValues as v}
							<option value={v}>{v}</option>
						{/each}
					</select>
					→
					<select bind:value={remapTo}>
						<option value="">— to —</option>
						{#each clusters as c}
							<option value={c.name}>{c.name}</option>
						{/each}
					</select>
					<button onclick={applyRemap} disabled={routerSaving || !remapFrom || !remapTo || remapFrom === remapTo}>Apply</button>
				</div>
			{/if}

			<!-- Rules table -->
			<table class="rules-table">
				<thead>
					<tr>
						<th>Name</th>
						<th>Keywords</th>
						<th>Cluster / Model</th>
						<th>Fallback</th>
						<th></th>
					</tr>
				</thead>
				<tbody>
					{#each routerCfg.rules as rule, i}
						{#if editingRule && editingRule._idx === i}
						<tr class="editing-row">
							<td><input bind:value={editingRule.name} /></td>
							<td><input
								value={editingRule.keywords.join(", ")}
								oninput={(e) => editingRule!.keywords = parseKeywords((e.target as HTMLInputElement).value)}
							/></td>
							<td><select bind:value={editingRule.cluster}>
								<option value="">— cluster —</option>
								{#each clusters as c}
									<option value={c.name}>{c.name}</option>
								{/each}
							</select></td>
							<td><input
								value={(editingRule.fallback ?? []).join(", ")}
								oninput={(e) => editingRule!.fallback = parseKeywords((e.target as HTMLInputElement).value)}
							/></td>
								<td class="rule-actions">
									<button onclick={saveEditRule}>Save</button>
									<button onclick={() => editingRule = null}>Cancel</button>
								</td>
							</tr>
						{:else}
							<tr>
								<td>{rule.name}</td>
								<td class="keywords">{rule.keywords.join(", ")}</td>
								<td class="mono">{rule.cluster ? rule.cluster : (rule.model ?? "—")}</td>
								<td class="mono">{effectiveFallback(rule.fallback)}</td>
								<td class="rule-actions">
									<button onclick={() => startEditRule(i)}>Edit</button>
									<button class="btn-del" onclick={() => deleteRule(i)}>Delete</button>
								</td>
							</tr>
						{/if}
					{/each}
					{#if routerCfg.rules.length === 0}
						<tr><td colspan={5} class="muted" style="text-align:center;padding:1rem">No rules — all requests go to default model</td></tr>
					{/if}
				</tbody>
			</table>

			<!-- Add rule -->
			{#if showAddRule}
				<div class="add-rule-form">
					<input bind:value={newRule.name} placeholder="Rule name" />
					<input
						value={newRule.keywords.join(", ")}
						oninput={(e) => newRule.keywords = parseKeywords((e.target as HTMLInputElement).value)}
						placeholder="keywords, comma separated"
					/>
					<select bind:value={newRule.cluster}>
						<option value="">— cluster —</option>
						{#each clusters as c}
							<option value={c.name}>{c.name}</option>
						{/each}
					</select>
					<select bind:value={newRule.model}>
						<option value="">— model alias —</option>
						{#each models as m}
							<option value={m.alias}>{m.label ?? m.alias}</option>
						{/each}
					</select>
					<input
						value={(newRule.fallback ?? []).join(", ")}
						oninput={(e) => newRule.fallback = parseKeywords((e.target as HTMLInputElement).value)}
						placeholder="fallback clusters (optional)"
					/>
					<button onclick={addRule} disabled={!newRule.name || !newRule.keywords.length || (!newRule.cluster && !newRule.model)}>Add</button>
					<button onclick={() => showAddRule = false}>Cancel</button>
				</div>
			{:else}
				<button class="btn-add-rule" onclick={() => showAddRule = true}>+ Add rule</button>
			{/if}
		{:else}
			<p class="muted">Loading router config…</p>
		{/if}
	</section>

	<!-- Idle Unload -->
	<section>
		<h3>Idle Unload</h3>
		{#if idleError}<p class="error">{idleError}</p>{/if}
		{#if idleCfg}
			<div class="router-toolbar">
				<label class="toggle-label">
					<input
						type="checkbox"
						checked={idleCfg.enabled}
						disabled={idleSaving}
						onchange={toggleIdle}
					/>
					Auto-unload idle models after
				</label>
				<select
					value={idleCfg.timeout_minutes}
					disabled={idleSaving}
					onchange={(e) => setIdleTimeout(Number(e.currentTarget.value))}
				>
					{#each [[5,"5 min"],[10,"10 min"],[15,"15 min"],[30,"30 min"],[60,"1 hr"],[120,"2 hr"]] as [val, label]}
						<option value={val}>{label}</option>
					{/each}
				</select>
				<span class="muted">of no requests</span>
			</div>
		{:else}
			<p class="muted">Loading…</p>
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
							<select
								value={startFamily[c.id]}
								onchange={(e) => onFamilyChange(c.id, e.currentTarget.value)}
							>
								<option value="">— pick model —</option>
								{#each models.filter((m) => m.backend === c.backend || ((c.backend as string) === "mixed_vulkan" && m.backend === "vulkan")) as m}
									<option value={m.family}>{m.label ?? m.model_name ?? m.family}</option>
								{/each}
							</select>
							<select bind:value={startProfile[c.id]}>
								{#each familyProfileOptions(startFamily[c.id]) as p}
									<option value={p}>{p}</option>
								{/each}
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
	.badge-rocmfp4 {
		background: #e0872a;
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
	.router-status {
		font-size: 0.85rem;
		color: var(--red, #e57373);
	}
	.router-status.online {
		color: var(--green, #4caf50);
	}
	.router-toolbar {
		display: flex;
		align-items: center;
		gap: 1rem;
		margin-bottom: 0.75rem;
		flex-wrap: wrap;
	}
	.toggle-label {
		display: flex;
		align-items: center;
		gap: 0.4rem;
		cursor: pointer;
	}
	.remap-row {
		display: flex;
		align-items: center;
		gap: 0.6rem;
		flex-wrap: wrap;
		margin-bottom: 0.75rem;
		font-size: 0.85rem;
	}
	.remap-row select {
		padding: 0.2rem 0.4rem;
		background: var(--bg-card);
		color: var(--text);
		border: 1px solid var(--border);
		border-radius: 4px;
	}
	.rules-table {
		width: 100%;
		border-collapse: collapse;
		font-size: 0.85rem;
		margin-bottom: 0.75rem;
	}
	.rules-table th,
	.rules-table td {
		padding: 0.35rem 0.6rem;
		text-align: left;
		border-bottom: 1px solid var(--border);
	}
	.rules-table th {
		color: var(--text-muted);
		font-weight: normal;
	}
	.keywords {
		color: var(--text-muted);
		font-size: 0.8rem;
		max-width: 260px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.rule-actions {
		display: flex;
		gap: 0.4rem;
		white-space: nowrap;
	}
	.editing-row input {
		width: 100%;
		padding: 0.2rem 0.4rem;
		background: var(--bg);
		border: 1px solid var(--accent, #6c8ebf);
		color: var(--text);
		border-radius: 3px;
		font-size: 0.8rem;
	}
	.add-rule-form {
		display: flex;
		flex-wrap: wrap;
		gap: 0.5rem;
		align-items: center;
		padding: 0.75rem;
		background: var(--bg-card);
		border: 1px solid var(--border);
		border-radius: 6px;
		margin-bottom: 0.5rem;
	}
	.add-rule-form input,
	.add-rule-form select {
		padding: 0.3rem 0.5rem;
		background: var(--bg);
		border: 1px solid var(--border);
		color: var(--text);
		border-radius: 4px;
		font-size: 0.85rem;
	}
	.btn-add-rule {
		background: transparent;
		border: 1px dashed var(--border);
		color: var(--text-muted);
		border-radius: 4px;
		padding: 0.3rem 0.75rem;
		cursor: pointer;
		font-size: 0.85rem;
	}
	.btn-add-rule:hover {
		border-color: var(--accent, #6c8ebf);
		color: var(--text);
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
