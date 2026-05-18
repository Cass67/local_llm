# MTP Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Benchmark native llama.cpp `draft-mtp` support on `ubt26`, then promote only stable, useful MTP profiles into local_llm scripts and docs.

**Architecture:** Add a dedicated benchmark runner first, copy/run it on `ubt26`, and capture CSV plus markdown evidence. Only after benchmark winners are known, update launchers/config/docs/tests for accepted profiles while preserving non-MTP fallbacks.

**Tech Stack:** Bash, llama.cpp `llama-server`, OpenAI-compatible `/v1/chat/completions`, SSH to `ubt26`, existing `test_oc_local.sh`.

---

## File Structure

- Create `scripts/bench-mtp-remote.sh`: remote-side benchmark runner copied to `/home/cass/llama.cpp`; owns candidate matrix, server lifecycle, completion probes, log parsing, and CSV output.
- Create `docs/benchmarks/2026-05-18-mtp-benchmark.md`: final benchmark report with promoted/rejected families and selected `--spec-draft-n-max` values.
- Modify `scripts/start3.sh`, `scripts/start8.sh`, `scripts/start10.sh`, and possibly `scripts/start9.sh`: only after benchmark evidence identifies stable MTP replacements.
- Modify `scripts/oc-local`: add any accepted MTP families/profiles, model names, repos, and output/config metadata.
- Modify `configs/profiles.json`: mirror accepted profile values so central config remains accurate.
- Modify `README.md`: document MTP-capable profiles and unchanged families.
- Modify `installer.sh`: update symlink/copy lists only if new families or launchers are added.
- Modify `test_oc_local.sh`: assert accepted MTP profile metadata and launcher content.

## Constraints

- Do not promote a model that loads but fails completion.
- Do not replace `reliable` with MTP unless it is stable.
- Do not change `gemma`, `gemma-vision`, `gpt-oss`, `deepseek-r1`, or `qwen-coder` unless a suitable MTP equivalent is found and benchmarked.
- Do not commit unless the user explicitly asks for a commit.

### Task 1: Add Remote MTP Benchmark Runner

**Files:**
- Create: `scripts/bench-mtp-remote.sh`
- Test: `test_oc_local.sh`

- [ ] **Step 1: Add script existence test**

Add this assertion near the existing benchmark/start script checks in `test_oc_local.sh`:

```bash
bench_mtp_contents="$(<"$repo_root/scripts/bench-mtp-remote.sh")"
assert_contains "$bench_mtp_contents" "--spec-type draft-mtp"
assert_contains "$bench_mtp_contents" "--spec-draft-n-max"
assert_contains "$bench_mtp_contents" "qwen3.6-35b-a3b-mtp"
assert_contains "$bench_mtp_contents" "qwen3.6-27b-mtp"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bash test_oc_local.sh`

Expected: FAIL because `scripts/bench-mtp-remote.sh` does not exist yet.

- [ ] **Step 3: Create benchmark runner**

Create `scripts/bench-mtp-remote.sh` with this implementation:

