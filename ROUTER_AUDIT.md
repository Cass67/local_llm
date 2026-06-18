# Model Router Audit — model-router Branch (v2)

## Plan (from commit messages)

The model router plan was built incrementally across 6 commits:

1. **68db62c** — Route by cluster names (not hardcoded model aliases), first-match-wins keyword routing, fallback support, health checks via `/api/clusters`
2. **30c433d** — Backend API: GET/PUT `/api/router/config`, proxy to router health, live config reload
3. **291a88b** — Router UI in Architecture tab: status indicator, enable/disable toggle, rules table with inline edit/delete, add rule form
4. **3e97329** — Containerize router (Docker, :3200), live config reload on each health tick, enabled flag bypass, expand routing rules
5. **ae4d8bf** — Log routing decision per request (model chosen + prompt prefix)
6. **e11b607** — Add router log source to LogPanel dropdown

## Code Matches Plan ✓

**Core router** (`scripts/model_router.py`) — ✓ matches plan
- First-match-wins keyword routing (`_route()`)
- Cluster name resolution via `/api/clusters` (not hardcoded model aliases)
- Fallback support (both model aliases and cluster names)
- Health check interval (10s), reloaded on each health tick
- Enabled flag — bypasses routing when disabled
- Default model: null → picks first healthy model dynamically
- Logs routing decision: `print(f"router: {chosen!r} ← {prompt[:80]!r}")`
- `/health` exposes `cluster_map` for debugging

**Backend API** (`container/backend/routes/router_config.py`) — ✓ matches plan
- GET/PUT `/api/router/config` — read/write `router_rules.json` from state dir
- GET `/api/router/health` — proxies to router :3200, returns `running:false` if offline
- Validation: required `backend_url`, `rules` must be list, each rule needs `keywords` + (`cluster` or `model`)

**UI** (`Architecture.svelte`) — ✓ matches plan
- Status indicator (online/offline) with live `cluster→model` map
- Enable/disable toggle (saves immediately)
- Rules table with inline edit and delete per row
- Add rule form with cluster dropdown populated from existing clusters
- Backed by `GET/PUT /api/router/config` and `GET /api/router/health`

**Logging** (`LogPanel.svelte`) — ✓ matches plan
- Router log source in dropdown: `Router logs`
- `source === 'router'` → streams from `local-llm-router` container

---

## Bugs

### 1. Router's `/v1/` routes NOT exposed through Caddy

**Severity: HIGH**

The Caddyfile (`scripts/Caddyfile.local-llm`) has no routing for the router's `/v1/` endpoints. The management backend is at :3100, the router is at :3200. The Caddyfile proxies `/v1/*` to :3100 (management), but the router's `/v1/chat/completions` and `/v1/models` are on :3200.

**Impact:** If the intent is for the router to be a transparent proxy for all `/v1/` LLM requests, requests hitting the Caddy proxy will never reach the router — they'll go straight to the management backend instead.

**Fix:** Add routing in `scripts/Caddyfile.local-llm`:

```caddyfile
# Router — all /v1/ LLM requests go through the keyword router
handle /v1/* {
    reverse_proxy 127.0.0.1:3200
}
```

Then update the management backend's `/v1/*` proxy to exclude these paths, or remove the management backend's `/v1/` proxy entirely if the router is the sole LLM entrypoint.

**Current Caddyfile lines 21-23:**
```caddyfile
handle /v1/* {
    reverse_proxy 127.0.0.1:3100
}
```

**Note:** The Open WebUI at :3101 is configured to use `OPENAI_API_BASE_URL: http://127.0.0.1:3100/v1` (management backend, not the router). If the router should serve Open WebUI too, that env var needs changing.

---

### 2. Router health check silent degradation

**Severity: MEDIUM**

`scripts/model_router.py` lines 72-79: the router calls `/api/clusters` to build the `cluster_map` for routing by cluster name. If the management backend is down, the router silently loses cluster-based routing and falls back to model-alias-only routing.

