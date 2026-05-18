# Gemma Vision Profiles Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Provide separate Gemma text-only and Gemma vision launch paths.

**Architecture:** Keep `scripts/start4.sh` as text-only Gemma with `--no-mmproj`. Add `scripts/start5.sh` for Gemma vision without `--no-mmproj`, using lower-memory profiles. Extend `scripts/oc-local` family parsing with `gemma-vision` and matching model alias.

**Tech Stack:** Bash, llama.cpp `llama-server`, OpenCode `OPENCODE_CONFIG_CONTENT`, shell dry-run tests.

---

### Task 1: Tests

**Files:**
- Modify: `test_oc_local.sh`

**Steps:**
1. Add assertions that `start4.sh` contains `--no-mmproj`.
2. Add assertions that `start5.sh` exists, does not contain `--no-mmproj`, and uses `--alias gemma-4-31b-it-vision`.
3. Add dry-run assertions for `oc-local gemma-vision reliable --lean` routing to `./start5.sh reliable` and `localllm/gemma-4-31b-it-vision`.
4. Run `./test_oc_local.sh` and confirm RED failure because `start5.sh` and family parsing are missing.

### Task 2: Implementation

**Files:**
- Create: `scripts/start5.sh`
- Modify: `scripts/oc-local`

**Steps:**
1. Add `scripts/start5.sh` with Gemma vision profiles and no `--no-mmproj`.
2. Add `gemma-vision` to wrapper family parsing.
3. Add symlink defaults for `oc-gemma-vision-*`.
4. Use model name `gemma-4-31b-it-vision`.
5. Run tests.

### Task 3: Docs And Install

**Files:**
- Modify: `README.md`

**Steps:**
1. Document text-only and vision Gemma commands.
2. Install updated wrapper and copy launchers to `ubt26`.
3. Run syntax, tests, shellcheck, and installed dry-runs.
