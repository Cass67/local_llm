<script lang="ts">
  import { onMount, onDestroy, tick } from 'svelte';
  import { scrollToBottom } from '../lib/scroll';

  let lines: string[] = $state([]);
  let connected: boolean = $state(false);
  let autoScroll: boolean = $state(true);
  let source: 'runner' | 'mgmt' = $state('runner');
  let eventSource: EventSource | null = null;
  let logContainer: HTMLDivElement | undefined = $state();

  function connect() {
    eventSource?.close();
    lines = [];
    connected = false;

    eventSource = new EventSource(`/api/local-llm/logs/stream?source=${source}`);
    eventSource.onopen = () => { connected = true; };

    eventSource.addEventListener('log', (e: MessageEvent) => {
      lines = [...lines, e.data];
      if (lines.length > 500) lines = lines.slice(-500);
      if (autoScroll) {
        tick().then(() => {
          if (autoScroll && logContainer) scrollToBottom(logContainer);
        });
      }
    });

    eventSource.onerror = () => {
      connected = false;
      eventSource?.close();
      setTimeout(connect, 3000);
    };
  }

  onMount(connect);
  onDestroy(() => eventSource?.close());
</script>

<div class="log-panel">
  <div class="log-toolbar">
    <span class="status" class:connected>
      {connected ? '● Live' : '○ Disconnected'}
    </span>
    <span class="line-count">{lines.length} lines</span>
    <select bind:value={source} onchange={connect}>
      <option value="runner">Runner logs</option>
      <option value="mgmt">Management/API logs</option>
    </select>
    <button onclick={connect} disabled={connected}>Reconnect</button>
    <label>
      <input type="checkbox" bind:checked={autoScroll} />
      Auto-scroll
    </label>
    <button onclick={() => lines = []}>Clear</button>
  </div>
  <div class="log-container" bind:this={logContainer}>
    {#each lines as line, i}
      <div class="log-line">
        <span class="line-num">{i + 1}</span>
        <span class="line-text">{line}</span>
      </div>
    {/each}
    {#if lines.length === 0}
      <div class="empty">Waiting for log output...</div>
    {/if}
  </div>
</div>

<style>
  .log-panel { display: flex; flex-direction: column; height: 100%; }
  .log-toolbar {
    display: flex;
    align-items: center;
    gap: 1rem;
    padding: 0.3rem 0.5rem;
    background: var(--bg-card);
    border-bottom: 1px solid var(--border);
    font-size: 0.8rem;
    flex-shrink: 0;
  }
  .status { color: var(--red); }
  .status.connected { color: var(--green); }
  .line-count { color: var(--text-muted); }
  .log-toolbar button, .log-toolbar select {
    padding: 0.2rem 0.5rem;
    border: 1px solid var(--border);
    background: var(--bg);
    color: var(--text);
    border-radius: 3px;
    cursor: pointer;
    font-size: 0.75rem;
  }
  .log-container {
    flex: 1;
    overflow-y: auto;
    background: #000;
    padding: 0.5rem;
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 0.8rem;
    line-height: 1.4;
  }
  .log-line { display: flex; gap: 1rem; }
  .log-line:hover { background: #ffffff08; }
  .line-num { color: var(--text-muted); min-width: 3rem; text-align: right; user-select: none; }
  .line-text { white-space: pre-wrap; word-break: break-all; }
  .empty { color: var(--text-muted); text-align: center; padding: 2rem; }
</style>
