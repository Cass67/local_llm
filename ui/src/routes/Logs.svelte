<script lang="ts">
  import LogPanel from '../components/LogPanel.svelte';
</script>

<div class="route">
  <h2>Server Logs</h2>
  <div class="log-wrapper">
    <LogPanel />
  </div>
</div>

<style>
  .route { display: flex; flex-direction: column; height: calc(100vh - 4rem); }
  h2 { margin: 0 0 0.5rem 0; }
  .log-wrapper { flex: 1; min-height: 0; }
</style>