```bash
#!/usr/bin/env bash
set -euo pipefail

llama_dir="${LLAMA_CPP_DIR:-/home/cass/llama.cpp}"
cd "$llama_dir"

out_dir="bench-mtp"
logs_dir="$out_dir/logs"
csv="$out_dir/results.csv"
template="${QWEN36_TEMPLATE:-$llama_dir/templates/qwen36-opencode.jinja}"
port="${LLAMA_PORT:-8080}"
host="127.0.0.1"

mkdir -p "$logs_dir"
printf 'family,repo,hf_file,ctx,batch,ubatch,spec_n,status,model_mib,kv_mib,rs_mib,compute_mib,prompt_tps,decode_tps,reason\n' > "$csv"

stop_server() {
  pkill -f './build/bin/llama-server' 2>/dev/null || true
  sleep 3
}

last_number_for() {
  local pattern="$1"
  local log="$2"
  grep -E "$pattern" "$log" | tail -1 | grep -Eo '[0-9]+([.][0-9]+)?' | tail -1 || true
}

run_trial() {
  local family="$1"
  local repo="$2"
  local hf_file="$3"
  local alias="$4"
  local ctx="$5"
  local batch="$6"
  local ubatch="$7"
  local spec_n="$8"
  local safe_name log pid status reason model_mib kv_mib rs_mib compute_mib prompt_tps decode_tps

  stop_server
  safe_name="${family}-${spec_n}-${ctx}-${hf_file}"
  safe_name="${safe_name//[^A-Za-z0-9_.-]/_}"
  log="$logs_dir/${safe_name}.log"
  : > "$log"

  ./build/bin/llama-server \
    -hf "$repo" \
    --hf-file "$hf_file" \
    --chat-template-file "$template" \
    --no-mmproj \
    --host 0.0.0.0 \
    --port "$port" \
    -ngl 999 \
    -c "$ctx" \
    --flash-attn on \
    -ub "$ubatch" \
    -b "$batch" \
    --threads "$(nproc)" \
    --prio 2 \
    --no-warmup \
    --temp 0.6 \
    --top-p 0.95 \
    --top-k 20 \
    --min-p 0.0 \
    --presence-penalty 0.0 \
    --spec-type draft-mtp \
    --spec-draft-n-max "$spec_n" \
    --alias "$alias" > "$log" 2>&1 &
  pid=$!

  status='fail'
  reason='startup_timeout'
  for _ in $(seq 1 180); do
    if curl -fsS "http://$host:$port/v1/models" >/dev/null 2>&1; then
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

  if [[ "$status" == loaded ]]; then
    if curl -fsS "http://$host:$port/v1/chat/completions" \
      -H 'Content-Type: application/json' \
      -d "{\"model\":\"$alias\",\"messages\":[{\"role\":\"user\",\"content\":\"Write exactly three short bullet points about local LLM benchmarking.\"}],\"max_tokens\":256}" >> "$log" 2>&1; then
      reason='completion_ok'
    else
      status='completion_fail'
      reason='completion_failed'
    fi
    sleep 2
  fi

  model_mib="$(last_number_for 'ROCm0 model buffer size' "$log")"
  kv_mib="$(last_number_for 'ROCm0 KV buffer size' "$log")"
  rs_mib="$(last_number_for 'ROCm0 RS buffer size' "$log")"
  compute_mib="$(last_number_for 'ROCm0 compute buffer size' "$log")"
  prompt_tps="$(grep -E 'prompt eval time' "$log" | tail -1 | grep -Eo '[0-9]+([.][0-9]+)? tokens per second' | grep -Eo '^[0-9]+([.][0-9]+)?' || true)"
  decode_tps="$(grep -E '^       eval time' "$log" | tail -1 | grep -Eo '[0-9]+([.][0-9]+)? tokens per second' | grep -Eo '^[0-9]+([.][0-9]+)?' || true)"

  if [[ "$status" == fail ]]; then
    if grep -qi 'out of memory\|failed to allocate\|cudaMalloc failed\|hipMalloc failed' "$log"; then
      reason='oom'
    elif grep -qi 'failed to load model' "$log"; then
      reason='load_failed'
    fi
  fi

  printf '%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n' "$family" "$repo" "$hf_file" "$ctx" "$batch" "$ubatch" "$spec_n" "$status" "$model_mib" "$kv_mib" "$rs_mib" "$compute_mib" "$prompt_tps" "$decode_tps" "$reason" >> "$csv"
  stop_server
}

spec_values=(2 4 8 12 16 24 32)

for spec_n in "${spec_values[@]}"; do
  run_trial qwen-mtp unsloth/Qwen3.6-35B-A3B-MTP-GGUF Qwen3.6-35B-A3B-MTP-UD-Q3_K_XL.gguf qwen3.6-35b-a3b-mtp 32768 256 256 "$spec_n"
  run_trial qwen-27b-mtp unsloth/Qwen3.6-27B-MTP-GGUF Qwen3.6-27B-MTP-IQ4_XS.gguf qwen3.6-27b-mtp 65536 64 64 "$spec_n"
  run_trial qwen-heretic-mtp llmfan46/Qwen3.6-27B-uncensored-heretic-v2-Native-MTP-Preserved-GGUF Qwen3.6-27B-uncensored-heretic-v2-Native-MTP-Preserved-IQ4_XS.gguf qwen3.6-27b-heretic-mtp 65536 64 64 "$spec_n"
done

printf 'Results: %s\n' "$csv"
```

