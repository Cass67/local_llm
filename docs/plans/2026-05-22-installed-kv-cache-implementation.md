# Installed Model KV Cache Benchmark Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Benchmark default, `q8_0/q8_0`, and selective `q4_0/q4_0` KV cache modes across installed reliable model families on `ubt26`.

**Architecture:** Add a temporary benchmark runner that starts llama.cpp directly with each family’s reliable launcher settings plus optional KV flags, probes the API, captures logs, and writes a Markdown report. Do not change launcher defaults until results are reviewed.

**Tech Stack:** Bash, llama.cpp `llama-server`, Hugging Face cached GGUFs, `curl`, user systemd on `ubt26`, Markdown benchmark report.

---

### Task 1: Create A Remote KV Benchmark Runner

**Files:**
- Create: `scripts/bench-installed-kv-remote.sh`

**Step 1: Write the script**

Create a Bash script that runs on `ubt26` from `/home/cass/llama.cpp`.

The script must:

- accept no arguments for the full benchmark.
- define benchmark cases for these reliable families: `qwen`, `qwen-hauhau`, `qwen-27b-hauhau`, `gemma-hauhau`, `qwen-27b`, `qwen-coder`, `gemma`, `gemma-vision`, `gpt-oss`, `deepseek-r1`, `qwen-opus`, `qwen-heretic`.
- encode each case’s repo, hf-file or quant selector, alias, context, batch, ubatch, mmproj mode, and extra template/reasoning flags based on `scripts/oc-local --info <family> reliable --lean` and the actual launcher scripts.
- run each case with KV modes `default` and `q8_0`.
- run `q4_0` only when an environment variable `RUN_Q4=1` is set or when rerun manually for selected cases.
- stop any existing `llama-server` process before each benchmark command and restore the user service at the end.
- use a temp log per run.
- wait for `/v1/models` on `127.0.0.1:8080`.
- run a sanity chat completion with `max_tokens: 64`, `temperature: 0`, prompt `Reply with exactly: ok`.
- print one TSV line per run with fields:
  `family`, `model`, `kv`, `ctx`, `quant`, `mmproj`, `status`, `prompt_tps`, `decode_tps`, `kv_log`, `sanity`, `notes`.

Keep the script minimal and self-contained. Avoid changing persistent launchers.

**Step 2: Syntax check**

Run: `bash -n scripts/bench-installed-kv-remote.sh`

Expected: exit code 0.

Run: `shellcheck scripts/bench-installed-kv-remote.sh`

Expected: exit code 0.

### Task 2: Copy Runner And Run Pass 1

**Files:**
- Remote: `/home/cass/llama.cpp/bench-installed-kv-remote.sh`
- Create local raw output: `/tmp/installed-kv-pass1.tsv`

**Step 1: Copy runner**

Run:

```bash
scp scripts/bench-installed-kv-remote.sh ubt26:/home/cass/llama.cpp/bench-installed-kv-remote.sh
ssh ubt26 'chmod +x /home/cass/llama.cpp/bench-installed-kv-remote.sh && bash -n /home/cass/llama.cpp/bench-installed-kv-remote.sh'
```

Expected: exit code 0.

**Step 2: Run pass 1**

Run:

```bash
ssh ubt26 'cd /home/cass/llama.cpp && ./bench-installed-kv-remote.sh' | tee /tmp/installed-kv-pass1.tsv
```

Expected: TSV rows for each family with `default` and `q8_0`, plus failure rows for models that do not load.

### Task 3: Decide And Run Selective q4_0 Pass

**Files:**
- Create local raw output: `/tmp/installed-kv-q4.tsv`

**Step 1: Inspect pass 1**

Select q4 candidates where:

- default or q8 failed/OOMed.
- q8 reduced speed sharply but context pressure is high.
- KV log suggests large memory pressure.

**Step 2: Run q4 only for selected cases**

Either set an environment variable accepted by the runner, or temporarily edit a remote-only case list without changing repo files.

Run:

```bash
ssh ubt26 'cd /home/cass/llama.cpp && RUN_Q4=1 ./bench-installed-kv-remote.sh' | tee /tmp/installed-kv-q4.tsv
```

If the runner only supports all q4 with `RUN_Q4=1`, it is acceptable to stop early if enough q4 data is gathered.

### Task 4: Write Benchmark Report

**Files:**
- Create: `docs/benchmarks/2026-05-22-installed-kv-cache.md`

**Step 1: Write report**

Create a Markdown report with:

- host/runtime details.
- installed/cached model inventory summary.
- table columns: family, model, quant, context, KV mode, mmproj, status, prompt tok/s, decode tok/s, KV log, sanity, notes.
- per-family recommendation: default KV, `q8_0`, `q4_0`, or inconclusive.
- promotion summary: which launchers, if any, should change later.

**Step 2: Verify report consistency**

Check the report against `/tmp/installed-kv-pass1.tsv` and `/tmp/installed-kv-q4.tsv`.

Expected: every successful or failed run appears in the report, and recommendations are justified by the data.

### Task 5: Restore Service And Verify

**Files:**
- Remote: `/home/cass/llama.cpp/current-model.env`

**Step 1: Restore user service**

Prefer the model that was active before benchmarking unless it failed. Current pre-benchmark state was:

```text
REMOTE_SCRIPT=./start12.sh
REMOTE_PROFILE=reliable
```

Run:

```bash
ssh ubt26 'cd /home/cass/llama.cpp && cat > current-model.env <<"EOF"
REMOTE_SCRIPT=./start12.sh
REMOTE_PROFILE=reliable
EOF
systemctl --user restart llama-server.service'
```

**Step 2: Verify API**

Run:

```bash
ssh ubt26 'for i in $(seq 1 180); do curl -fsS --max-time 2 http://127.0.0.1:8080/v1/models && exit 0; sleep 2; done; exit 1'
```

Expected: `qwen3.6-27b-hauhau` model response with `multimodal` capability.

**Step 3: Verify exact probe**

Run the `Reply with exactly: ok` chat probe against `qwen3.6-27b-hauhau`.

Expected: `content: "ok"`, HTTP 200.

### Task 6: Final Local Verification

**Files:**
- Test relevant changed files only.

**Step 1: Syntax and lint**

Run:

```bash
bash -n scripts/bench-installed-kv-remote.sh
shellcheck scripts/bench-installed-kv-remote.sh
```

Expected: exit code 0.

**Step 2: Status summary**

Run:

```bash
git status --short
```

Expected: benchmark script/report/design/plan are changed or added; no unexpected destructive changes.
