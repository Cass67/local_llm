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

	let models = $state<ModelInfo[]>([]);
	let allProfiles = $state<Record<string, { default: string; profiles: Record<string, any> }>>({});
	let selectedFamily = $state("");
	let selectedProfile = $state("");
	let draftText = $state("");
	let newName = $state("");
	let isNew = $state(false);
	let error = $state("");
	let saved = $state(false);
	let importing = $state(false);
	let cloning = $state(false);
	let cloneName = $state("");

	const families = $derived([...new Set(models.map((m) => m.family))].sort());
	const currentFam = $derived(allProfiles[selectedFamily] ?? { default: "", profiles: {} });
	const profileNames = $derived(Object.keys(currentFam.profiles).sort());

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
			draftText = def ? JSON.stringify(famData?.profiles[def] ?? {}, null, 2) : "";
		}
	});

	function pickProfile(name: string) {
		isNew = false;
		selectedProfile = name;
		draftText = name ? JSON.stringify(currentFam.profiles[name] ?? {}, null, 2) : "";
	}

	function onFamilyChange(fam: string) {
		selectedFamily = fam;
		isNew = false;
		const names = Object.keys(allProfiles[fam]?.profiles ?? {}).sort();
		const def = allProfiles[fam]?.default || names[0] || "";
		selectedProfile = def;
		draftText = def ? JSON.stringify(allProfiles[fam]?.profiles[def] ?? {}, null, 2) : "";
	}

	async function handleImport() {
		importing = true;
		error = "";
		try {
			const result = await importProfilesFromModels();
			await reload();
			// re-init selection for current family
			const famData = allProfiles[selectedFamily];
			const names = Object.keys(famData?.profiles ?? {}).sort();
			const def = famData?.default || names[0] || "";
			selectedProfile = def;
			draftText = def ? JSON.stringify(famData?.profiles[def] ?? {}, null, 2) : "";
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
		draftText = JSON.stringify({ batch: 4096, ubatch: 256, ngl: 999, context: null }, null, 2);
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
		if (!name) { error = "name required"; return; }
		let parsed: any;
		try { parsed = JSON.parse(draftText); }
		catch { error = "invalid JSON"; return; }
		try {
			await upsertProfile(selectedFamily, name, parsed);
			await reload();
			isNew = false;
			newName = "";
			selectedProfile = name;
			draftText = JSON.stringify(allProfiles[selectedFamily]?.profiles[name] ?? parsed, null, 2);
			saved = true;
			setTimeout(() => (saved = false), 1500);
		} catch (e: any) {
			error = e.message;
		}
	}

	async function handleDelete() {
		if (!selectedProfile || isNew) return;
		if (!confirm(`Delete "${selectedProfile}" from ${selectedFamily}?`)) return;
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
			{#each families as f}<option value={f}>{f}</option>{/each}
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
			<button class="btn-del" onclick={handleDelete}>Delete</button>
		{/if}
		<button class="btn-save" onclick={handleSave}>{saved ? "Saved ✓" : "Save"}</button>
	</div>

	{#if error}<p class="error">{error}</p>{/if}

	{#if selectedFamily}
		{#if !isNew && profileNames.length === 0}
			<p class="muted">No profiles for <strong>{selectedFamily}</strong> — click + New.</p>
		{/if}
		<textarea bind:value={draftText} spellcheck="false" placeholder="paste or type JSON here"></textarea>
	{/if}
</div>

<style>
	.profiles-page {
		max-width: 860px;
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
	.btn-save { border-color: var(--accent, #6c8ebf); color: var(--accent, #6c8ebf); }
	.btn-save:hover { background: color-mix(in srgb, var(--accent, #6c8ebf) 15%, transparent); }
	.btn-del { color: #e57373; border-color: #e5737333; }
	.btn-del:hover { background: #e5737322; }
	.btn-import { color: var(--text-muted); font-size: 0.8rem; }
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
</style>