- [ ] **Step 4: Run syntax checks**

Run: `bash -n scripts/bench-mtp-remote.sh test_oc_local.sh`

Expected: no output and exit code 0.

- [ ] **Step 5: Run repo tests**

Run: `bash test_oc_local.sh`

Expected: PASS, or fail only where the checked HF filenames differ from actual repository files found in Task 2.

### Task 2: Validate Candidate Filenames On Hugging Face

**Files:**
- Modify: `scripts/bench-mtp-remote.sh`

- [ ] **Step 1: Query candidate file lists**

Run these commands from the local repo:

```bash
python3 - <<'PY'
import json
import urllib.request

repos = [
    'unsloth/Qwen3.6-35B-A3B-MTP-GGUF',
    'unsloth/Qwen3.6-27B-MTP-GGUF',
    'llmfan46/Qwen3.6-27B-uncensored-heretic-v2-Native-MTP-Preserved-GGUF',
    'noctrex/Qwopus3.6-27B-v1-preview-MTP-GGUF',
    'mudler/Qwopus3.6-35B-A3B-v1-APEX-MTP-GGUF',
]

for repo in repos:
    with urllib.request.urlopen(f'https://huggingface.co/api/models/{repo}') as response:
        data = json.load(response)
    print(repo)
    for sibling in data.get('siblings', []):
        name = sibling.get('rfilename', '')
        if name.endswith('.gguf'):
            print(' ', name)
PY
```

Expected: printed `.gguf` filenames for each repo.

- [ ] **Step 2: Replace placeholder filenames with actual files**

Edit the `run_trial` calls in `scripts/bench-mtp-remote.sh` so each `--hf-file` exactly matches an available file. Prefer quants that fit prior RX 7900 XT results: `IQ4_XS`, `Q4_K_S`, `Q3_K_M`, or `UD-Q3_K_XL`; avoid very large Q8 unless known to fit.

- [ ] **Step 3: Add opus candidate if file list is suitable**

If `noctrex/Qwopus3.6-27B-v1-preview-MTP-GGUF` exposes a 27B quant likely to fit, add this line inside the `for spec_n` loop:

```bash
run_trial qwen-opus-mtp noctrex/Qwopus3.6-27B-v1-preview-MTP-GGUF '<actual-gguf-file>' qwen3.6-27b-opus-mtp 65536 64 64 "$spec_n"
```

If only the 35B A3B variant looks suitable, use this line instead:

```bash
run_trial qwen-opus-mtp mudler/Qwopus3.6-35B-A3B-v1-APEX-MTP-GGUF '<actual-gguf-file>' qwen3.6-35b-a3b-opus-mtp 32768 128 128 "$spec_n"
```

- [ ] **Step 4: Run syntax check**

Run: `bash -n scripts/bench-mtp-remote.sh`

Expected: no output and exit code 0.

### Task 3: Run Remote Benchmark Matrix

**Files:**
- Remote output: `/home/cass/llama.cpp/bench-mtp/results.csv`
- Remote logs: `/home/cass/llama.cpp/bench-mtp/logs/*.log`

- [ ] **Step 1: Copy runner to ubt26**

Run:

```bash
scp scripts/bench-mtp-remote.sh ubt26:/home/cass/llama.cpp/bench-mtp-remote.sh
ssh ubt26 'chmod +x /home/cass/llama.cpp/bench-mtp-remote.sh'
```

Expected: both commands exit 0.

- [ ] **Step 2: Run benchmark on ubt26**

Run:

