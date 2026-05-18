# Heretic 256k Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Empirically measure whether `qwen-heretic` can load and respond at 128k, 196k, or 256k context on the RX 7900 XT, and identify the minimum quant/profile needed.

**Architecture:** Run a remote benchmark script on `ubt26` that serially restarts `llama-server` for each quant/context pair, captures logs, probes `/v1/models` and a tiny completion, then writes a CSV and log summary. Do not change permanent profiles until the results are known.

**Tech Stack:** Bash, SSH, curl, llama.cpp `llama-server`, ROCm, existing remote directory `/home/cass/llama.cpp`.

---

## Files

- Create local helper: `scripts/bench-heretic-context.sh`
- Create results directory: `docs/benchmarks/`
- Create result file after run: `docs/benchmarks/YYYY-MM-DD-heretic-context.md`
- Remote temporary files under `/home/cass/llama.cpp/bench-heretic-context/`

## Task 1: Write Benchmark Script

**Files:**
- Create: `scripts/bench-heretic-context.sh`

- [ ] **Step 1: Create script**

Create `scripts/bench-heretic-context.sh` with these behaviors:

```bash
#!/usr/bin/env bash
set -euo pipefail

remote_host="${OC_LOCAL_REMOTE_HOST:-ubt26}"
remote_dir="${OC_LOCAL_REMOTE_DIR:-/home/cass/llama.cpp}"
bench_dir="$remote_dir/bench-heretic-context"

ssh "$remote_host" "mkdir -p '$bench_dir' '$remote_dir/templates'"
ssh "$remote_host" "test -f '$remote_dir/templates/qwen36-opencode.jinja'"

ssh "$remote_host" "cat > '$bench_dir/run.sh'" <<'REMOTE'
#!/usr/bin/env bash
set -euo pipefail

cd /home/cass/llama.cpp
mkdir -p bench-heretic-context/logs
csv='bench-heretic-context/results.csv'
printf 'quant,ctx,status,model_mib,kv_mib,rs_mib,compute_mib,free_mib,prompt_tps,decode_tps,reason\n' > "$csv"

repo='DavidAU/Qwen3.6-27B-Heretic-Uncensored-FINETUNE-NEO-CODE-Di-IMatrix-MAX-GGUF'
template='/home/cass/llama.cpp/templates/qwen36-opencode.jinja'
alias='qwen3.6-27b-heretic-bench'

quants=(
  'Qwen3.6-27B-NEO-CODE-HERE-2T-OT-Q4_K_M.gguf'
  'Qwen3.6-27B-NEO-CODE-HERE-2T-OT-Q4_K_S.gguf'
  'Qwen3.6-27B-NEO-CODE-HERE-2T-OT-IQ4_XS.gguf'
  'Qwen3.6-27B-NEO-CODE-HERE-2T-OT-IQ3_M.gguf'
  'Qwen3.6-27B-NEO-CODE-HERE-2T-OT-IQ2_M.gguf'
)
contexts=(65536 98304 131072 196608 262144)

stop_server() {
  pkill -f './build/bin/llama-server .*qwen3.6-27b-heretic-bench' 2>/dev/null || true
  pkill -f './build/bin/llama-server .*qwen3.6-27b-heretic-code' 2>/dev/null || true
  sleep 3
}

extract_first_number() {
  local pattern="$1"
  local file="$2"
  grep -E "$pattern" "$file" | tail -1 | grep -Eo '[0-9]+([.][0-9]+)?' | tail -1 || true
}

for quant in "${quants[@]}"; do
  for ctx in "${contexts[@]}"; do
    stop_server
    safe_quant="${quant//[^A-Za-z0-9_]/_}"
    log="bench-heretic-context/logs/${safe_quant}-${ctx}.log"
    : > "$log"

    ./build/bin/llama-server \
      -hf "$repo" \
      --hf-file "$quant" \
      --chat-template-file "$template" \
      --no-mmproj \
      --host 0.0.0.0 \
      --port 8080 \
      -ngl 999 \
      -c "$ctx" \
      --flash-attn on \
      -ub 64 \
      -b 64 \
      --threads "$(nproc)" \
      --prio 2 \
      --no-warmup \
      --temp 0.6 \
      --top-p 0.95 \
      --top-k 20 \
      --min-p 0.0 \
      --presence-penalty 0.0 \
      --alias "$alias" > "$log" 2>&1 &
    pid=$!

    status='fail'
    reason='startup_timeout'
    for _ in $(seq 1 90); do
      if curl -fsS http://127.0.0.1:8080/v1/models >/dev/null 2>&1; then
        status='loaded'
        reason='loaded'
        break
      fi
      if ! kill -0 "$pid" 2>/dev/null; then
        reason='process_exited'
        break
      fi
      sleep 2
    done

    prompt_tps=''
    decode_tps=''
    if [[ "$status" == loaded ]]; then
      if curl -fsS http://127.0.0.1:8080/v1/chat/completions \
        -H 'Content-Type: application/json' \
        -d '{"model":"qwen3.6-27b-heretic-bench","messages":[{"role":"user","content":"Say OK only."}],"max_tokens":64}' >> "$log" 2>&1; then
        reason='completion_ok'
      else
        status='completion_fail'
        reason='completion_failed'
      fi
      sleep 2
    fi

    model_mib="$(grep -E 'ROCm0 model buffer size' "$log" | tail -1 | grep -Eo '[0-9]+([.][0-9]+)?' | tail -1 || true)"
    kv_mib="$(grep -E 'ROCm0 KV buffer size' "$log" | tail -1 | grep -Eo '[0-9]+([.][0-9]+)?' | tail -1 || true)"
    rs_mib="$(grep -E 'ROCm0 RS buffer size' "$log" | tail -1 | grep -Eo '[0-9]+([.][0-9]+)?' | tail -1 || true)"
    compute_mib="$(grep -E 'ROCm0 compute buffer size' "$log" | tail -1 | grep -Eo '[0-9]+([.][0-9]+)?' | tail -1 || true)"
    free_mib="$(grep -E 'memory breakdown.*ROCm0|ROCm0 \(RX 7900 XT\)' "$log" | tail -1 | awk '{print $9}' || true)"
    prompt_tps="$(grep -E 'prompt eval time' "$log" | tail -1 | grep -Eo '[0-9]+([.][0-9]+)? tokens per second' | grep -Eo '^[0-9]+([.][0-9]+)?' || true)"
    decode_tps="$(grep -E '^       eval time' "$log" | tail -1 | grep -Eo '[0-9]+([.][0-9]+)? tokens per second' | grep -Eo '^[0-9]+([.][0-9]+)?' || true)"

    if [[ "$status" != loaded && "$status" != completion_fail ]]; then
      if grep -qi 'out of memory\|failed to allocate\|cudaMalloc failed' "$log"; then
        reason='oom'
      elif grep -qi 'failed to load model' "$log"; then
        reason='load_failed'
      fi
    fi

    printf '%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n' "$quant" "$ctx" "$status" "$model_mib" "$kv_mib" "$rs_mib" "$compute_mib" "$free_mib" "$prompt_tps" "$decode_tps" "$reason" >> "$csv"
    stop_server
  done
done
REMOTE

ssh "$remote_host" "chmod +x '$bench_dir/run.sh' && '$bench_dir/run.sh'"
scp "$remote_host:$bench_dir/results.csv" ./heretic-context-results.csv
```

