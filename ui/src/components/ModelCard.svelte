<script lang="ts">
	import { BACKENDS } from "../lib/types";
	import type { Backend, ModelInfo, ClusterInfo } from "../lib/types";
	import { editModel, fetchFamilyProfiles } from "../lib/api";

	let {
		model,
		runningClusterIds = [] as string[],
		clusters = [] as ClusterInfo[],
		starting = false,
		onStartOnCluster,
		onCopyBackend,
		onDetail,
		onEdit,
	}: {
		model: ModelInfo;
		runningClusterIds: string[];
		clusters: ClusterInfo[];
		starting: boolean;
		onStartOnCluster: (clusterId: string, profile: string) => void;
		onCopyBackend?: (backend: Backend) => void;
		onDetail?: () => void;
		onEdit?: () => void;
	} = $props();

	let editingLabel = $state(false);
	let labelDraft = $state("");

	function startLabelEdit() {
		labelDraft = model.label || model.model_name;
		editingLabel = true;
	}

	async function commitLabel() {
		editingLabel = false;
		const next = labelDraft.trim();
		const current = model.label || "";
		if (next === current || (next === model.model_name && !model.label)) return;
		await editModel(model.family, { label: next === model.model_name ? "" : next });
		model.label = next === model.model_name ? undefined : next;
	}

	function labelKeydown(e: KeyboardEvent) {
		if (e.key === "Enter") (e.target as HTMLElement).blur();
		if (e.key === "Escape") { editingLabel = false; }
	}

	// Mirrors _BACKEND_LABELS in container/backend/model_variants.py.
	const BACKEND_LABELS: Record<Backend, string> = {
		rocm: "ROCm",
		rocmfp4: "ROCmFP4",
		rocmmain: "ROCmMain",
		rocmmainmtp: "ROCmMainMTP",
		rocmunsloth: "ROCmUnsloth",
		rocmunslothsrc: "ROCmUnslothSrc",
		rocmqwen4exp: "ROCmQwen4Exp",
		rocmqwen4exp2: "ROCmQwen4Exp2",
		rocmfork: "ROCmFork",
		rocmdflash2: "ROCmDFlash2",
		vulkan: "Vulkan",
		cuda: "CUDA",
	};
	const ALL_BACKENDS: Backend[] = [...BACKENDS];
	const STANDARD_PROFILES = ["speed", "fastlong", "balanced", "reliable", "tiny"];

	let selectedProfile = $state("");
	let selectedCluster = $state("");
	let savedProfiles: string[] = $state([]);
	let otherBackends = $derived(ALL_BACKENDS.filter((b) => b !== model.backend));
	// Never default the picker to the backend the model is already on.
	let copyTarget = $state<Backend>("rocm");
	$effect(() => {
		if (!otherBackends.includes(copyTarget)) copyTarget = otherBackends[0];
	});
	let isRunning = $derived(runningClusterIds.length > 0);
	let idleClusters = $derived(clusters.filter((c) => !runningClusterIds.includes(c.id)));

	$effect(() => {
		fetchFamilyProfiles(model.family).then((data) => {
			const names = Object.keys(data.profiles ?? {});
			savedProfiles = names;
			if (!selectedProfile) selectedProfile = data.default || names[0] || model.profile || "balanced";
		}).catch(() => {
			if (!selectedProfile) selectedProfile = model.profile || "balanced";
		});
		if (!selectedCluster && idleClusters.length === 1) selectedCluster = idleClusters[0].id;
	});

	function doStart() {
		const cid = idleClusters.length === 1 ? idleClusters[0].id : selectedCluster;
		if (cid) onStartOnCluster(cid, selectedProfile);
	}
</script>

