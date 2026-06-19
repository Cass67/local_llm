<script lang="ts">
	import { onMount } from "svelte";
	import { editModel, fetchModelDetail } from "../lib/api";
	import { splitKnownFlags } from "../lib/mtpFlags";
	import type { Backend, ClusterInfo } from "../lib/types";

	let {
		family,
		clusters = [] as ClusterInfo[],
		onClose,
		onSaved,
		onStartOnCluster,
	}: {
		family: string;
		clusters?: ClusterInfo[];
		onClose: () => void;
		onSaved: () => void;
		onStartOnCluster?: (clusterId: string, profile: string) => void;
	} = $props();
	let loading = $state(true);
	let saving = $state(false);
	let error = $state("");
	let form: Record<string, string> = $state({});
	let selectedCluster = $state("");

	onMount(async () => {
		try {
			const data = await fetchModelDetail(family);
			const cfg = data.config || {};
			const parsed = splitKnownFlags(cfg.flags);
			const flashOn = cfg.flash_attention !== undefined ? cfg.flash_attention : parsed.flash_attention;
			const jinjaOn = cfg.jinja !== undefined ? cfg.jinja : parsed.jinja;
			form = {
				profile: data.profile || "balanced",
				ctx: String(cfg.ctx || data.context || ""),
				batch: String(cfg.batch || ""),
				ubatch: String(cfg.ubatch || ""),
				ngl: String(cfg.ngl || ""),
				cache_type_k: cfg.cache_type_k || "",
				cache_type_v: cfg.cache_type_v || "",
				ctx_shift: cfg.ctx_shift || "",
				reasoning: cfg.reasoning === false ? "off" : "on",
				backend: cfg.backend || data.backend || "rocm",
				visible_devices: cfg.visible_devices || "",
				split_mode: cfg.split_mode || "",
				tensor_split: cfg.tensor_split || "",
				mtp_enabled: cfg.mtp_enabled ? "on" : "off",
				mtp_draft_n_max: String(cfg.mtp_draft_n_max ?? ""),
				mtp_draft_n_min: String(cfg.mtp_draft_n_min ?? ""),
				mtp_draft_p_min: String(cfg.mtp_draft_p_min ?? ""),
				flash_attention: flashOn ? "on" : "off",
				jinja: jinjaOn ? "on" : "off",
				flags: parsed.flags,
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

	function mtpFloat(): number {
		const value = Number(form.mtp_draft_p_min || "0.5");
		return Number.isFinite(value) ? value : 0.5;
	}

	async function doSave() {
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
			mtp_enabled: form.mtp_enabled === "on",
			mtp_draft_n_max: num("mtp_draft_n_max"),
			mtp_draft_n_min: num("mtp_draft_n_min"),
			mtp_draft_p_min: mtpFloat() || undefined,
			flash_attention: form.flash_attention === "on",
			jinja: form.jinja === "on",
			flags: form.flags,
		});
	}

	async function save() {
		saving = true;
		error = "";
		try {
			await doSave();
			onSaved();
			onClose();
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			saving = false;
		}
	}

	async function saveAndStart() {
		const cid = clusters.length === 1 ? clusters[0].id : selectedCluster;
		if (!cid) return;
		saving = true;
		error = "";
		try {
			await doSave();
			onStartOnCluster?.(cid, form.profile || "reliable");
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
					<label>Backend<select bind:value={form.backend}><option value="rocm">rocm</option><option value="vulkan">vulkan</option><option value="cuda">cuda</option></select></label>
					<label>Visible Devices<input bind:value={form.visible_devices} /></label>
					<label>Split Mode<input bind:value={form.split_mode} /></label>
					<label>Tensor Split<input bind:value={form.tensor_split} /></label>
					<div class="mtp-section">
						<label class="checkbox-row">
							<input
								type="checkbox"
								checked={form.mtp_enabled === "on"}
								onchange={(e) => (form.mtp_enabled = e.currentTarget.checked ? "on" : "off")}
							/>
							Enable MTP speculative decoding
						</label>
						{#if form.mtp_enabled === "on"}
							<div class="form-grid mtp-grid">
								<label>Draft max<input type="number" bind:value={form.mtp_draft_n_max} /></label>
								<label>Draft min<input type="number" bind:value={form.mtp_draft_n_min} /></label>
								<label>P min<input type="number" step="0.01" bind:value={form.mtp_draft_p_min} /></label>
							</div>
						{/if}
					</div>
					<label class="checkbox-row">
							<input type="checkbox" checked={form.flash_attention === "on"}
								onchange={(e) => (form.flash_attention = e.currentTarget.checked ? "on" : "off")} />
							Flash attention
						</label>
						<label class="checkbox-row">
							<input type="checkbox" checked={form.jinja === "on"}
								onchange={(e) => (form.jinja = e.currentTarget.checked ? "on" : "off")} />
							Jinja templates
						</label>
						<label>Flags<input bind:value={form.flags} /></label>
				</div>
				<div class="actions">
					<button onclick={save} disabled={saving}>{saving ? "Saving..." : "Save"}</button>
					{#if clusters.length > 0}
						<div class="start-group">
							{#if clusters.length > 1}
								<select bind:value={selectedCluster} class="cluster-sel">
									<option value="">— cluster —</option>
									{#each clusters as c}
										<option value={c.id}>{c.name}</option>
									{/each}
								</select>
							{/if}
							<button
								class="start-btn"
								onclick={saveAndStart}
								disabled={saving || (clusters.length > 1 && !selectedCluster)}
							>
								{saving ? "Saving..." : clusters.length === 1 ? `Save & Start on ${clusters[0].name}` : "Save & Start"}
							</button>
						</div>
					{/if}
				</div>
			{/if}
		</div>
	</div>
</div>

<style>
	.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.8); display: flex; align-items: center; justify-content: center; z-index: 100; backdrop-filter: blur(4px); }
	.modal { background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px; width: 90%; max-width: 780px; max-height: 85vh; display: flex; flex-direction: column; overflow: hidden; box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.5); }
	.modal-header { display: flex; justify-content: space-between; align-items: center; padding: 0.75rem 1rem; border-bottom: 1px solid var(--border); background: var(--bg); }
	.modal-header h3 { margin: 0; font-size: 0.9rem; font-weight: bold; }
	.modal-header button { background: none; border: none; color: var(--text-muted); cursor: pointer; font-size: 1.2rem; }
	.modal-body { flex: 1; overflow-y: auto; padding: 1rem; }
	.form-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 0.7rem; }
	.mtp-section { grid-column: 1 / -1; border: 1px solid var(--border); border-radius: 8px; padding: 0.8rem; background: var(--bg); }
	.mtp-grid { margin-top: 0.8rem; }
	label { display: flex; flex-direction: column; gap: 0.3rem; color: var(--text-muted); font-size: 0.8rem; }
	.checkbox-row { flex-direction: row; align-items: center; color: var(--text); gap: 0.5rem; }
	input, select { padding: 0.5rem; border: 1px solid var(--border); border-radius: 6px; background: var(--bg-card); color: var(--text); transition: border-color 0.1s; }
	input:focus, select:focus { outline: none; border-color: var(--accent); }
	.actions { margin-top: 1.2rem; display: flex; justify-content: flex-end; gap: 0.5rem; flex-wrap: wrap; align-items: center; }
	.actions button { padding: 0.6rem 1.2rem; background: var(--accent); color: var(--text); border: none; border-radius: 6px; cursor: pointer; font-weight: bold; transition: filter 0.1s; }
	.actions button:hover:not(:disabled) { filter: brightness(1.2); }
	.actions button:disabled { opacity: 0.5; cursor: not-allowed; }
	.start-group { display: flex; gap: 0.4rem; align-items: center; }
	.cluster-sel { padding: 0.5rem; border: 1px solid var(--border); border-radius: 6px; background: var(--bg-card); color: var(--text); font-size: 0.85rem; }
	.start-btn { padding: 0.6rem 1.2rem; background: var(--green); color: var(--text); border: none; border-radius: 6px; cursor: pointer; font-weight: bold; transition: filter 0.1s; }
	.start-btn:hover:not(:disabled) { filter: brightness(1.2); }
	.start-btn:disabled { opacity: 0.5; cursor: not-allowed; }
	.error { background: var(--red); color: white; padding: 0.5rem; border-radius: 4px; margin-bottom: 0.7rem; }
</style>
