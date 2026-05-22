# Hauhau Models Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add Hauhau model families, benchmark them on `ubt26`, and install local shortcuts.

**Architecture:** Add one launcher per model family and wire each into `oc-local` metadata and installer shortcut generation. Benchmark remotely before final profile promotion, using conservative values and lowering context or quant only if needed.

**Tech Stack:** Bash launchers, llama.cpp `llama-server`, Hugging Face GGUF repos, OpenCode local wrapper scripts, SSH to `ubt26`.

---

### Task 1: Add Failing Tests For New Families

**Files:**
- Modify: `test_oc_local.sh`

**Step 1: Add assertions**

Add checks for `qwen-27b-hauhau` and `gemma-hauhau`:

```bash
assert_contains "$installer_contents" "qwen-27b-hauhau"
assert_contains "$installer_contents" "gemma-hauhau"

qwen_27b_hauhau_info="$(run_info qwen-27b-hauhau reliable --lean)"
assert_contains "$qwen_27b_hauhau_info" "family=qwen-27b-hauhau"
assert_contains "$qwen_27b_hauhau_info" "model_name=qwen3.6-27b-hauhau"
assert_contains "$qwen_27b_hauhau_info" "hf_repo=HauhauCS/Qwen3.6-27B-Uncensored-HauhauCS-Aggressive"
assert_contains "$qwen_27b_hauhau_info" "remote_start=./start12.sh reliable"

gemma_hauhau_info="$(run_info gemma-hauhau reliable --lean)"
assert_contains "$gemma_hauhau_info" "family=gemma-hauhau"
assert_contains "$gemma_hauhau_info" "model_name=gemma4-26b-a4b-hauhau"
assert_contains "$gemma_hauhau_info" "hf_repo=HauhauCS/Gemma4-26B-A4B-Uncensored-HauhauCS-Balanced"
assert_contains "$gemma_hauhau_info" "remote_start=./start14.sh reliable"
```

**Step 2: Verify failure**

Run: `bash test_oc_local.sh`

Expected: FAIL because the new families and launchers are not implemented.

### Task 2: Add Launchers And Metadata

**Files:**
- Create: `scripts/start12.sh`
- Create: `scripts/start14.sh`
- Modify: `scripts/oc-local`
- Modify: `installer.sh`

**Step 1: Create launchers**

Create launchers following the `start11.sh` style. Use aliases:

- `qwen3.6-27b-hauhau`
- `gemma4-26b-a4b-hauhau`

Use `--hf-file` with:

- `Qwen3.6-27B-Uncensored-HauhauCS-Aggressive-IQ4_XS.gguf`
- `Gemma4-26B-A4B-Uncensored-HauhauCS-Balanced-IQ4_XS.gguf`

**Step 2: Wire `oc-local`**

Add basename mappings and family cases for:

- `qwen-27b-hauhau`
- `gemma-hauhau`

Use reliable defaults `ctx=65536`, `batch=64`, `ubatch=64`, `ngl=999`.

**Step 3: Update installer**

Add the two families to the family/profile wrapper loop and add base reliable wrappers if needed.

**Step 4: Verify**

Run:

```bash
bash -n scripts/oc-local installer.sh scripts/start12.sh scripts/start14.sh test_oc_local.sh
shellcheck scripts/oc-local installer.sh scripts/start12.sh scripts/start14.sh
bash test_oc_local.sh
```

Expected: syntax and shellcheck pass; tests pass unless unrelated existing test failures surface.

### Task 3: Install And Copy Launchers

**Files:**
- Remote: `/home/cass/llama.cpp/start12.sh`
- Remote: `/home/cass/llama.cpp/start14.sh`

**Step 1: Install local shortcuts**

Run: `./installer.sh`

Expected: `~/.local/bin/oc-qwen-27b-hauhau` and `~/.local/bin/oc-gemma-hauhau` exist.

**Step 2: Copy remote launchers**

Run:

```bash
scp scripts/start12.sh scripts/start14.sh ubt26:/home/cass/llama.cpp/
ssh ubt26 'chmod +x /home/cass/llama.cpp/start12.sh /home/cass/llama.cpp/start14.sh && bash -n /home/cass/llama.cpp/start12.sh /home/cass/llama.cpp/start14.sh'
```

Expected: exit code 0.

### Task 4: Benchmark New Models

**Files:**
- Create: `docs/benchmarks/2026-05-19-hauhau-models.md`

**Step 1: Stop current llama-server**

Run: `ssh ubt26 'pkill -f "[l]lama-server" 2>/dev/null || true'`

**Step 2: Smoke each launcher**

For each start script, run it under `timeout 180` and inspect whether it loads or OOMs:

```bash
ssh ubt26 'cd /home/cass/llama.cpp && timeout 180 ./start12.sh reliable >/tmp/start12-hauhau.log 2>&1; echo start12=$?; tail -80 /tmp/start12-hauhau.log'
```

Repeat for `start14.sh`.

**Step 3: Record results**

Write a markdown table with load status, chosen quant, context, batch, and any tok/s lines if a completion probe is run.

### Task 5: Final Verification

**Files:**
- All changed local files

Run:

```bash
bash -n scripts/oc-local installer.sh scripts/start11.sh scripts/start12.sh scripts/start14.sh test_oc_local.sh
shellcheck scripts/oc-local installer.sh scripts/start11.sh scripts/start12.sh scripts/start14.sh
```

Verify installed shortcuts with `--info --lean` for each new base command.
