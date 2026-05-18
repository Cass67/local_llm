# Gemma OpenCode Profiles Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add Gemma 4 31B launcher profiles and make OpenCode wrapper select Qwen or Gemma.

**Architecture:** Keep Qwen in `scripts/start3.sh`. Add Gemma-specific `scripts/start4.sh`. Extend `scripts/oc-local` with optional model family parsing while keeping Qwen as default for existing commands.

**Tech Stack:** Bash, llama.cpp `llama-server`, OpenCode `OPENCODE_CONFIG_CONTENT`, shell dry-run tests.

---

### Task 1: Wrapper Tests

**Files:**
- Modify: `test_oc_local.sh`

**Steps:**
1. Add failing dry-run assertions for `gemma reliable --lean` and `qwen reliable --lean`.
2. Run `./test_oc_local.sh` and confirm it fails because model family parsing is missing.

### Task 2: Wrapper Implementation

**Files:**
- Modify: `scripts/oc-local`

**Steps:**
1. Parse optional family argument: `qwen` or `gemma`.
2. Preserve existing default behavior as Qwen.
3. Route remote launcher to `./start3.sh` for Qwen and `./start4.sh` for Gemma.
4. Add symlink default family handling for `oc-qwen-*` and `oc-gemma-*`.
5. Run `./test_oc_local.sh` and confirm it passes.

### Task 3: Gemma Launcher

**Files:**
- Create: `scripts/start4.sh`

**Steps:**
1. Add Gemma profile launcher for `unsloth/gemma-4-31B-it-GGUF`.
2. Include `speed`, `fastlong`, `balanced`, `reliable`, and `tiny`.
3. Keep decode flags aligned with `start3.sh`.
4. Run `bash -n scripts/start4.sh`.

### Task 4: Docs And Verification

**Files:**
- Modify: `README.md`

**Steps:**
1. Document Qwen/Gemma usage and symlinks.
2. Run `bash -n scripts/oc-local scripts/start3.sh scripts/start4.sh test_oc_local.sh`.
3. Run `./test_oc_local.sh`.
4. Run `shellcheck scripts/oc-local scripts/start3.sh scripts/start4.sh test_oc_local.sh` if available.
