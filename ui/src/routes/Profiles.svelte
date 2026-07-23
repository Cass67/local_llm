<script lang="ts">
	import { onMount } from "svelte";
	import type { ModelInfo } from "../lib/types";
	import {
		fetchModels,
		fetchAllProfiles,
		importProfilesFromModels,
		upsertProfile,
		deleteProfile,
		cloneProfile,
		setDefaultProfile,
	} from "../lib/api";

	type Field = {
		key: string;
		label: string;
		type: "bool" | "int" | "float" | "text" | "select";
		options?: string[];
		placeholder?: string;
		hint?: string;
	};
	type Group = { title: string; fields: Field[] };

	// Full profile schema — mirrors build_llama_server_args in backend/runtime.py.
	const SCHEMA: Group[] = [
		{
			title: "Model / GPU",
			fields: [
				{ key: "ngl", label: "GPU layers (-ngl)", type: "int", placeholder: "999" },
				{ key: "split_mode", label: "Split mode", type: "select", options: ["layer", "row", "none"] },
				{ key: "tensor_split", label: "Tensor split", type: "text", placeholder: "3,1" },
				{ key: "main_gpu", label: "Main GPU", type: "int" },
				{ key: "threads", label: "Threads (-t)", type: "int" },
				{ key: "threads_batch", label: "Threads batch (-tb)", type: "int" },
				{ key: "context", label: "Context size", type: "int", placeholder: "auto" },
				{ key: "batch", label: "Batch (-b)", type: "int", placeholder: "4096" },
				{ key: "ubatch", label: "U-batch (-ub)", type: "int", placeholder: "256" },
				{ key: "no_mmap", label: "No mmap", type: "bool" },
				{ key: "mlock", label: "mlock", type: "bool" },
				{ key: "no_kv_offload", label: "No KV offload", type: "bool" },
				{ key: "numa", label: "NUMA", type: "select", options: ["distribute", "isolate", "numactl"] },
			],
		},
		{
			title: "Cache / KV",
			fields: [
				{ key: "cache_prompt", label: "Cache prompt", type: "bool" },
				{ key: "cache_ram", label: "Cache RAM (MiB)", type: "int", placeholder: "16384" },
				{ key: "cache_type_k", label: "Cache type K", type: "select", options: ["f16", "q8_0", "q4_0"] },
				{ key: "cache_type_v", label: "Cache type V", type: "select", options: ["f16", "q8_0", "q4_0"] },
				{ key: "context_shift", label: "Context shift", type: "bool" },
				{ key: "ctx_checkpoints", label: "Ctx checkpoints", type: "int", placeholder: "64" },
				{ key: "checkpoint_min_step", label: "Checkpoint min step", type: "int", placeholder: "4096" },
			],
		},
		{
			title: "Server runtime",
			fields: [
				{ key: "timeout", label: "Timeout (s)", type: "int", placeholder: "600" },
				{ key: "threads_http", label: "HTTP threads", type: "int", placeholder: "2" },
				{ key: "parallel", label: "Parallel slots", type: "int", placeholder: "1" },
				{ key: "no_cont_batching", label: "No cont batching", type: "bool" },
				{ key: "prio", label: "Priority", type: "int", placeholder: "2" },
				{ key: "no_warmup", label: "No warmup", type: "bool" },
			],
		},
		{
			title: "Sampling",
			fields: [
				{ key: "temperature", label: "Temperature", type: "float" },
				{ key: "top_p", label: "top-p", type: "float" },
				{ key: "top_k", label: "top-k", type: "int" },
				{ key: "min_p", label: "min-p", type: "float" },
				{ key: "repeat_penalty", label: "Repeat penalty", type: "float" },
				{ key: "repetition_penalty", label: "Repetition penalty", type: "float" },
				{ key: "presence_penalty", label: "Presence penalty", type: "float" },
				{ key: "frequency_penalty", label: "Frequency penalty", type: "float" },
			],
		},
		{
			title: "Features",
			fields: [
				{ key: "flash_attention", label: "Flash attention", type: "bool" },
				{ key: "jinja", label: "Jinja templates", type: "bool" },
				{ key: "reasoning", label: "Reasoning", type: "bool" },
				{ key: "mmproj", label: "mmproj path", type: "text" },
			],
		},
		{
			title: "Speculative (MTP)",
			fields: [
				{ key: "mtp_enabled", label: "MTP enabled", type: "bool" },
				{ key: "mtp_draft_model", label: "Draft model path", type: "text" },
				{ key: "mtp_draft_n_max", label: "Draft n-max", type: "int" },
				{ key: "mtp_draft_n_min", label: "Draft n-min", type: "int" },
				{ key: "mtp_draft_p_min", label: "Draft p-min", type: "float" },
			],
		},
		{
			title: "Raw flags",
			fields: [
				{ key: "flags", label: "Extra flags", type: "text", placeholder: "--foo bar", hint: "passed verbatim" },
			],
		},
	];

	const KNOWN_KEYS = new Set(SCHEMA.flatMap((g) => g.fields.map((f) => f.key)));

	let models = $state<ModelInfo[]>([]);
	let allProfiles = $state<Record<string, { default: string; profiles: Record<string, any> }>>({});
	let selectedFamily = $state("");
	let selectedProfile = $state("");
	let form = $state<Record<string, any>>({});
	let draftText = $state("");
	let editMode = $state<"form" | "json">("form");
	let newName = $state("");
	let isNew = $state(false);
	let error = $state("");
	let saved = $state(false);
	let importing = $state(false);
	let cloning = $state(false);
	let cloneName = $state("");
	let showDeleteConfirm = $state(false);

	const familyBackend = $derived(
		Object.fromEntries(models.map((m) => [m.family, m.backend])) as Record<string, string>,
	);
	const families = $derived([...new Set(models.map((m) => m.family))].sort());
	const currentFam = $derived(allProfiles[selectedFamily] ?? { default: "", profiles: {} });
	const profileNames = $derived(Object.keys(currentFam.profiles).sort());
	// Keys present on the profile that the form doesn't know about — preserved on save.
	const unknownKeys = $derived(Object.keys(form).filter((k) => !KNOWN_KEYS.has(k)));

	function loadInto(obj: any) {
		form = structuredClone($state.snapshot(obj ?? {}));
		draftText = JSON.stringify(obj ?? {}, null, 2);
	}

	onMount(async () => {
		const [modelData, profileData] = await Promise.all([fetchModels(), fetchAllProfiles()]);
		models = modelData.models;
		allProfiles = profileData.families;
		if (families.length > 0) {
			const fam = families[0];
			selectedFamily = fam;
			const famData = profileData.families[fam];
			const names = Object.keys(famData?.profiles ?? {}).sort();
			const def = famData?.default || names[0] || "";
			selectedProfile = def;
			loadInto(def ? famData?.profiles[def] : {});
		}
	});

	function pickProfile(name: string) {
		isNew = false;
		selectedProfile = name;
		loadInto(name ? currentFam.profiles[name] : {});
	}

	function onFamilyChange(fam: string) {
		selectedFamily = fam;
		isNew = false;
		const names = Object.keys(allProfiles[fam]?.profiles ?? {}).sort();
		const def = allProfiles[fam]?.default || names[0] || "";
		selectedProfile = def;
		loadInto(def ? allProfiles[fam]?.profiles[def] : {});
	}

	// Sync when toggling editor mode so both views agree.
	function setMode(mode: "form" | "json") {
		if (mode === editMode) return;
		if (editMode === "form") {
			draftText = JSON.stringify(coerce(form), null, 2);
		} else {
			try {
				form = coerce(JSON.parse(draftText));
			} catch {
				error = "invalid JSON — fix before switching to form";
				return;
			}
		}
		error = "";
		editMode = mode;
	}

	// --- form field helpers -------------------------------------------------
	function has(key: string) {
		return key in form;
	}
	function toggleInclude(key: string, field: Field) {
		if (key in form) delete form[key];
		else form[key] = field.type === "select" ? (field.options?.[0] ?? "") : "";
	}
	function setBool(key: string, val: boolean) {
		if (val) form[key] = true;
		else delete form[key];
	}
	function num(key: string, raw: string, float: boolean) {
		if (raw.trim() === "") {
			form[key] = "";
			return;
		}
		const n = float ? parseFloat(raw) : parseInt(raw, 10);
		form[key] = Number.isNaN(n) ? raw : n;
	}

	// Coerce number-typed fields to numbers, drop blank/empty values.
	function coerce(obj: Record<string, any>): Record<string, any> {
		const out: Record<string, any> = { ...obj };
		for (const g of SCHEMA) {
			for (const f of g.fields) {
				if (!(f.key in out)) continue;
				const v = out[f.key];
				if (f.type === "bool") continue;
				if (v === "" || v === null || v === undefined) {
					delete out[f.key];
					continue;
				}
				if (f.type === "int") out[f.key] = parseInt(String(v), 10);
				else if (f.type === "float") out[f.key] = parseFloat(String(v));
			}
		}
		return out;
	}

	async function handleImport() {
		importing = true;
		error = "";
		try {
			const result = await importProfilesFromModels();
			await reload();
			const famData = allProfiles[selectedFamily];
			const names = Object.keys(famData?.profiles ?? {}).sort();
			const def = famData?.default || names[0] || "";
			selectedProfile = def;
			loadInto(def ? famData?.profiles[def] : {});
			if (result.imported === 0) error = "Nothing new to import (all profiles already exist).";
		} catch (e: any) {
			error = e.message;
		} finally {
			importing = false;
		}
	}

	async function handleClone() {
		const name = cloneName.trim();
		if (!name || !selectedProfile) return;
		cloning = true;
		error = "";
		try {
			await cloneProfile(selectedFamily, selectedProfile, name);
			await reload();
			cloneName = "";
			pickProfile(name);
		} catch (e: any) {
			error = e.message;
		} finally {
			cloning = false;
		}
	}

	function startNew() {
		isNew = true;
		newName = "";
		loadInto({ batch: 4096, ubatch: 256, ngl: 999 });
	}

	function cancelNew() {
		isNew = false;
		pickProfile(currentFam.default || profileNames[0] || "");
	}

	async function reload() {
		allProfiles = (await fetchAllProfiles()).families;
	}

	async function handleSave() {
		error = "";
		const name = isNew ? newName.trim() : selectedProfile;
		if (!name) {
			error = "name required";
			return;
		}
		let parsed: any;
		if (editMode === "json") {
			try {
				parsed = JSON.parse(draftText);
			} catch {
				error = "invalid JSON";
				return;
			}
		} else {
			parsed = coerce(form);
		}
		try {
			await upsertProfile(selectedFamily, name, parsed);
			await reload();
			isNew = false;
			newName = "";
			selectedProfile = name;
			loadInto(allProfiles[selectedFamily]?.profiles[name] ?? parsed);
			saved = true;
			setTimeout(() => (saved = false), 1500);
		} catch (e: any) {
			error = e.message;
		}
	}

	function confirmDelete() {
		if (!selectedProfile || isNew) return;
		showDeleteConfirm = true;
	}

	async function handleDelete() {
		if (!selectedProfile || isNew) return;
		showDeleteConfirm = false;
		error = "";
		try {
			await deleteProfile(selectedFamily, selectedProfile);
			await reload();
			const names = Object.keys(allProfiles[selectedFamily]?.profiles ?? {}).sort();
			pickProfile(names[0] || "");
		} catch (e: any) {
			error = e.message;
		}
	}

	async function handleSetDefault() {
		if (!selectedProfile || isNew) return;
		try {
			await setDefaultProfile(selectedFamily, selectedProfile);
			await reload();
		} catch (e: any) {
			error = e.message;
		}
	}
