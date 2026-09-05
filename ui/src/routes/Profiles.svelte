<script lang="ts">
	import { onMount } from "svelte";
	import { BACKENDS } from "../lib/types";
	import type { ModelInfo } from "../lib/types";
	import {
		fetchModels,
		fetchAllProfiles,
		importProfilesFromModels,
		upsertProfile,
		deleteProfile,
		cloneProfile,
		setDefaultProfile,
		lintProfile,
		fetchProfileSnapshots,
		createProfileSnapshot,
		restoreProfileSnapshot,
		deleteProfileSnapshot,
		fetchSnapshotDiff,
		type ProfileSnapshot,
		type SnapshotChange,
	} from "../lib/api";
	import type { LintFinding, VramEstimate } from "../lib/types";

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
				{
					key: "backend",
					label: "Backend (runner image)",
					type: "select",
					options: [...BACKENDS],
					hint: "which runner image serves this profile; unset means rocm. An unbuilt image fails at launch, and an unknown name silently falls back to rocm",
				},
				{ key: "ngl", label: "GPU layers (-ngl)", type: "int", placeholder: "999" },
				{ key: "split_mode", label: "Split mode", type: "select", options: ["layer", "tensor", "row", "none"] },
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
				{ key: "cache_reuse", label: "Cache reuse (min chunk)", type: "int", placeholder: "256" },
				{ key: "kv_unified", label: "Unified KV", type: "bool", hint: "pool the KV across slots instead of splitting -c evenly per --parallel slot" },
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
				{ key: "backend_sampling", label: "Backend sampling", type: "bool" },
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
			title: "Speculative",
			fields: [
				{ key: "mtp_enabled", label: "MTP enabled", type: "bool" },
				{
					key: "spec_type",
					label: "Spec type",
					type: "text",
					placeholder: "draft-mtp,ngram-mod",
					hint: "comma-separated; ngram-mod needs no draft model",
				},
				{ key: "mtp_draft_model", label: "Draft model path", type: "text" },
				{ key: "mtp_draft_n_max", label: "Draft n-max", type: "int" },
				{ key: "mtp_draft_n_min", label: "Draft n-min", type: "int" },
				{ key: "mtp_draft_p_min", label: "Draft p-min", type: "float" },
				{ key: "ngram_mod_n_match", label: "ngram n-match", type: "int" },
				{ key: "ngram_mod_n_min", label: "ngram n-min", type: "int" },
				{ key: "ngram_mod_n_max", label: "ngram n-max", type: "int" },
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
	let lint = $state<LintFinding[]>([]);
	let vram = $state<VramEstimate | null>(null);
	let vramAvailable = $state<number | null>(null);
	let saved = $state(false);
	let importing = $state(false);
	let cloning = $state(false);
	let cloneName = $state("");
	let showDeleteConfirm = $state(false);
	let showHistory = $state(false);
	let snapshots = $state<ProfileSnapshot[]>([]);
	let restoreTarget = $state<ProfileSnapshot | null>(null);
	let snapshotting = $state(false);
	let expanded = $state("");
	let diff = $state<SnapshotChange[]>([]);
	let diffLoading = $state(false);
	let scopedTarget = $state<{ snap: string; change: SnapshotChange } | null>(null);

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
			refreshLint();
		}
	});

	function pickProfile(name: string) {
		isNew = false;
		selectedProfile = name;
		loadInto(name ? currentFam.profiles[name] : {});
		refreshLint();
	}

	function onFamilyChange(fam: string) {
		selectedFamily = fam;
		isNew = false;
		const names = Object.keys(allProfiles[fam]?.profiles ?? {}).sort();
		const def = allProfiles[fam]?.default || names[0] || "";
		selectedProfile = def;
		loadInto(def ? allProfiles[fam]?.profiles[def] : {});
		refreshLint();
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
		else if (field.type === "select") form[key] = field.options?.[0] ?? "";
		else if (field.type === "bool") form[key] = true;
		else form[key] = "";
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

	async function refreshLint() {
		if (!selectedFamily || !selectedProfile || isNew) {
			lint = [];
			vram = null;
			vramAvailable = null;
			return;
		}
		try {
			const res = await lintProfile(selectedFamily, selectedProfile);
			lint = res.lint;
			vram = res.vram_estimate;
			vramAvailable = res.vram_available_mb;
		} catch {
			lint = [];
			vram = null;
			vramAvailable = null;
		}
	}

	const gb = (mb: number) => (mb / 1024).toFixed(1);

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
			const result = await upsertProfile(selectedFamily, name, parsed);
			lint = result.lint ?? [];
			await reload();
			isNew = false;
			newName = "";
			selectedProfile = name;
			loadInto(allProfiles[selectedFamily]?.profiles[name] ?? parsed);
			saved = true;
			setTimeout(() => (saved = false), 1500);
			refreshLint();
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

	function snapshotTime(id: string): string {
		// ids look like 20260814T153000123456Z[_label]
		const m = id.match(/^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})/);
		if (!m) return id;
		const [, y, mo, d, h, mi, s] = m;
		return new Date(`${y}-${mo}-${d}T${h}:${mi}:${s}Z`).toLocaleString();
	}

	async function toggleHistory() {
		showHistory = !showHistory;
		if (showHistory) await loadSnapshots();
	}

	async function loadSnapshots() {
		try {
			snapshots = await fetchProfileSnapshots();
		} catch (e: any) {
			error = e.message;
		}
	}

	async function handleSnapshotNow() {
		snapshotting = true;
		error = "";
		try {
			await createProfileSnapshot("manual");
			await loadSnapshots();
		} catch (e: any) {
			error = e.message;
		} finally {
			snapshotting = false;
		}
	}

	async function toggleExpand(id: string) {
		if (expanded === id) {
			expanded = "";
			return;
		}
		expanded = id;
		diff = [];
		diffLoading = true;
		try {
			diff = await fetchSnapshotDiff(id);
		} catch (e: any) {
			error = e.message;
		} finally {
			diffLoading = false;
		}
	}

	async function handleScopedRestore() {
		if (!scopedTarget) return;
		const { snap, change } = scopedTarget;
		scopedTarget = null;
		error = "";
		try {
			await restoreProfileSnapshot(snap, {
				family: change.family,
				profile: change.profile,
			});
			await reload();
			diff = await fetchSnapshotDiff(snap);
			if (change.family === selectedFamily) pickProfile(change.profile);
		} catch (e: any) {
			error = e.message;
		}
	}

	async function handleRestore() {
		if (!restoreTarget) return;
		const id = restoreTarget.id;
		restoreTarget = null;
		error = "";
		try {
			await restoreProfileSnapshot(id);
			await reload();
			await loadSnapshots();
			const names = Object.keys(allProfiles[selectedFamily]?.profiles ?? {}).sort();
			pickProfile(names.includes(selectedProfile) ? selectedProfile : names[0] || "");
		} catch (e: any) {
			error = e.message;
		}
	}

	async function handleDeleteSnapshot(id: string) {
		try {
			await deleteProfileSnapshot(id);
			await loadSnapshots();
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

		<button class="btn-history" class:active={showHistory} onclick={toggleHistory}>
			⏱ History
		</button>
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

	{#if showHistory}
		<div class="history-panel">
			<div class="history-head">
				<strong>Profile history</strong>
				<span class="muted">
					every save, delete, clone and sweep snapshots <code>profiles.json</code> first
				</span>
				<span class="spacer"></span>
				<button onclick={handleSnapshotNow} disabled={snapshotting}>
					{snapshotting ? "Saving…" : "Snapshot now"}
				</button>
			</div>
			{#if snapshots.length === 0}
				<p class="muted">No snapshots yet — the next change will create one.</p>
			{:else}
				<div class="history-scroll">
				<table class="history-table">
					<tbody>
						{#each snapshots as s}
							<tr>
								<td class="h-when">
									<button class="h-expand" onclick={() => toggleExpand(s.id)}>
										{expanded === s.id ? "▾" : "▸"} {snapshotTime(s.id)}
									</button>
								</td>
								<td class="h-label">{s.label || "—"}</td>
								<td class="h-count">{s.families} families · {s.profiles} profiles</td>
								<td class="h-actions">
									<button onclick={() => (restoreTarget = s)}>Restore all</button>
									<button class="btn-del" onclick={() => handleDeleteSnapshot(s.id)}>✕</button>
								</td>
							</tr>
							{#if expanded === s.id}
								<tr>
									<td colspan="4" class="h-diff">
										{#if diffLoading}
											<span class="muted">Comparing…</span>
										{:else if diff.length === 0}
											<span class="muted">Identical to the current config.</span>
										{:else}
											<table class="diff-table">
												<tbody>
													{#each diff as c}
														<tr>
															<td class="d-status {c.status}">
																{c.status === "changed"
																	? "changed"
																	: c.status === "added-since"
																		? "added since"
																		: "deleted since"}
															</td>
															<td class="d-name">{c.family}<span class="muted"> / </span>{c.profile}</td>
															<td class="d-keys">{c.keys.join(", ") || "—"}</td>
															<td class="d-act">
																<button onclick={() => (scopedTarget = { snap: s.id, change: c })}>
																	Restore this
																</button>
															</td>
														</tr>
													{/each}
												</tbody>
											</table>
										{/if}
									</td>
								</tr>
							{/if}
						{/each}
					</tbody>
				</table>
				</div>
				<p class="muted">
					{snapshots.length} snapshot{snapshots.length === 1 ? "" : "s"} · oldest
					{snapshotTime(snapshots[snapshots.length - 1].id)} · capped at 100
				</p>
			{/if}
		</div>
	{/if}

	{#if scopedTarget}
		<div class="confirm-overlay">
			<div class="confirm-box">
				<p>
					Restore <strong>{scopedTarget.change.profile}</strong> in
					<strong>{scopedTarget.change.family}</strong> from
					{snapshotTime(scopedTarget.snap)}?
				</p>
				<p class="muted">
					{#if scopedTarget.change.status === "added-since"}
						This profile didn't exist in the snapshot — restoring is not possible, cancel and
						delete it instead if that's what you want.
					{:else}
						Only this profile changes. Keys affected:
						<code>{scopedTarget.change.keys.join(", ") || "—"}</code>. A snapshot is taken
						first, and any cluster running this profile is restarted.
					{/if}
				</p>
				<div class="confirm-actions">
					<button onclick={() => (scopedTarget = null)}>Cancel</button>
					<button
						class="btn-save"
						disabled={scopedTarget.change.status === "added-since"}
						onclick={handleScopedRestore}>Restore</button
					>
				</div>
			</div>
		</div>
	{/if}

	{#if restoreTarget}
		<div class="confirm-overlay">
			<div class="confirm-box">
				<p>
					Restore <strong>all profiles</strong> from
					<strong>{snapshotTime(restoreTarget.id)}</strong>?
				</p>
				<p class="muted">
					This replaces every family and profile, not just the one you're editing. The current
					state is snapshotted first, so this is undoable. Running clusters are not restarted.
				</p>
				<div class="confirm-actions">
					<button onclick={() => (restoreTarget = null)}>Cancel</button>
					<button class="btn-save" onclick={handleRestore}>Restore</button>
				</div>
			</div>
		</div>
	{/if}

	{#if lint.length > 0 || vram}
		<div class="lint-panel">
			{#each lint as finding}
				<div class="lint-row {finding.level}">
					<span class="lint-badge">{finding.level === "error" ? "dead" : "warn"}</span>
					<code>{finding.field}</code>
					<span>{finding.message}</span>
				</div>
			{/each}
			{#if vram}
				<div class="lint-row vram">
					<span class="lint-badge vram-badge">vram</span>
					<span>
						~{gb(vram.total_mb)} GB estimated
						(weights {gb(vram.weights_mb)} + KV {gb(vram.kv_mb)} @ {vram.ctx.toLocaleString()} ctx
						over {vram.n_layers} layers)
						{#if vramAvailable}of {gb(vramAvailable)} GB available{/if}
					</span>
				</div>
			{/if}
		</div>
	{/if}

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
								<div class="row">
									<label class="inc" title="include this option">
										<input
											type="checkbox"
											checked={has(f.key)}
											onchange={() => toggleInclude(f.key, f)}
										/>
									</label>
									<span class="fname" class:off={!has(f.key)}>{f.label}</span>
										{#if f.type === "bool"}
											<select
												disabled={!has(f.key)}
												value={form[f.key] === false ? "off" : "on"}
												onchange={(e) => (form[f.key] = e.currentTarget.value === "on")}
											>
												<option value="on">on</option>
												<option value="off">off</option>
											</select>
										{:else if f.type === "select"}
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
	.btn-history { font-size: 0.8rem; color: var(--text-muted); }
	.btn-history.active { color: var(--accent, #6c8ebf); border-color: var(--accent, #6c8ebf); }

	.history-panel {
		border: 1px solid var(--border);
		border-radius: 4px;
		background: var(--bg-card);
		padding: 0.6rem 0.75rem;
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}
	.history-head { display: flex; align-items: baseline; gap: 0.5rem; flex-wrap: wrap; }
	.muted { color: var(--text-muted); font-size: 0.8rem; }
	.history-scroll { max-height: 22rem; overflow-y: auto; overflow-x: auto; }
	.history-table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
	.history-table td { padding: 0.28rem 0.4rem; border-top: 1px solid var(--border); }
	.h-when { white-space: nowrap; }
	.h-label { color: var(--accent, #6c8ebf); font-family: monospace; font-size: 0.78rem; }
	.h-count { color: var(--text-muted); white-space: nowrap; }
	.h-actions { text-align: right; white-space: nowrap; }
	.h-actions button { padding: 0.15rem 0.5rem; font-size: 0.78rem; }
	.h-expand {
		border: none;
		background: none;
		padding: 0;
		font-size: 0.82rem;
		color: var(--text);
		cursor: pointer;
	}
	.h-diff { padding: 0.2rem 0.4rem 0.5rem 1.4rem; }
	.diff-table { width: 100%; border-collapse: collapse; font-size: 0.78rem; }
	.diff-table td { padding: 0.2rem 0.4rem; vertical-align: top; }
	.d-status { white-space: nowrap; font-size: 0.72rem; text-transform: uppercase; }
	.d-status.changed { color: #e0a458; }
	.d-status.added-since { color: #6bbf8a; }
	.d-status.deleted-since { color: #e57373; }
	.d-name { font-family: monospace; word-break: break-all; }
	.d-keys { color: var(--text-muted); font-family: monospace; font-size: 0.72rem; }
	.d-act { text-align: right; white-space: nowrap; }
	.d-act button { padding: 0.1rem 0.45rem; font-size: 0.75rem; }

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
	.inc { display: flex; align-items: center; }
	.inc input { cursor: pointer; }
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
	.lint-panel {
		display: flex;
		flex-direction: column;
		gap: 0.35rem;
		margin: 0.5rem 0 0.75rem;
	}
	.lint-row {
		display: flex;
		align-items: baseline;
		gap: 0.5rem;
		font-size: 0.85rem;
		padding: 0.4rem 0.6rem;
		border-radius: 4px;
		border-left: 3px solid transparent;
	}
	.lint-row.error { background: #2b1a1a; border-left-color: #e57373; color: #f0c9c9; }
	.lint-row.warn { background: #2b2517; border-left-color: #e0b155; color: #efe0c2; }
	.lint-row.vram { background: #16222b; border-left-color: #5fa8d3; color: #cfe4f0; }
	.lint-badge {
		flex: 0 0 auto;
		font-size: 0.7rem;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		opacity: 0.85;
	}
	.lint-row code { flex: 0 0 auto; opacity: 0.95; }
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
