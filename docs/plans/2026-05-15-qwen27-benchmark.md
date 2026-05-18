# Qwen 27B Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Benchmark only Qwen3.6 27B profiles and update the fleet so the optimum profiles are where users expect them.

**Architecture:** Use the existing `start8.sh` launcher and `oc-local` wrapper as the source of truth. Benchmark live remote `llama-server` runs for Qwen3.6 27B only, capture load/generation metrics, then update `start8.sh`, `oc-local`, `test_oc_local.sh`, and `README.md` if the evidence shows a better profile mapping.

**Tech Stack:** Bash, llama.cpp `llama-server`, OpenAI-compatible HTTP API, OpenCode wrapper scripts.

---

### Task 1: Capture Current Qwen 27B Profile Matrix

**Files:**
- Read: `scripts/oc-local`
- Read: `scripts/start8.sh`
- Modify: none

- [ ] **Step 1: Record current profile settings**

Run:

```bash
for profile in speed fastlong balanced reliable tiny; do
  oc-qwen-27b-${profile} --lean --info | awk -v p="$profile" 'BEGIN { print "=== " p " ===" } /^(profile|quant|ctx|batch|ubatch|ngl|command)=/'
done
```

Expected current baseline:

```text
speed: IQ4_XS, 32768, 128/128
fastlong: IQ4_XS, 49152, 128/128
balanced: IQ4_XS, 49152, 64/64
reliable: IQ4_XS, 65536, 64/64
tiny: UD-Q3_K_XL, 98304, 64/64
```

### Task 2: Benchmark Live Qwen 27B Profiles

**Files:**
- Read: remote logs under `/home/cass/llama.cpp/llama-*.log`
- Modify: none

- [ ] **Step 1: For each profile, start the server without OpenCode**

Run for each profile:

```bash
ssh ubt26 'pkill -x llama-server || true; deadline=$((SECONDS+30)); while pgrep -x llama-server >/dev/null; do if (( SECONDS >= deadline )); then pkill -9 -x llama-server || true; break; fi; sleep 1; done; cd /home/cass/llama.cpp && rm -f llama-qwen27-bench.log && nohup ./start8.sh PROFILE >llama-qwen27-bench.log 2>&1 < /dev/null &'
```

Replace `PROFILE` with `speed`, `fastlong`, `balanced`, `reliable`, and `tiny`.

- [ ] **Step 2: Wait for API readiness**

Run:

```bash
deadline=$((SECONDS+180)); until curl -fsS http://cass.lan:8080/v1/models >/dev/null 2>&1; do if (( SECONDS >= deadline )); then exit 1; fi; sleep 2; done
```

Expected: exits `0` for stable profiles. If it exits `1`, inspect the remote log and mark profile failed.

- [ ] **Step 3: Capture memory/offload evidence**

Run:

```bash
ssh ubt26 'grep -E "memory breakdown|ROCm0 \(|offloaded|ROCm0 model buffer|KV buffer|compute buffer|n_ctx|n_batch|n_ubatch|server is listening|failed|out of memory|HSA" /home/cass/llama.cpp/llama-qwen27-bench.log'
```

Record: context, quant, GPU layers, model buffer MiB, KV MiB, compute MiB, startup failure if any.

- [ ] **Step 4: Run exact-answer sanity prompt**

Run:

```bash
curl -sS --max-time 180 http://cass.lan:8080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen3.6-27b","messages":[{"role":"user","content":"Think briefly, then answer exactly: READY"}],"max_tokens":512,"temperature":0.6,"top_p":0.95}'
```

Expected: JSON with `finish_reason:"stop"` and `content:"READY"`.

- [ ] **Step 5: Run 5k repo-summary timing prompt**

Run:

```bash
python3 -c 'import json; prompt="Summarize this synthetic repo note in one sentence and end with FINAL: OK.\n" + ("module alpha handles parsing; module beta handles tests; " * 500); print(json.dumps({"model":"qwen3.6-27b","messages":[{"role":"user","content":prompt}],"max_tokens":2048,"temperature":0.6,"top_p":0.95}))' \
  | curl -sS --max-time 240 http://cass.lan:8080/v1/chat/completions \
      -H 'Content-Type: application/json' \
      -d @-
```

Expected: JSON with timing fields. Record `prompt_per_second`, `predicted_per_second`, `finish_reason`, and whether final `content` includes `FINAL: OK.`.

### Task 3: Select Optimum Qwen 27B Mapping

**Files:**
- Modify: `scripts/start8.sh`
- Modify: `scripts/oc-local`
- Modify: `test_oc_local.sh`
- Modify: `README.md`

- [ ] **Step 1: Choose profile roles based on evidence**

Use these rules:

```text
speed: fastest stable profile that returns final content on both prompts.
fastlong: highest-context stable IQ4_XS profile that does not crash.
balanced: same context as fastlong with smaller batch if speed and reliability differ.
reliable: best quality stable profile for OpenCode default.
long context alias/profile: the largest lower-quant stable profile, currently expected to be qwen-27b tiny at 98304.
```

- [ ] **Step 2: Write failing tests for chosen mapping**

Update `test_oc_local.sh` assertions for `qwen-27b` profiles before changing implementation. For example, if keeping current mapping:

```bash
qwen_27b_tiny_info_output="$(run_info qwen-27b tiny --lean)"
assert_contains "$qwen_27b_tiny_info_output" "quant=UD-Q3_K_XL"
assert_contains "$qwen_27b_tiny_info_output" "ctx=98304"
```

Run:

```bash
./test_oc_local.sh
```

Expected: fails if implementation does not match selected optimum mapping.

- [ ] **Step 3: Update implementation**

Modify both `scripts/start8.sh` and `scripts/oc-local` so the selected mapping is identical in both files.

- [ ] **Step 4: Update docs**

Modify `README.md` recommended Qwen 27B rows to describe the final optimum commands and note failed boundaries, e.g. `102400 loaded but crashed on generation; 98304 generated successfully`.

### Task 4: Verify and Install

**Files:**
- Modify: installed `/Users/cass/.local/bin/oc-local`
- Modify: remote `/home/cass/llama.cpp/start8.sh`

- [ ] **Step 1: Run local verification**

Run:

```bash
./test_oc_local.sh
bash -n scripts/oc-local scripts/start8.sh test_oc_local.sh
shellcheck scripts/oc-local scripts/start8.sh test_oc_local.sh
```

Expected: all commands exit `0`.

- [ ] **Step 2: Install updated files**

Run:

```bash
install -m 0755 scripts/oc-local ~/.local/bin/oc-local
scp scripts/start8.sh ubt26:/home/cass/llama.cpp/start8.sh
ssh ubt26 'chmod +x /home/cass/llama.cpp/start8.sh'
```

Expected: all commands exit `0`.

- [ ] **Step 3: Verify installed profile output**

Run:

```bash
oc-qwen-27b-speed --lean --info
oc-qwen-27b-reliable --lean --info
oc-qwen-27b-tiny --lean --info
```

Expected: output reflects selected optimum profile mapping.

---

Self-review:

- Spec coverage: Benchmarks only Qwen3.6 27B and updates optimum config where needed.
- Placeholder scan: No TBD/TODO placeholders remain.
- Type consistency: Profile names match existing wrapper enum: `speed`, `fastlong`, `balanced`, `reliable`, `tiny`.