```bash
ssh ubt26 'cd /home/cass/llama.cpp && ./bench-mtp-remote.sh'
```

Expected: finishes with `Results: bench-mtp/results.csv`. This may run for a long time and download models.

- [ ] **Step 3: Fetch CSV results**

Run:

```bash
scp ubt26:/home/cass/llama.cpp/bench-mtp/results.csv mtp-results.csv
```

Expected: local `mtp-results.csv` exists.

- [ ] **Step 4: Inspect failures**

Run:

```bash
ssh ubt26 'cd /home/cass/llama.cpp && grep -Ril "out of memory\|failed to allocate\|completion_failed\|process_exited" bench-mtp/logs || true'
```

Expected: failing logs are listed, or no output if all trials succeeded.

### Task 4: Write Benchmark Report

**Files:**
- Create: `docs/benchmarks/2026-05-18-mtp-benchmark.md`
- Read: `mtp-results.csv`

- [ ] **Step 1: Summarize result rows**

Run:

```bash
python3 - <<'PY'
import csv
from collections import defaultdict

rows = list(csv.DictReader(open('mtp-results.csv', newline='')))
best = defaultdict(lambda: None)
for row in rows:
    if row['reason'] != 'completion_ok':
        continue
    decode = float(row['decode_tps'] or 0)
    family = row['family']
    if best[family] is None or decode > float(best[family]['decode_tps'] or 0):
        best[family] = row

for family, row in sorted(best.items()):
    print(f"{family}: spec_n={row['spec_n']} decode={row['decode_tps']} prompt={row['prompt_tps']} file={row['hf_file']}")
PY
```

Expected: one best successful row per successful family.

- [ ] **Step 2: Create markdown report**

Write `docs/benchmarks/2026-05-18-mtp-benchmark.md` with:

```markdown
# MTP Benchmark

## Result

Summarize which families were promoted, which were rejected, and why.

## Environment

- Host: `ubt26`
- llama.cpp: `version: 9222 (9a532ae4b)`
- Speculative mode: `--spec-type draft-mtp`
- Sweep: `--spec-draft-n-max` values `2`, `4`, `8`, `12`, `16`, `24`, `32`

## Winners

| Family | Repo | GGUF | Context | Batch | UBatch | Best spec n | Prompt tok/s | Decode tok/s |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |

## Rejections

| Family | Reason |
| --- | --- |
| `qwen-coder` | No suitable 30B coder MTP equivalent found. |
| `gemma` | No obvious MTP GGUF equivalent found. |
| `gemma-vision` | No obvious MTP GGUF equivalent found. |
| `gpt-oss` | No obvious MTP GGUF equivalent found. |
| `deepseek-r1` | No useful 32B distill MTP equivalent found. |

## Raw Data

Reference local `mtp-results.csv` and remote `/home/cass/llama.cpp/bench-mtp/logs`.
```

- [ ] **Step 3: Fill winners table from actual results**

Replace the placeholder text and populate every promoted family from `mtp-results.csv`. If no candidates are promoted, state that no MTP profile met stability and performance requirements.

### Task 5: Promote Accepted Profiles

**Files:**
- Modify: accepted `scripts/start*.sh`
- Modify: `scripts/oc-local`
- Modify: `configs/profiles.json`
- Modify: `README.md`
- Modify: `installer.sh` only if new symlinks or launchers are required
- Modify: `test_oc_local.sh`

- [ ] **Step 1: Write tests for accepted profile metadata**

For each accepted family, add assertions in `test_oc_local.sh` similar to existing `run_info` assertions:

```bash
qwen_mtp_info_output="$(run_info qwen reliable --lean)"
assert_contains "$qwen_mtp_info_output" "hf_repo=unsloth/Qwen3.6-35B-A3B-MTP-GGUF"
assert_contains "$qwen_mtp_info_output" "spec_type=draft-mtp"
assert_contains "$qwen_mtp_info_output" "spec_draft_n_max=<best-value-from-report>"
```

Use actual accepted family names and best values from `docs/benchmarks/2026-05-18-mtp-benchmark.md`.