- [ ] **Step 2: Make script executable**

Run:

```bash
chmod +x scripts/bench-heretic-context.sh
```

## Task 2: Run Benchmark

**Files:**
- Output: `heretic-context-results.csv`

- [ ] **Step 1: Run benchmark**

Run:

```bash
./scripts/bench-heretic-context.sh
```

Expected: creates `heretic-context-results.csv`. Runtime may be long because it can download additional quants and restart the server 25 times.

- [ ] **Step 2: Inspect results**

Run:

```bash
column -s, -t heretic-context-results.csv
```

Expected: rows identify which quant/context combinations load and complete.

## Task 3: Restore Working Server

**Files:**
- Remote process only

- [ ] **Step 1: Restart known profile**

Run:

```bash
oc-qwen-heretic-reliable --lean --info
oc-qwen-heretic-reliable --lean
```

If Heretic reliable fails, restore default:

```bash
oc-qwen-reliable --lean
```

## Task 4: Record Findings

**Files:**
- Create: `docs/benchmarks/YYYY-MM-DD-heretic-context.md`

- [ ] **Step 1: Create result note**

Write a concise summary:

```markdown
# Heretic Context Benchmark

## Result

<max usable context and quant>

## Matrix

<CSV table>

## Recommendation

<whether to add 128k/196k/256k profile>
```

## Self-Review

- Spec coverage: all quant/context pairs, memory data, completion probe, server restore, and result notes are covered.
- Placeholder scan: no unresolved implementation placeholders remain.
- Type consistency: quant names and contexts match the approved matrix.