</script>

<div class="profiles-page">
	<div class="toolbar">
		<select
			value={selectedFamily}
			onchange={(e) => onFamilyChange(e.currentTarget.value)}
			class="sel-family"
		>
			{#each families as f}<option value={f}>{f}{familyBackend[f] ? ` · ${familyBackend[f]}` : ""}</option>{/each}
		</select>

		{#if isNew}
			<input bind:value={newName} placeholder="profile name" class="name-input" />
			<button onclick={cancelNew}>Cancel</button>
		{:else if profileNames.length > 0}
			<select
				value={selectedProfile}
				onchange={(e) => pickProfile(e.currentTarget.value)}
				class="sel-profile"
			>
				{#each profileNames as p}
					<option value={p}>{p}{currentFam.default === p ? " ★" : ""}</option>
				{/each}
			</select>
		{/if}

		<button onclick={startNew}>+ New</button>

		{#if !isNew && selectedProfile}
			<input bind:value={cloneName} placeholder="clone as…" class="clone-input"
				onkeydown={(e) => e.key === "Enter" && handleClone()} />
			<button onclick={handleClone} disabled={cloning || !cloneName.trim()}>Clone</button>
		{/if}

		{#if !isNew && selectedProfile && currentFam.default !== selectedProfile}
			<button onclick={handleSetDefault}>Set default</button>
		{/if}

		<span class="spacer"></span>

		<button class="btn-import" onclick={handleImport} disabled={importing}>
			{importing ? "Importing…" : "Import from models"}
		</button>
		{#if !isNew && selectedProfile}
			<button class="btn-del" onclick={confirmDelete}>Delete</button>
		{/if}
		<button class="btn-save" onclick={handleSave}>{saved ? "Saved ✓" : "Save"}</button>

		{#if showDeleteConfirm}
			<div class="confirm-overlay">
				<div class="confirm-box">
					<p>Delete profile <strong>{selectedProfile}</strong> from <strong>{selectedFamily}</strong>?</p>
					<div class="confirm-actions">
						<button onclick={() => (showDeleteConfirm = false)}>Cancel</button>
						<button class="btn-del" onclick={handleDelete}>Yes, delete</button>
					</div>
				</div>
			</div>
		{/if}
	</div>

	{#if error}<p class="error">{error}</p>{/if}

	{#if selectedFamily}
		{#if !isNew && profileNames.length === 0}
			<p class="muted">No profiles for <strong>{selectedFamily}</strong> — click + New.</p>
		{/if}

		{#if isNew || selectedProfile}
			<div class="mode-tabs">
				<button class:active={editMode === "form"} onclick={() => setMode("form")}>Form</button>
				<button class:active={editMode === "json"} onclick={() => setMode("json")}>JSON</button>
			</div>

			{#if editMode === "form"}
				<div class="form-grid">
					{#each SCHEMA as group}
						<fieldset>
							<legend>{group.title}</legend>
							{#each group.fields as f}
								{#if f.type === "bool"}
									<label class="row bool-row">
										<input
											type="checkbox"
											checked={form[f.key] === true}
											onchange={(e) => setBool(f.key, e.currentTarget.checked)}
										/>
										<span class="fname">{f.label}</span>
									</label>
								{:else}
									<div class="row">
										<label class="inc" title="include this option">
											<input
												type="checkbox"
												checked={has(f.key)}
												onchange={() => toggleInclude(f.key, f)}
											/>
										</label>
										<span class="fname" class:off={!has(f.key)}>{f.label}</span>
										{#if f.type === "select"}
											<select
												disabled={!has(f.key)}
												value={form[f.key] ?? ""}
												onchange={(e) => (form[f.key] = e.currentTarget.value)}
											>
												{#each f.options ?? [] as o}<option value={o}>{o}</option>{/each}
											</select>
										{:else if f.type === "text"}
											<input
												type="text"
												disabled={!has(f.key)}
												placeholder={f.placeholder ?? ""}
												value={form[f.key] ?? ""}
												oninput={(e) => (form[f.key] = e.currentTarget.value)}
											/>
										{:else}
											<input
												type="number"
												step={f.type === "float" ? "any" : "1"}
												disabled={!has(f.key)}
												placeholder={f.placeholder ?? ""}
												value={form[f.key] ?? ""}
												oninput={(e) => num(f.key, e.currentTarget.value, f.type === "float")}
											/>
										{/if}
									</div>
								{/if}
							{/each}
						</fieldset>
					{/each}
				</div>
				{#if unknownKeys.length > 0}
					<p class="muted small">
						Preserved (edit in JSON): {unknownKeys.join(", ")}
					</p>
				{/if}
			{:else}
				<textarea bind:value={draftText} spellcheck="false" placeholder="paste or type JSON here"></textarea>
			{/if}
		{/if}
	{/if}
</div>

<style>
	.profiles-page {
		max-width: 960px;
		margin: 0 auto;
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
	}
	.toolbar {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		flex-wrap: wrap;
	}
	select, input {
		padding: 0.3rem 0.5rem;
		background: var(--bg-card);
		border: 1px solid var(--border);
		color: var(--text);
		border-radius: 4px;
		font-size: 0.9rem;
	}
	.sel-family { max-width: 280px; }
	.sel-profile { max-width: 180px; }
	.name-input { width: 150px; }
	.clone-input { width: 120px; }
	.spacer { flex: 1; }
	button {
		padding: 0.3rem 0.7rem;
		border: 1px solid var(--border);
		background: var(--bg-card);
		color: var(--text);
		border-radius: 4px;
		cursor: pointer;
		font-size: 0.85rem;
		white-space: nowrap;
	}
	.btn-save { min-width: 90px; text-align: center; border-color: var(--accent, #6c8ebf); color: var(--accent, #6c8ebf); }
	.btn-save:hover { background: color-mix(in srgb, var(--accent, #6c8ebf) 15%, transparent); }
	.btn-del { color: #e57373; border-color: #e5737333; }
	.btn-del:hover { background: #e5737322; }
	.btn-import { color: var(--text-muted); font-size: 0.8rem; }

	.mode-tabs { display: flex; gap: 0.25rem; }
	.mode-tabs button { font-size: 0.8rem; opacity: 0.7; }
	.mode-tabs button.active {
		opacity: 1;
		border-color: var(--accent, #6c8ebf);
		color: var(--accent, #6c8ebf);
	}

	.form-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
		gap: 0.75rem;
		align-items: start;
	}
	fieldset {
		border: 1px solid var(--border);
		border-radius: 6px;
		padding: 0.5rem 0.75rem 0.75rem;
		margin: 0;
	}
	legend {
		padding: 0 0.35rem;
		font-size: 0.8rem;
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}
	.row {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		padding: 0.15rem 0;
	}
	.bool-row { cursor: pointer; }
	.inc { display: flex; align-items: center; }
	.inc input, .bool-row input { cursor: pointer; }
	.fname { flex: 1; font-size: 0.85rem; }
	.fname.off { color: var(--text-muted); }
	.row input[type="number"],
	.row input[type="text"],
	.row select {
		width: 130px;
		font-size: 0.85rem;
	}
	.row input:disabled, .row select:disabled { opacity: 0.4; }
	.small { font-size: 0.8rem; }

	textarea {
		width: 100%;
		min-height: 440px;
		padding: 0.75rem;
		background: var(--bg-card);
		border: 1px solid var(--border);
		color: var(--text);
		border-radius: 6px;
		font-family: monospace;
		font-size: 0.9rem;
		resize: vertical;
		box-sizing: border-box;
	}
	textarea:focus { outline: none; border-color: var(--accent, #6c8ebf); }
	.error { color: #e57373; margin: 0; }
	.muted { color: var(--text-muted); }

	.confirm-overlay {
		position: fixed;
		inset: 0;
		background: rgba(0, 0, 0, 0.5);
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 100;
	}
	.confirm-box {
		background: var(--bg-card);
		border: 1px solid var(--border);
		border-radius: 8px;
		padding: 1.5rem;
		max-width: 400px;
		width: 90%;
		box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
	}
	.confirm-box p {
		margin: 0 0 1rem;
		font-size: 0.95rem;
		color: var(--text);
	}
	.confirm-actions {
		display: flex;
		gap: 0.5rem;
		justify-content: flex-end;
	}
</style>
