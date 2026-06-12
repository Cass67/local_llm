<script lang="ts">
  import Router from 'svelte-spa-router';
  import Models from './routes/Models.svelte';
  import Playground from './routes/Playground.svelte';
  import Logs from './routes/Logs.svelte';
  import Header from './components/Header.svelte';

  const routes = {
    '/': Models,
    '/models': Models,
    '/playground': Playground,
    '/logs': Logs,
  };
</script>

<div class="app">
  <Header />
  <main>
    <Router {routes} />
  </main>
</div>

<style>
  .app {
    display: flex;
    flex-direction: column;
    min-height: 100vh;
  }
  main {
    flex: 1;
    padding: 1rem;
  }
</style>
