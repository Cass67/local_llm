<script lang="ts">
	import type { ModelInfo } from "../lib/types";

	let {
		model,
		isRunning = false,
		switching = null as string | null,
		onSwitch,
		onCopyBackend,
		onDetail,
		onEdit,
	}: {
		model: ModelInfo;
		isRunning: boolean;
		switching: string | null;
		onSwitch: (profile: string) => void;
		onCopyBackend?: (backend: "rocm" | "vulkan") => void;
		onDetail?: () => void;
		onEdit?: () => void;
	} = $props();

	let selectedProfile = $state("");
	let isSwitching = $derived(switching === model.family);
	let oppositeBackend: "rocm" | "vulkan" = $derived(model.backend === "vulkan" ? "rocm" : "vulkan");

	$effect(() => {
		if (!selectedProfile) selectedProfile = model.profile || "reliable";
	});
</script>

<div class="model-card" class:running={isRunning}>
	<div class="card-header">
		<h3>{model.model_name}</h3>
		<span class="backend-badge" class:rocm={model.backend === "rocm"} class:vulkan={model.backend === "vulkan"}>{model.backend}</span>
	</div>

	<div class="card-body">
		<div class="info-row"><span>Family:</span> <strong>{model.family}</strong></div>
		<div class="info-row"><span>Alias:</span> <code>{model.alias}</code></div>
		{#if model.context}<div class="info-row"><span>Context:</span> {model.context.toLocaleString()}</div>{/if}
		{#if model.config?.quant}<div class="info-row"><span>Quant:</span> {model.config.quant}</div>{/if}
		{#if model.config?.visible_devices}<div class="info-row"><span>GPUs:</span> {model.config.visible_devices}</div>{/if}

		<div class="profile-select">
			<label for={`profile-${model.family}`}>Profile:</label>
			<select id={`profile-${model.family}`} bind:value={selectedProfile}>
				<option value="speed">Speed</option>
				<option value="fastlong">FastLong</option>
				<option value="balanced">Balanced</option>
				<option value="reliable">Reliable</option>
				<option value="tiny">Tiny</option>
			</select>
		</div>

		<button class="switch-btn" disabled={isSwitching || isRunning} onclick={() => onSwitch(selectedProfile)}>
			{#if isSwitching}Launching...{:else if isRunning}Running{:else}Launch{/if}
		</button>

		<div class="card-actions">
			<button onclick={onDetail}>Detail</button>
			<button onclick={onEdit}>Edit</button>
			<button onclick={() => onCopyBackend?.(oppositeBackend)}>Copy to {oppositeBackend === "rocm" ? "ROCm" : "Vulkan"}</button>
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
	.card-header h3 { margin: 0; font-size: 1rem; }
	.backend-badge { 
		font-size: 0.7rem; 
		padding: 0.1rem 0.4rem; 
		border-radius: 3px; 
		text-transform: uppercase; 
		font-weight: bold;
	}
	.backend-badge.rocm { background: #ef444422; color: #ef4444; box-shadow: 0 0 8px #ef444433; }
	.backend-badge.vulkan { background: #8b5cf622; color: #8b5cf6; box-shadow: 0 0 8px #8b5cf633; }
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
	.profile-select { 
		display: flex; 
		align-items: center; 
		gap: 0.5rem; 
		margin-top: 0.8rem; 
		padding: 0.5rem; 
		background: var(--bg); 
		border-radius: 6px; 
		border: 1px solid var(--border);
	}
	.profile-select label { color: var(--text-muted); font-size: 0.8rem; }
	.profile-select select { 
		flex: 1; 
		padding: 0.2rem; 
		border: none; 
		background: transparent; 
		color: var(--text); 
		font-family: inherit;
		cursor: pointer;
	}
	.switch-btn { 
		margin-top: 0.8rem; 
		padding: 0.6rem; 
		border: none; 
		border-radius: 6px; 
		background: var(--accent); 
		color: var(--text); 
		cursor: pointer; 
		font-weight: bold; 
		transition: filter 0.1s;
	}
	.switch-btn:hover:not(:disabled) { filter: brightness(1.2); }
	.switch-btn:disabled { opacity: 0.5; cursor: not-allowed; }
	.card-actions { display: flex; gap: 0.4rem; margin-top: 0.5rem; }
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
