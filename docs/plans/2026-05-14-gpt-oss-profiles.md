# GPT OSS Profiles Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add and tune gpt-oss-20b profiles so Q8/high reasoning uses full 131k context across the primary profiles.

**Architecture:** Add `scripts/start6.sh` for gpt-oss. Extend `scripts/oc-local` with a `gpt-oss` family, symlink parsing, info output, generated OpenCode model id, and remote launcher routing.

**Tech Stack:** Bash, llama.cpp `llama-server`, OpenCode `OPENCODE_CONFIG_CONTENT`, shell dry-run tests.

---

### Task 1: Tests

**Files:**
- Modify: `test_oc_local.sh`

**Steps:**
1. Add assertions that `scripts/start6.sh` uses `unsloth/gpt-oss-20b-GGUF` and alias `gpt-oss-20b`.
2. Add assertions that `oc-local gpt-oss reliable --lean --info` reports `quant=UD-Q8_K_XL`, `ctx=131072`, `ngl=999`, `batch=128`, and `ubatch=128`.
3. Add assertions that `oc-gpt-oss-reliable --dry-run --lean` routes to `./start6.sh reliable`.
4. Run `./test_oc_local.sh` and confirm RED failure.

### Task 2: Implementation

**Files:**
- Create: `scripts/start6.sh`
- Modify: `scripts/oc-local`

**Steps:**
1. Add gpt-oss launcher profiles:
   - `speed`: `UD-Q8_K_XL`, `131072`, `ngl=999`, `1024/1024`, high reasoning
   - `fastlong`: `UD-Q8_K_XL`, `131072`, `ngl=999`, `512/512`, high reasoning
   - `balanced`: `UD-Q8_K_XL`, `131072`, `ngl=999`, `256/256`, high reasoning
   - `reliable`: `UD-Q8_K_XL`, `131072`, `ngl=999`, `128/128`, high reasoning
   - `tiny`: `UD-Q4_K_XL`, `131072`, `ngl=999`, `256/256`
2. Add wrapper family and symlink parsing for `gpt-oss`.
3. Use model id `localllm/gpt-oss-20b`.
4. Run `./test_oc_local.sh` and confirm GREEN.

### Task 3: Docs, Install, Verify

**Files:**
- Modify: `README.md`

**Steps:**
1. Add gpt-oss profile table and usage examples.
2. Install updated `oc-local` and `oc-gpt-oss-*` symlinks.
3. Copy `scripts/start6.sh` to `ubt26:/home/cass/llama.cpp/start6.sh`.
4. Run syntax checks, dry-run tests, shellcheck, and `oc-gpt-oss-reliable --lean --info`.
5. Start `oc-gpt-oss-reliable --lean` or remote `start6.sh reliable` and inspect startup memory/offload logs.
