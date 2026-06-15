<script lang="ts">
	import { onMount } from "svelte";
	import { deleteModels, fetchInventory, fetchModels } from "../lib/api";
	import type { InventoryModel, ModelInfo } from "../lib/types";

	let { onClose, onDeleted }: { onClose: () => void; onDeleted: () => void } = $props();
	let models: ModelInfo[] = $state([]);
	let inventory: InventoryModel[] = $state([]);
	let selected: Set<string> = $state(new Set());
	let deleting = $state(false);
	let error = $state("");

	onMount(async () => {
		try {
			const [m, inv] = await Promise.all([fetchModels(), fetchInventory()]);
			models = m.models;
			inventory = inv.models;
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : String(e);
		}
	});

	function repoFor(model: ModelInfo): string {
		return model.alias || model.family;
	}

	function diskGb(repo: string): string {
		return inventory.find((i) => i.repo === repo)?.disk_gb || "-";
	}

	function toggle(repo: string) {
		const next = new Set(selected);
		if (next.has(repo)) next.delete(repo);
		else next.add(repo);
		selected = next;
	}

	async function del() {
		if (selected.size === 0) return;
		if (!confirm(`Delete ${selected.size} model(s)? This removes metadata/cache.`)) return;
		deleting = true;
		error = "";
		try {
			await deleteModels([...selected]);
			onDeleted();
			onClose();
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			deleting = false;
		}
	}
</script>

<div
	class="modal-overlay"
	role="button"
	tabindex="0"
	onclick={(e) => { if (e.target === e.currentTarget) onClose(); }}
	onkeydown={(e) => { if (e.key === "Escape") onClose(); }}
>
	<div class="modal" role="dialog" aria-modal="true">
		<div class="modal-header"><h3>Delete Models</h3><button onclick={onClose}>✕</button></div>
		<div class="modal-body">
			{#if error}<div class="error">{error}</div>{/if}
			<div class="actions">
				<button onclick={() => (selected = new Set(models.map(repoFor)))}>Select All</button>
				<button onclick={() => (selected = new Set())}>Select None</button>
				<button class="danger" onclick={del} disabled={deleting || selected.size === 0}>{deleting ? "Deleting..." : `Delete ${selected.size}`}</button>
			</div>
			<table>
				<thead><tr><th></th><th>Family</th><th>Alias</th><th>Backend</th><th>Disk GB</th></tr></thead>
				<tbody>
					{#each models as model}
						{@const repo = repoFor(model)}
						<tr>
							<td><input type="checkbox" checked={selected.has(repo)} onchange={() => toggle(repo)} /></td>
							<td>{model.family}</td><td>{model.alias}</td><td>{model.backend}</td><td>{diskGb(repo)}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	</div>
</div>

<style>
	.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.8); display: flex; align-items: center; justify-content: center; z-index: 100; backdrop-filter: blur(4px); }
	.modal { background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px; width: 90%; max-width: 900px; max-height: 85vh; display: flex; flex-direction: column; overflow: hidden; box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.5); }
	.modal-header { display: flex; justify-content: space-between; align-items: center; padding: 0.75rem 1rem; border-bottom: 1px solid var(--border); background: var(--bg); }
	.modal-header h3 { margin: 0; font-size: 0.9rem; font-weight: bold; }
	.modal-header button { background: none; border: none; color: var(--text-muted); cursor: pointer; font-size: 1.2rem; }
	.modal-body { flex: 1; overflow-y: auto; padding: 1rem; }
	.actions { display: flex; gap: 0.5rem; margin-bottom: 0.7rem; }
	button { padding: 0.3rem 0.6rem; border: 1px solid var(--border); background: var(--bg); color: var(--text); border-radius: 6px; cursor: pointer; font-size: 0.8rem; transition: all 0.1s; }
	button:hover { border-color: var(--text-muted); }
	button.danger { background: var(--red); color: white; border: none; font-weight: bold; }
	button.danger:hover { filter: brightness(1.2); }
	table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
	th, td { text-align: left; padding: 0.6rem 0.4rem; border-bottom: 1px solid var(--border); }
	th { color: var(--text-muted); font-weight: normal; }
	.error { background: var(--red); color: white; padding: 0.5rem; border-radius: 4px; margin-bottom: 0.7rem; }
</style>
