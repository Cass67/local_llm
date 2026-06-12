<script lang="ts">
  import { onMount } from 'svelte';
  import { fetchModels, fetchCurrentModel, switchModel } from '../lib/api';
  import type { ModelInfo, CurrentModelResponse } from '../lib/types';
  import ModelCard from './ModelCard.svelte';

  let models: ModelInfo[] = $state([]);
  let current: CurrentModelResponse | null = $state(null);
  let switching: string | null = $state(null);
  let selectedBackend: 'rocm' | 'vulkan' = $state('rocm');
  let error: string = $state('');
  let loading: boolean = $state(true);

  async function load() {
    loading = true;
    error = '';
    try {
      const [modelData, currentData] = await Promise.all([
        fetchModels(),
        fetchCurrentModel(),
      ]);
      models = modelData.models;
      current = currentData;
    } catch (e: unknown) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  }

  async function handleSwitch(family: string, profile: string, backend: 'rocm' | 'vulkan') {
    switching = family;
    error = '';
    try {
      await switchModel({ family, profile, backend });
      await load();
    } catch (e: unknown) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      switching = null;
    }
  }

  onMount(load);

  let filteredModels = $derived(
    selectedBackend === 'vulkan'
      ? models.filter(m => m.backend === 'vulkan' || m.family.endsWith('-vulkan'))
      : models.filter(m => m.backend === 'rocm' || !m.family.endsWith('-vulkan'))
  );
</script>

<div class="models-panel">
  {#if error}
    <div class="error">{error}</div>
  {/if}

  <div class="toolbar">
    <div class="backend-toggle">
      <button class:active={selectedBackend === 'rocm'} onclick={() => selectedBackend = 'rocm'}>ROCm</button>
      <button class:active={selectedBackend === 'vulkan'} onclick={() => selectedBackend = 'vulkan'}>Vulkan</button>
    </div>
    <button class="refresh" onclick={load} disabled={loading}>
      {loading ? 'Loading...' : 'Refresh'}
    </button>
  </div>

  {#if current}
    <div class="current-status">
      Running: <strong>{current.alias}</strong> ({current.backend})
      <span class="status-dot" class:active={current.running} class:inactive={!current.running}></span>
      <span class="service-status">{current.llama_server.status}</span>
    </div>
  {/if}

  <div class="model-grid">
    {#each filteredModels as model (model.family + '-' + model.backend)}
      <ModelCard
        {model}
        isRunning={current?.alias === model.alias}
        {switching}
        onSwitch={(profile) => handleSwitch(model.family, profile, model.backend === 'vulkan' ? 'vulkan' : 'rocm')}
      />
    {/each}
  </div>

  {#if filteredModels.length === 0 && !loading}
    <div class="empty">No models accepted yet. Use the CLI or install flow.</div>
  {/if}
</div>

<style>
  .models-panel { display: flex; flex-direction: column; gap: 1rem; }
  .error { background: var(--red); color: white; padding: 0.5rem; border-radius: 4px; }
  .toolbar { display: flex; justify-content: space-between; align-items: center; }
  .backend-toggle { display: flex; gap: 0; }
  .backend-toggle button {
    padding: 0.3rem 0.8rem;
    border: 1px solid var(--border);
    background: var(--bg-card);
    color: var(--text-muted);
    cursor: pointer;
    font-size: 0.85rem;
  }
  .backend-toggle button:first-child { border-radius: 4px 0 0 4px; }
  .backend-toggle button:last-child { border-radius: 0 4px 4px 0; }
  .backend-toggle button.active {
    background: var(--accent);
    color: var(--text);
    border-color: var(--accent);
  }
  .refresh { padding: 0.3rem 0.8rem; border: 1px solid var(--border); background: var(--bg-card); color: var(--text); cursor: pointer; border-radius: 4px; }
  .current-status { padding: 0.5rem; background: var(--bg-card); border-radius: 4px; font-size: 0.9rem; }
  .status-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin: 0 0.3rem; }
  .status-dot.active { background: var(--green); }
  .status-dot.inactive { background: var(--red); }
  .service-status { color: var(--text-muted); font-size: 0.8rem; margin-left: 0.5rem; }
  .model-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 1rem; }
  .empty { text-align: center; color: var(--text-muted); padding: 2rem; }
</style>