- [ ] **Step 2: Run tests to verify failure**

Run: `bash test_oc_local.sh`

Expected: FAIL because `oc-local` and launcher metadata do not expose accepted MTP values yet.

- [ ] **Step 3: Update accepted start scripts**

For each accepted launcher, update repo/file variables and add these flags to the final `llama-server` command with the actual best value:

```bash
  --spec-type draft-mtp \
  --spec-draft-n-max "<best-value-from-report>" \
```

Do not add these flags to rejected families or unstable profiles.

- [ ] **Step 4: Update `scripts/oc-local` metadata**

Add variables for accepted profiles:

```bash
spec_type=none
spec_draft_n_max=0
```

Set them inside accepted family/profile cases:

```bash
spec_type=draft-mtp
spec_draft_n_max=<best-value-from-report>
```

Include them in `--info` output so tests can assert the active configuration.

- [ ] **Step 5: Update central profile config**

For each accepted `configs/profiles.json` entry, add:

```json
"spec_type": "draft-mtp",
"spec_draft_n_max": <best-value-from-report>
```

For unchanged entries, either omit the keys or use existing style if the repo already has explicit defaults.

- [ ] **Step 6: Update docs**

In `README.md`, add a short MTP note near the family/profile tables:

```markdown
MTP is enabled only on benchmark-proven profiles. Use `--info` to confirm `spec_type=draft-mtp` and the selected `spec_draft_n_max` before starting a session.
```

Add one line per promoted family with its selected MTP setting and leave rejected families documented as unchanged.

- [ ] **Step 7: Run validation**

Run:

```bash
bash -n scripts/oc-local scripts/model-manager.sh scripts/update-manager.sh scripts/model-discovery.sh scripts/hardware-analyzer.sh installer.sh scripts/start2.sh scripts/start3.sh scripts/start4.sh scripts/start5.sh scripts/start6.sh scripts/start7.sh scripts/start8.sh scripts/start9.sh scripts/start10.sh scripts/bench-mtp-remote.sh test_oc_local.sh
bash test_oc_local.sh
```

Expected: both commands pass.

### Task 6: Remote Verify Promoted Launchers

**Files:**
- Remote: `/home/cass/llama.cpp/start*.sh`

- [ ] **Step 1: Copy changed launchers**

Run one `scp` command containing only launchers changed in Task 5. Example:

```bash
scp scripts/start3.sh scripts/start8.sh scripts/start10.sh ubt26:/home/cass/llama.cpp/
```

Expected: command exits 0.

- [ ] **Step 2: Make launchers executable**

Run:

```bash
ssh ubt26 'chmod +x /home/cass/llama.cpp/start3.sh /home/cass/llama.cpp/start8.sh /home/cass/llama.cpp/start10.sh'
```

Expected: command exits 0. Include only changed launchers.

- [ ] **Step 3: Start one promoted profile**

Run one accepted launcher manually. Example:

```bash
ssh ubt26 'cd /home/cass/llama.cpp && ./start3.sh speed > /tmp/start3-mtp-verify.log 2>&1 &'
```

Expected: command starts server in background.

- [ ] **Step 4: Confirm API is ready**

Run:

```bash
ssh ubt26 'for i in $(seq 1 120); do curl -fsS http://127.0.0.1:8080/v1/models && exit 0; sleep 2; done; exit 1'
```

Expected: returns model list JSON.

- [ ] **Step 5: Stop server**

Run:

```bash
ssh ubt26 'pkill -f "./build/bin/llama-server" || true'
```

Expected: exits 0.

## Self-Review

- Spec coverage: model capability discovery, max forward predicted token benchmarking, and script updates are covered by Tasks 1-6.
- Placeholder scan: implementation placeholders are limited to `<best-value-from-report>` and `<actual-gguf-file>`, which are intentionally produced by earlier benchmark/discovery tasks before promotion.
- Type consistency: MTP metadata uses `spec_type` and `spec_draft_n_max` consistently across tests, `oc-local`, JSON config, and docs.
