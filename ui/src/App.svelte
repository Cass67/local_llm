<script lang="ts">
  import Router from 'svelte-spa-router';
  import Models from './routes/Models.svelte';
  import Logs from './routes/Logs.svelte';
  import Search from './routes/Search.svelte';
  import Status from './routes/Status.svelte';
  import Benchmarks from './routes/Benchmarks.svelte';
  import Architecture from './routes/Architecture.svelte';
  import Profiles from './routes/Profiles.svelte';
  import Coding from './routes/Coding.svelte';
  import Tuning from './routes/Tuning.svelte';
  import Header from './components/Header.svelte';

  const routes = {
    '/': Architecture,
    '/models': Models,
    '/search': Search,
    '/logs': Logs,
    '/status': Status,
    '/benchmarks': Benchmarks,
    // The leaderboard moved onto the Benchmarks page; keep the old URL working
    // for bookmarks and tabs left open from before the merge.
    '/leaderboard': Benchmarks,
    '/architecture': Architecture,
    '/profiles': Profiles,
    '/coding': Coding,
    '/tuning': Tuning,
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
