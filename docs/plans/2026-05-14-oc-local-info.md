# OpenCode Local Info Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `--info` to print exact resolved local model/server/OpenCode settings without starting anything.

**Architecture:** Extend `scripts/oc-local` option parsing with `--info`. Resolve family/profile metadata in the wrapper, mirroring `start3.sh`, `start4.sh`, and `start5.sh`. Print human-readable fields plus the generated llama-server command and OpenCode config.

**Tech Stack:** Bash, llama.cpp `llama-server`, OpenCode `OPENCODE_CONFIG_CONTENT`, shell dry-run tests.

---

### Task 1: Tests

**Files:**
- Modify: `test_oc_local.sh`

**Steps:**
1. Add assertions for `oc-local gemma-vision reliable --lean --info`.
2. Assert output includes family/profile, quant/context/batch/ubatch/ngl, mmproj mode, model id, remote launcher, and full command.
3. Run `./test_oc_local.sh` and confirm RED failure because `--info` is unknown or not implemented.

### Task 2: Implementation

**Files:**
- Modify: `scripts/oc-local`

**Steps:**
1. Parse `--info` before and after profile arguments.
2. Add metadata variables for repo, quant, ctx, batch, ubatch, ngl, mmproj mode, alias, and fixed common flags.
3. Print info and exit before SSH/OpenCode startup.
4. Preserve `--dry-run` behavior.

### Task 3: Docs And Install

**Files:**
- Modify: `README.md`

**Steps:**
1. Document `--info` usage.
2. Install updated wrapper locally.
3. Run syntax checks, tests, shellcheck, and installed `--info` command.
