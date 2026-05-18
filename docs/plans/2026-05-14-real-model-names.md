# Real Model Names Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace fake `gpt-4` aliases/model ids with real short model names.

**Architecture:** Keep one OpenCode provider but set model key/name from selected family. Align `llama-server --alias` values with those names so `/v1/models` and OpenCode config match.

**Tech Stack:** Bash, llama.cpp `llama-server`, OpenCode `OPENCODE_CONFIG_CONTENT`, shell dry-run tests.

---

### Task 1: Tests

**Files:**
- Modify: `test_oc_local.sh`

**Steps:**
1. Add assertions that Qwen dry-run reports `model=localllm/qwen3.6-35b-a3b` and config key/name `qwen3.6-35b-a3b`.
2. Add assertions that Gemma dry-run reports `model=localllm/gemma-4-31b-it` and config key/name `gemma-4-31b-it`.
3. Run `./test_oc_local.sh` and confirm RED failure from current `gpt-4` names.

### Task 2: Implementation

**Files:**
- Modify: `scripts/oc-local`
- Modify: `scripts/start3.sh`
- Modify: `scripts/start4.sh`

**Steps:**
1. Map family `qwen` to model alias `qwen3.6-35b-a3b`.
2. Map family `gemma` to model alias `gemma-4-31b-it`.
3. Use selected alias in `OC_LOCAL_MODEL` default and generated config model key/name.
4. Replace `--alias gpt-4` in launchers.
5. Run tests and syntax checks.

### Task 3: Docs And Install

**Files:**
- Modify: `README.md`

**Steps:**
1. Update docs to show real aliases and `OC_LOCAL_MODEL` default behavior.
2. Reinstall wrapper locally and copy launchers to remote host.
3. Verify installed dry-run output.
