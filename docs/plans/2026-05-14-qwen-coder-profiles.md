# Qwen Coder Profiles Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add first-class Qwen Coder profiles optimized for full GPU offload and faster reliable sessions.

**Architecture:** Add repo-managed `scripts/start2.sh` for Qwen3-Coder. Extend `scripts/oc-local` with a `qwen-coder` family, matching symlink parsing, info output, generated OpenCode model id, and remote launcher routing.

**Tech Stack:** Bash, llama.cpp `llama-server`, OpenCode `OPENCODE_CONFIG_CONTENT`, shell dry-run tests.

---

### Task 1: Tests

**Files:**
- Modify: `test_oc_local.sh`

**Steps:**
1. Add assertions that `scripts/start2.sh` uses `unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF` and alias `qwen3-coder-30b-a3b-instruct`.
2. Add assertions that `oc-local qwen-coder reliable --lean --info` reports `quant=UD-Q3_K_XL`, `ctx=65536`, `ngl=999`, `batch=128`, and `ubatch=128`.
3. Add assertions that `oc-qwen-coder-reliable --lean --dry-run` routes to `./start2.sh reliable`.
4. Run `./test_oc_local.sh` and confirm RED failure.

### Task 2: Implementation

**Files:**
- Create/Modify: `scripts/start2.sh`
- Modify: `scripts/oc-local`

**Steps:**
1. Add Qwen Coder launcher profiles:
   - `speed`: `IQ4_XS`, `32768`, `ngl=999`, `512/512`
   - `fastlong`: `IQ4_XS`, `40960`, `ngl=999`, `512/512`
   - `balanced`: `UD-Q3_K_XL`, `49152`, `ngl=999`, `256/256`
   - `reliable`: `UD-Q3_K_XL`, `65536`, `ngl=999`, `128/128`
   - `tiny`: `UD-Q2_K_XL`, `65536`, `ngl=999`, `256/256`
2. Add wrapper family and symlink parsing for `qwen-coder`.
3. Use model id `localllm/qwen3-coder-30b-a3b-instruct`.
4. Run `./test_oc_local.sh` and confirm GREEN.

### Task 3: Docs, Install, Verify

**Files:**
- Modify: `README.md`

**Steps:**
1. Add Qwen Coder profile table and usage examples.
2. Install updated `oc-local` and `oc-qwen-coder-*` symlinks.
3. Copy `scripts/start2.sh` to `ubt26:/home/cass/llama.cpp/start2.sh`.
4. Run syntax checks, dry-run tests, shellcheck, and `oc-qwen-coder-reliable --lean --info`.
5. Start `oc-qwen-coder-reliable --lean` and inspect remote log for full offload.
