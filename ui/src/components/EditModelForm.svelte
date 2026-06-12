<script lang="ts">
	import { onMount } from "svelte";
	import { editModel, fetchModelDetail } from "../lib/api";

	let { family, onClose, onSaved }: { family: string; onClose: () => void; onSaved: () => void } = $props();
	let loading = $state(true);
	let saving = $state(false);
	let error = $state("");
	let form: Record<string, string> = $state({});

	onMount(async () => {
		try {
			const data = await fetchModelDetail(family);
			const cfg = data.config || {};
			form = {
				profile: data.profile || "balanced",
				ctx: String(cfg.ctx || data.context || ""),
				batch: String(cfg.batch || "4096"),
				ubatch: String(cfg.ubatch || "256"),
				ngl: String(cfg.ngl || "999"),
				cache_type_k: cfg.cache_type_k || "",
				cache_type_v: cfg.cache_type_v || "",
				ctx_shift: cfg.ctx_shift || "",
				reasoning: cfg.reasoning === false ? "off" : "on",
				backend: cfg.backend || data.backend || "rocm",
				visible_devices: cfg.visible_devices || "",
				split_mode: cfg.split_mode || "",
				tensor_split: cfg.tensor_split || "",
				flags: cfg.flags || "",
			};
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
	});

	function num(name: string): number | undefined {
		const v = form[name]?.trim();
		return v ? Number(v) : undefined;
	}

	async function save() {
		saving = true;
		error = "";
		try {
			await editModel(family, {
				profile: form.profile,
				ctx: num("ctx"),
				batch: num("batch"),
				ubatch: num("ubatch"),
				ngl: num("ngl"),
				cache_type_k: form.cache_type_k || undefined,
				cache_type_v: form.cache_type_v || undefined,
				ctx_shift: form.ctx_shift || undefined,
				reasoning: form.reasoning === "on",
				backend: form.backend || undefined,
				visible_devices: form.visible_devices || undefined,
				split_mode: form.split_mode || undefined,
				tensor_split: form.tensor_split || undefined,
				flags: form.flags || undefined,
			});
			onSaved();
			onClose();
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			saving = false;
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
		<div class="modal-header"><h3>Edit {family}</h3><button onclick={onClose}>✕</button></div>
		<div class="modal-body">
			{#if loading}
				<p>Loading...</p>
			{:else}
				{#if error}<div class="error">{error}</div>{/if}
				<div class="form-grid">
					<label>Profile<input bind:value={form.profile} /></label>
					<label>Ctx<input type="number" bind:value={form.ctx} /></label>
					<label>Batch<input type="number" bind:value={form.batch} /></label>
					<label>Ubatch<input type="number" bind:value={form.ubatch} /></label>
					<label>NGL<input type="number" bind:value={form.ngl} /></label>
					<label>Cache K<input bind:value={form.cache_type_k} /></label>
					<label>Cache V<input bind:value={form.cache_type_v} /></label>
					<label>Ctx Shift<input bind:value={form.ctx_shift} /></label>
					<label>Reasoning<select bind:value={form.reasoning}><option value="on">on</option><option value="off">off</option></select></label>
					<label>Backend<select bind:value={form.backend}><option value="rocm">rocm</option><option value="vulkan">vulkan</option></select></label>
					<label>Visible Devices<input bind:value={form.visible_devices} /></label>
					<label>Split Mode<input bind:value={form.split_mode} /></label>
					<label>Tensor Split<input bind:value={form.tensor_split} /></label>
					<label>Flags<input bind:value={form.flags} /></label>
				</div>
				<div class="actions"><button onclick={save} disabled={saving}>{saving ? "Saving..." : "Save + Regenerate Launcher"}</button></div>
			{/if}
		</div>
	</div>
</div>

<style>
	.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.7); display: flex; align-items: center; justify-content: center; z-index: 100; }
	.modal { background: var(--bg-card); border: 1px solid var(--border); border-radius: 8px; width: 90%; max-width: 780px; max-height: 85vh; display: flex; flex-direction: column; }
	.modal-header { display: flex; justify-content: space-between; align-items: center; padding: 0.7rem 1rem; border-bottom: 1px solid var(--border); }
	.modal-header h3 { margin: 0; }
	.modal-header button { background: none; border: none; color: var(--text-muted); cursor: pointer; font-size: 1.2rem; }
	.modal-body { overflow-y: auto; padding: 1rem; }
	.form-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 0.7rem; }
	label { display: flex; flex-direction: column; gap: 0.2rem; color: var(--text-muted); font-size: 0.8rem; }
	input, select { padding: 0.45rem; border: 1px solid var(--border); border-radius: 4px; background: var(--bg); color: var(--text); }
	.actions { margin-top: 1rem; display: flex; justify-content: flex-end; }
	.actions button { padding: 0.5rem 1rem; background: var(--accent); color: var(--text); border: none; border-radius: 4px; cursor: pointer; }
	.error { background: var(--red); color: white; padding: 0.5rem; border-radius: 4px; margin-bottom: 0.7rem; }
</style>
