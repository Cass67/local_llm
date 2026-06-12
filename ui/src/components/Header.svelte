<script lang="ts">
  let currentRoute = $state('/');
</script>

<header>
  <h1>local_llm</h1>
  <nav>
    <a href="#/models" class:active={currentRoute === '/models'}>Models</a>
    <a href="#/playground" class:active={currentRoute === '/playground'}>Playground</a>
    <a href="#/logs" class:active={currentRoute === '/logs'}>Logs</a>
  </nav>
</header>

<style>
  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.5rem 1rem;
    background: var(--bg-card);
    border-bottom: 1px solid var(--border);
    position: sticky;
    top: 0;
    z-index: 10;
  }
  h1 { margin: 0; font-size: 1.2rem; }
  nav { display: flex; gap: 1rem; }
  a { color: var(--text-muted); text-decoration: none; }
  a.active { color: var(--text); font-weight: bold; }
</style>