<div class="model-card" class:running={isRunning}>
	<div class="card-header">
		{#if editingLabel}
			<!-- svelte-ignore a11y_autofocus -->
			<input
				class="label-input"
				bind:value={labelDraft}
				onblur={commitLabel}
				onkeydown={labelKeydown}
				autofocus
			/>
		{:else}
			<button class="label-title" onclick={startLabelEdit} title="Click to rename">
				{model.label || model.model_name}
				{#if model.label}<span class="label-hint" title={model.model_name}>✎</span>{:else}<span class="label-hint muted">✎</span>{/if}
			</button>
		{/if}
		<span
			class="backend-badge"
			class:rocm={model.backend === "rocm"}
			class:rocmfp4={model.backend === "rocmfp4"}
			class:vulkan={model.backend === "vulkan"}
			class:cuda={model.backend === "cuda"}
		>{model.backend}</span>
	</div>

	<div class="card-body">
		<div class="info-row"><span>Family:</span> <strong>{model.family}</strong></div>
		<div class="info-row"><span>Alias:</span> <code>{model.alias}</code></div>
		{#if model.context}<div class="info-row"><span>Context:</span> {model.context.toLocaleString()}</div>{/if}
		{#if model.config?.quant}<div class="info-row"><span>Quant:</span> {model.config.quant}</div>{/if}

		{#if isRunning}
			<div class="running-chips">
				{#each runningClusterIds as cid}
					{@const c = clusters.find((x) => x.id === cid)}
					<span class="running-chip">● Running on {c?.name ?? cid}</span>
				{/each}
			</div>
		{/if}

		{#if idleClusters.length > 0}
			<div class="start-row">
				<input
					class="profile-input"
					list={`profiles-${model.family}`}
					bind:value={selectedProfile}
					placeholder="profile"
				/>
				<datalist id={`profiles-${model.family}`}>
					{#each savedProfiles as p}
						<option value={p}></option>
					{/each}
					{#each STANDARD_PROFILES.filter(p => !savedProfiles.includes(p)) as p}
						<option value={p}></option>
					{/each}
				</datalist>
				{#if idleClusters.length > 1}
					<select class="cluster-select" bind:value={selectedCluster}>
						<option value="">— cluster —</option>
						{#each idleClusters as c}
							<option value={c.id}>{c.name}</option>
						{/each}
					</select>
				{/if}
				<button
					class="switch-btn"
					disabled={starting || (idleClusters.length > 1 && !selectedCluster)}
					onclick={doStart}
				>
					{starting ? "Starting…" : idleClusters.length === 1 ? `▶ ${idleClusters[0].name}` : "▶ Start"}
				</button>
			</div>
		{:else if clusters.length === 0}
			<p class="no-cluster">No {BACKEND_LABELS[model.backend]} cluster — <a href="#/architecture">Architecture tab</a></p>
		{/if}

		<div class="card-actions">
			<button onclick={onDetail}>Detail</button>
			<button onclick={onEdit}>Edit</button>
			<select bind:value={copyTarget} title="copy this model as a variant on another runner image">
				{#each otherBackends as backend (backend)}
					<option value={backend}>{BACKEND_LABELS[backend]}</option>
				{/each}
			</select>
			<button onclick={() => onCopyBackend?.(copyTarget)}>Copy to backend</button>
		</div>
	</div>
</div>

<style>
	.model-card {
		background: var(--bg-card);
		border: 1px solid var(--border);
		border-radius: 8px;
		padding: 1rem;
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
		transition: transform 0.1s ease, border-color 0.1s ease;
		cursor: default;
	}
	.model-card:hover {
		transform: translateY(-2px);
		border-color: var(--accent);
	}
	.model-card.running { border-color: var(--green); }
	.card-header { display: flex; justify-content: space-between; align-items: flex-start; }
	.label-title { margin: 0; font-size: 1rem; font-weight: bold; cursor: text; display: flex; align-items: center; gap: 0.3rem; background: none; border: none; color: var(--text); padding: 0; text-align: left; }
	.label-hint { font-size: 0.7rem; opacity: 0.4; }
	.label-hint.muted { opacity: 0.2; }
	.label-title:hover .label-hint { opacity: 0.7; }
	.label-input {
		font-size: 1rem;
		font-weight: bold;
		background: var(--bg);
		border: 1px solid var(--accent);
		border-radius: 4px;
		color: var(--text);
		padding: 0.1rem 0.3rem;
		width: 100%;
		min-width: 0;
	}
	.backend-badge {
		font-size: 0.7rem;
		padding: 0.1rem 0.4rem;
		border-radius: 3px;
		text-transform: uppercase;
		font-weight: bold;
	}
	.backend-badge.rocm { background: #ef444422; color: #ef4444; box-shadow: 0 0 8px #ef444433; }
	.backend-badge.rocmfp4 { background: #f59e0b22; color: #f59e0b; box-shadow: 0 0 8px #f59e0b33; }
	.backend-badge.vulkan { background: #8b5cf622; color: #8b5cf6; box-shadow: 0 0 8px #8b5cf633; }
	.backend-badge.cuda { background: #22c55e22; color: #22c55e; box-shadow: 0 0 8px #22c55e33; }
	.card-body { display: flex; flex-direction: column; gap: 0.3rem; font-size: 0.85rem; }
	.info-row { display: flex; justify-content: space-between; gap: 0.5rem; }
	.info-row span { color: var(--text-muted); }
	code {
		font-family: 'JetBrains Mono', 'Fira Code', monospace;
		font-size: 0.8rem;
		background: var(--bg);
		padding: 0.1rem 0.3rem;
		border-radius: 3px;
		word-break: break-all;
	}
	.running-chips { display: flex; flex-direction: column; gap: 0.25rem; margin-top: 0.5rem; }
	.running-chip {
		font-size: 0.8rem;
		color: var(--green);
		background: color-mix(in srgb, var(--green) 12%, transparent);
		padding: 0.25rem 0.5rem;
		border-radius: 4px;
	}
	.start-row {
		display: flex;
		gap: 0.4rem;
		margin-top: 0.6rem;
		align-items: center;
	}
	.profile-input {
		width: 7rem;
		padding: 0.3rem 0.5rem;
		border: 1px solid var(--border);
		border-radius: 4px;
		background: var(--bg);
		color: var(--text);
		font-size: 0.82rem;
	}
	.cluster-select {
		flex: 1;
		padding: 0.3rem 0.4rem;
		background: var(--bg);
		border: 1px solid var(--border);
		color: var(--text);
		border-radius: 4px;
		font-size: 0.82rem;
	}
	.switch-btn {
		padding: 0.35rem 0.65rem;
		border: none;
		border-radius: 6px;
		background: var(--accent);
		color: var(--text);
		cursor: pointer;
		font-weight: bold;
		font-size: 0.82rem;
		white-space: nowrap;
		transition: filter 0.1s;
	}
	.switch-btn:hover:not(:disabled) { filter: brightness(1.2); }
	.switch-btn:disabled { opacity: 0.5; cursor: not-allowed; }
	.no-cluster {
		margin: 0.5rem 0 0;
		font-size: 0.8rem;
		color: var(--text-muted);
	}
	.no-cluster a { color: var(--accent); }
	.card-actions { display: flex; gap: 0.4rem; margin-top: 0.5rem; flex-wrap: wrap; }
	.card-actions button {
		flex: 1;
		padding: 0.35rem;
		border: 1px solid var(--border);
		border-radius: 4px;
		background: var(--bg);
		color: var(--text-muted);
		cursor: pointer;
		font-size: 0.75rem;
		transition: all 0.1s;
	}
	.card-actions button:hover { border-color: var(--text-muted); color: var(--text); }
</style>
