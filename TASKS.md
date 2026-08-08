# Tasks: local_llm improvements

Last updated: 2026-08-07

## Completed

### Wire fdinfo GPU parallelism into mgmt API ✅
Integrate lltop's DRM fdinfo engine-ns sampling and GPU-equivalents occupancy into the management backend so Status tab shows real GPU parallelism. Extract core logic from `lltop/lltop` into a shared module, add `/api/gpu-status` endpoint with per-runner engine metrics, keep lltop as convenience wrapper that calls the same code.

- Created `container/backend/gpu_status.py` — extracted fdinfo parsing, EngineTracker, split-mode detection, parallelism verdict
- Added `/api/gpu-status` to stats route + 2s background sampling loop
- Wired into main.py startup; faults isolated so fdinfo failure doesn't crash mgmt

## Pending

### Pick one source of truth for profile configs
Eliminate the confusing dual-profile setup. Either make repo `configs/profiles.json` authoritative and mount read-only into mgmt, or delete seed concept entirely and manage all profiles through UI API (`/state/profiles.json` only).

**Why:** users edit wrong file silently. README documents it but footgun remains.
**Approach:** likely delete seed — live state is already `/state/profiles.json`, repo file is just noise. update docs to match.

### Warn on unknown profile fields
Log warning when saving profile with unrecognized fields that `runtime.py` will silently ignore (e.g., typo'd `mtp_enabled` → `mtp_enable`). Prevent silent no-ops.

**Why:** documented behavior but still a trap — user enables "MTP" by setting wrong key and gets nothing.
**Approach:** profiles route validates keys against known set before saving; logs warning (or returns 422 with unknown-fields list). keep non-breaking — warn, don't reject.

### Upgrade router to semantic routing
Replace keyword + structural-signal matching with semantic routing using embeddings and cosine similarity against rule targets. More reliable than fragile keyword lists.

**Why:** current router breaks on prompts that describe a task without hitting keywords ("write code for fibonacci" with no "code"/"python" hit). tier-ratchet is naive.
**Approach:** embed prompt (tiny model, cached), cosine-sim against rule embeddings, pick highest match above threshold. still honor explicit keyword rules as override.

### Add runner startup progress endpoint
Stream runner cold-start stages ("pulling image", "loading gguf", "warming up") via `/cluster/status` so UI shows real progress instead of generic spinner. Include in langfuse trace metadata.

**Why:** cold start is slow, user sees no feedback beyond loading spinner.
**Approach:** runtime.py emits stage events during startup; stats route exposes latest stage per cluster; UI polls or SSE-streams it.

### Add state backup/export command
Produce clean export of `~/.local/share/local_llm` (model metadata + profiles + benchmark DBs) as single tar for migration or backup. No implicit coupling — explicit command, not cron.

**Why:** migrating hosts means rsync-ing a bag-of-files with no integrity check.
**Approach:** add `/api/state/export` endpoint that tars the state dir and returns stream; or CLI wrapper in scripts/. keep minimal — one tarball, no compression options to bikeshed about.

### Version benchmark SQLite schema and add profile filter
Add migration layer for chat_metrics/benchmark DBs so new fields don't break old clients. Add query params to filter by profile name and git commit range.

**Why:** adding fields like per-request GPU occupancy requires ALTER TABLE; no versioning yet. also can't filter "runs on this profile" without joining metadata.
**Approach:** add `schema_version` row, migration function in stats.py or benchmark_store.py, add `profile` query param to `/stats/history`.
