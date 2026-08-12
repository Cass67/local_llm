# Tasks: local_llm improvements

Last updated: 2026-08-07

## Completed

### Wire fdinfo GPU parallelism into mgmt API ✅
Integrate lltop's DRM fdinfo engine-ns sampling and GPU-equivalents occupancy into the management backend so Status tab shows real GPU parallelism. Extract core logic from `lltop/lltop` into a shared module, add `/api/gpu-status` endpoint with per-runner engine metrics, keep lltop as convenience wrapper that calls the same code.

- Created `container/backend/gpu_status.py` — extracted fdinfo parsing, EngineTracker, split-mode detection, parallelism verdict
- Added `/api/gpu-status` to stats route + 2s background sampling loop
- Wired into main.py startup; faults isolated so fdinfo failure doesn't crash mgmt

### Pick one source of truth for profile configs
Eliminated the dual-profile setup. `/state/profiles.json` is now the only profile store.

- Deleted `configs/profiles.json` (the seed) — it held 2 families against the live file's ~60
- `installer.sh` no longer copies a seed over the live file on every install; it migrates the legacy `config/profiles.json` location once, then bootstraps an empty file only when none exists
- `scripts/lib.sh` gained `STATE_DIR`; `PROFILES_JSON` now resolves to `$STATE_DIR/profiles.json` in lib.sh, model-manager.sh, and update-manager.sh
- `LOCAL_LLM_PROFILES_JSON` still overrides everywhere (used by tests)

### Fail loudly on a stale cluster definition
`visible_devices_for()` returns `""` when a cluster's `gpu_pci_ids` match nothing in
the inventory, and the caller's `if vd:` then skipped the assignment, leaving
`cfg["visible_devices"]` at whatever the profile carried. That is how the 2-GPU box
ran with `HIP_VISIBLE_DEVICES=0,1,2`. `_assert_cluster_gpus_present()` now raises
instead, checking PCI-id membership rather than resolved index so a Vulkan cluster
with no `vulkan_index` is still allowed. Regression tests in `tests/test_clusters.py`.

## Pending

### test_oc_local.sh: 123 stale README assertions
The suite aborted at line 69 on a doc `faf3dc2` deleted in June; that read and its two
assertions are now gone, which unmasked the real problem. `b3e11ed` rewrote the README
for the container architecture, but ~123 `assert_contains "$readme_contents" ...` still
guard the old systemd + OpenCode-web + Caddy docs — including an `assert_not_contains`
for `docker compose up -d`, now the primary install path. Suite cannot pass until these
go. 767 asserts total, 208 are doc guards; the Caddyfile/service-file guards (14) look
current, so this is a targeted deletion of the README block, not all doc guards.

**Why:** the suite has been unrunnable since June, so nothing in it is protecting anything.
**Approach:** delete the obsolete README assertions; consider whether doc-guarding prose
at this granularity earns its keep at all, or whether only the command examples should be
asserted.

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