**Impact:** If the management backend is unavailable, the router can still route by model alias (from `/v1/models`), but cluster-based rules won't resolve — they'll be skipped, and the fallback/default model will be used instead.

**Fix:** Add a warning log when `/api/clusters` fails, and consider making the router resilient to management backend outages by caching the last-known cluster map:

```python
# In model_router.py, around line 80:
except Exception as exc:
    print(f"router: health refresh failed: {exc}", flush=True)
    # Don't clear cluster_map on failure — keep last-known state
```

Currently the code only sets `_last_health_check` but does clear `_cluster_to_model` on failure (the global assignment on line 59 runs before the try block on line 64). The fix: move `_cluster_to_model = {}` into the try block so it only clears on success.

---

### 3. Empty keywords list not rejected by backend validation

**Severity: MEDIUM**

`container/backend/routes/router_config.py` line 40-41 validates that each rule needs `keywords` as a list, but doesn't validate that it's non-empty:

```python
if not isinstance(rule.get("keywords"), list):
    raise HTTPException(status_code=422, detail="each rule needs a keywords list")
```

**Impact:** An empty keywords list means the rule will never match (`any(kw in prompt for kw in [])` is always False in `_route()`). The UI allows creating such rules, and the backend doesn't reject them.

**Fix:** Add non-empty validation in `container/backend/routes/router_config.py`:

```python
if not isinstance(rule.get("keywords"), list):
    raise HTTPException(status_code=422, detail="each rule needs a keywords list")
if not rule.get("keywords"):
    raise HTTPException(status_code=422, detail="each rule needs at least one keyword")
```

---

### 4. UI add rule form doesn't support model alias targets

**Severity: LOW**

`Architecture.svelte` lines 398-402: the add rule form only has a cluster dropdown (`<select bind:value={newRule.cluster}>`), no model alias input. The backend API and the router both support `model` as an alternative to `cluster`, but the UI doesn't expose it.

**Impact:** Users can't create rules that target specific model aliases directly (only cluster names). This is a UX gap.

**Fix:** Add a model alias dropdown alongside the cluster dropdown in the add rule form:

```svelte
<select bind:value={newRule.cluster}>
    <option value="">— cluster —</option>
    {#each clusters as c}
        <option value={c.name}>{c.name}</option>
    {/each}
</select>
<select bind:value={newRule.model}>
    <option value="">— model —</option>
    {#each models as m}
        <option value={m.alias}>{m.alias}</option>
    {/each}
</select>
```

And update the add rule validation:

```svelte
<button onclick={addRule} disabled={!newRule.name || !newRule.keywords.length || (!newRule.cluster && !newRule.model)}>Add</button>
```

---

## Minor Observations (no fix needed)

### Router config path consistency

Backend (`container/backend/config.py`): `ROUTER_CONFIG = Path(os.environ.get("ROUTER_CONFIG", str(STATE_DIR / "router_rules.json")))`

Router (`scripts/model_router.py`): `_STATE_CONFIG = Path(os.environ.get("ROUTER_CONFIG", "")) or Path(os.environ.get("LOCAL_LLM_STATE_DIR", "/state")) / "router_rules.json"`

Both resolve to the same path when the env vars are set. ✓ No mismatch in practice.

### Router bypasses routing when model is already set explicitly

`scripts/model_router.py` line 234: `if ENABLED and not (isinstance(payload.get("model"), str) and payload["model"])`

This means if a client sends `{"model": "gpt-4"}`, the router passes it through without routing — even if routing is enabled. This is correct behavior for clients that want to override, but it means the router's keyword routing is only used when `model` is omitted or empty.

### Router health check interval is shared with config reload

`scripts/model_router.py` line 27: `HEALTH_INTERVAL: int = 10`

Config reload is triggered inside `_maybe_refresh()`, which runs on every health check. If the config file is large or the filesystem is slow, this could add latency to the health check. Unlikely to be a problem in practice but worth noting.
