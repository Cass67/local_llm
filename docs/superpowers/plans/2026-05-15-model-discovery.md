# Model Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `model-discovery` perform live Hugging Face GGUF discovery by default, detect the actual model host GPU, and keep installed profiles as a separate inventory section.

**Architecture:** Keep the implementation in `scripts/model-discovery.sh` with small shell functions for hardware probing, Hugging Face querying, JSON parsing, ranking, and rendering. Keep `scripts/hardware-analyzer.sh` focused on hardware only, sharing no source file to preserve the repo's single-script preference.

**Tech Stack:** Bash, `curl`, Python stdlib `json` for robust JSON parsing, SSH, ROCm tools, llama.cpp `llama-server --list-devices`, existing shell tests in `test_oc_local.sh`.

---

## File Structure

- Modify `scripts/model-discovery.sh`: add default live Hugging Face search, `--query`, `--limit`, `--installed-only`, GPU/VRAM/ROCm detection, fixture injection for tests, and clear output sections.
- Modify `scripts/hardware-analyzer.sh`: improve GPU detection using `rocminfo`, `rocm-smi`, and remote `llama-server --list-devices` fallback.
- Modify `test_oc_local.sh`: add regression coverage for new CLI options, installed-only mode, fixture-backed Hugging Face search, and GPU field wording.
- Modify `README.md`: document live search defaults, options, GPU detection, and installed profile inventory.
- Use existing `docs/plans/2026-05-15-model-discovery-design.md` as the approved design reference.

## Task 1: Add Test Fixtures And CLI Expectations

**Files:**
- Modify: `test_oc_local.sh`
- Create: `testdata/huggingface-model-search.json`

- [ ] **Step 1: Add Hugging Face fixture**

Create `testdata/huggingface-model-search.json`:

```json
[
  {
    "id": "unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF",
    "downloads": 1200,
    "likes": 45,
    "tags": ["gguf", "llama.cpp", "text-generation", "code"]
  },
  {
    "id": "unsloth/gpt-oss-20b-GGUF",
    "downloads": 900,
    "likes": 40,
    "tags": ["gguf", "llama.cpp", "reasoning"]
  },
  {
    "id": "example/not-a-gguf-model",
    "downloads": 5000,
    "likes": 100,
    "tags": ["safetensors"]
  }
]
```

- [ ] **Step 2: Add assertions for new discovery output**

Replace the current model-discovery assertions around lines 46-51 in `test_oc_local.sh` with:

```bash
model_discovery_output="$(OC_LOCAL_REMOTE_HOST=__none__ OC_LOCAL_HF_FIXTURE="$repo_root/testdata/huggingface-model-search.json" "$repo_root/scripts/model-discovery.sh")"
assert_contains "$model_discovery_output" "Hardware source: local"
assert_contains "$model_discovery_output" "GPU:"
assert_contains "$model_discovery_output" "VRAM:"
assert_contains "$model_discovery_output" "ROCm target:"
assert_contains "$model_discovery_output" "Hugging Face GGUF Candidates"
assert_contains "$model_discovery_output" "unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF"
assert_contains "$model_discovery_output" "Already Tuned Profiles"
assert_contains "$model_discovery_output" "oc-qwen-reliable --lean"
assert_not_contains "$model_discovery_output" "not a Hugging Face search"
assert_not_contains "$model_discovery_output" "Recommended models:"

installed_only_output="$(OC_LOCAL_REMOTE_HOST=__none__ "$repo_root/scripts/model-discovery.sh" --installed-only)"
assert_contains "$installed_only_output" "Already Tuned Profiles"
assert_not_contains "$installed_only_output" "Hugging Face GGUF Candidates"

query_help_output="$("$repo_root/scripts/model-discovery.sh" --help)"
assert_contains "$query_help_output" "--query <text>"
assert_contains "$query_help_output" "--limit <n>"
assert_contains "$query_help_output" "--installed-only"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `./test_oc_local.sh`

Expected: FAIL because `model-discovery.sh` does not yet render `Hugging Face GGUF Candidates`, `GPU:`, `VRAM:`, or the new options.

- [ ] **Step 4: Commit when requested**

Do not commit unless the user explicitly asks. If requested later, commit this task with:

```bash
git add test_oc_local.sh testdata/huggingface-model-search.json
git commit -m "test: cover live model discovery output"
```

## Task 2: Implement Hardware Detection Functions

**Files:**
- Modify: `scripts/model-discovery.sh`
- Modify: `scripts/hardware-analyzer.sh`

- [ ] **Step 1: Add hardware fields to `model-discovery.sh`**

Add these variables near the existing `cpu_cores`, `ram_gib`, and `source` initialization:

```bash
gpu_name='unknown'
vram='unknown'
rocm_target='unknown'
```

- [ ] **Step 2: Add remote hardware helper functions to `model-discovery.sh`**

Add after `remote_value()`:

```bash
remote_gpu_name() {
  remote_value "rocminfo 2>/dev/null | awk -F: '/Marketing Name/ {gsub(/^[ \\t]+/, \"\", \\$2); print \\$2; exit}'"
}

remote_rocm_target() {
  remote_value "rocminfo 2>/dev/null | awk -F: '/Name/ && \\$2 ~ /gfx/ {gsub(/^[ \\t]+/, \"\", \\$2); print \\$2; exit}'"
}

remote_vram() {
  local value
  value="$(remote_value "rocm-smi --showmeminfo vram 2>/dev/null | awk '/Total Memory/ {print \\$NF; exit}'")"
  if [[ -n "$value" ]]; then
    printf '%s\n' "$value"
    return
  fi
  remote_value "cd '${OC_LOCAL_REMOTE_DIR:-/home/cass/llama.cpp}' && ./build/bin/llama-server --list-devices 2>/dev/null | awk '/ROCm0/ {print; exit}'"
}
```

- [ ] **Step 3: Add local hardware helper functions to `model-discovery.sh`**

Add after `local_ram_gib()`:

```bash
local_gpu_name() {
  if command -v rocminfo >/dev/null 2>&1; then
    rocminfo 2>/dev/null | awk -F: '/Marketing Name/ {gsub(/^[ \\t]+/, "", $2); print $2; exit}'
  else
    printf 'unknown\n'
  fi
}

local_rocm_target() {
  if command -v rocminfo >/dev/null 2>&1; then
    rocminfo 2>/dev/null | awk -F: '/Name/ && $2 ~ /gfx/ {gsub(/^[ \\t]+/, "", $2); print $2; exit}'
  else
    printf 'unknown\n'
  fi
}

local_vram() {
  if command -v rocm-smi >/dev/null 2>&1; then
    rocm-smi --showmeminfo vram 2>/dev/null | awk '/Total Memory/ {print $NF; exit}'
  else
    printf 'unknown\n'
  fi
}
```

- [ ] **Step 4: Populate fields with fallback normalization**

In `model-discovery.sh`, after CPU/RAM detection, set GPU fields for remote and local paths:

```bash
if [[ "$source" == remote:* ]]; then
  gpu_name="$(remote_gpu_name)"
  vram="$(remote_vram)"
  rocm_target="$(remote_rocm_target)"
else
  gpu_name="$(local_gpu_name)"
  vram="$(local_vram)"
  rocm_target="$(local_rocm_target)"
fi

[[ -n "$gpu_name" ]] || gpu_name='unknown'
[[ -n "$vram" ]] || vram='unknown'
[[ -n "$rocm_target" ]] || rocm_target='unknown'
```

- [ ] **Step 5: Mirror the detection improvements in `hardware-analyzer.sh`**

Use the same source order: `rocminfo`, `rocm-smi`, then remote `llama-server --list-devices` fallback for VRAM/device. Keep output labels stable:

```bash
echo "GPU: $gpu_name"
echo "VRAM: $vram"
echo "ROCm target: $rocm_target"
```

- [ ] **Step 6: Run tests and syntax checks**

Run: `./test_oc_local.sh`

Expected: still FAIL on Hugging Face candidate output until Task 3.

Run: `bash -n scripts/model-discovery.sh scripts/hardware-analyzer.sh test_oc_local.sh`

Expected: no output, exit 0.

## Task 3: Implement Live Hugging Face Search

**Files:**
- Modify: `scripts/model-discovery.sh`

- [ ] **Step 1: Add CLI state and options**

Near existing option state, add:

```bash
query='gguf code reasoning chat'
limit=8
installed_only=false
```

Add parser cases:

```bash
    --query)
      if [[ $# -lt 2 ]]; then
        printf '%s requires text\n' "$1" >&2
        exit 2
      fi
      query="$2"
      shift 2
      ;;
    --limit)
      if [[ $# -lt 2 || ! "$2" =~ ^[0-9]+$ ]]; then
        printf '%s requires a numeric limit\n' "$1" >&2
        exit 2
      fi
      limit="$2"
      shift 2
      ;;
    --installed-only)
      installed_only=true
      shift
      ;;
```

- [ ] **Step 2: Update usage text**

Change usage to include:

```text
Usage: model-discovery.sh [--query <text>] [--limit <n>] [--installed-only] [--detailed] [--local] [--host <host>]

Queries Hugging Face live for GGUF model candidates and shows already tuned local profiles.

Options:
  --query <text>     Hugging Face search text (default: gguf code reasoning chat)
  --limit <n>        maximum Hugging Face candidates to show (default: 8)
  --installed-only   skip Hugging Face search and show tuned profiles only
```

- [ ] **Step 3: Add Hugging Face fetch function**

Add:

```bash
hf_search_json() {
  if [[ -n "${OC_LOCAL_HF_FIXTURE:-}" ]]; then
    cat "$OC_LOCAL_HF_FIXTURE"
    return
  fi

  local encoded_query
  encoded_query="$(python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1]))' "$query")"
  curl -fsSL "https://huggingface.co/api/models?search=${encoded_query}&limit=${limit}&sort=downloads&direction=-1" 2>/dev/null
}
```

- [ ] **Step 4: Add candidate rendering function**

Add:

```bash
render_hf_candidates() {
  local json_input="$1"
  python3 - "$limit" <<'PY' <<<"$json_input"
import json
import sys

limit = int(sys.argv[1])
models = json.load(sys.stdin)
count = 0

for model in models:
    repo = model.get("id", "")
    tags = [str(tag).lower() for tag in model.get("tags", [])]
    repo_lower = repo.lower()
    if "gguf" not in repo_lower and "gguf" not in tags:
        continue

    if "coder" in repo_lower or "code" in tags:
        purpose = "code"
    elif "reason" in repo_lower or "reasoning" in tags or "r1" in repo_lower:
        purpose = "reasoning"
    elif "vision" in repo_lower or "vl" in repo_lower:
        purpose = "vision"
    else:
        purpose = "chat"

    if any(size in repo_lower for size in ("7b", "8b", "9b", "14b", "20b", "22b", "27b", "30b", "32b", "35b")):
        fit = "maybe"
        reason = "size may fit with tuned quant/context"
    elif any(size in repo_lower for size in ("70b", "72b", "120b")):
        fit = "unlikely"
        reason = "too large for full RX 7900 XT offload"
    else:
        fit = "unknown"
        reason = "model size not clear from repo id"

    print(f"- {repo} | purpose={purpose} | fit={fit} | {reason}")
    count += 1
    if count >= limit:
        break

if count == 0:
    print("- no GGUF candidates found for query")
PY
}
```

- [ ] **Step 5: Render candidate section with network failure handling**

Before the installed profile section, add:

```bash
if [[ "$installed_only" == false ]]; then
  printf '\nHugging Face GGUF Candidates:\n'
  printf '%s\n' '-----------------------------'
  if hf_json="$(hf_search_json)"; then
    render_hf_candidates "$hf_json"
  else
    printf '%s\n' '- Hugging Face search unavailable; check network or try again later.'
  fi
fi
```

- [ ] **Step 6: Run fixture-backed test**

Run: `./test_oc_local.sh`

Expected: PASS for model discovery assertions and existing wrapper assertions.

## Task 4: Render Final Sections And Docs

**Files:**
- Modify: `scripts/model-discovery.sh`
- Modify: `README.md`

- [ ] **Step 1: Update hardware output labels**

Change the top output in `model-discovery.sh` to:

```bash
cat <<EOF
Model Discovery Results:
-----------------------
Hardware source: ${source}
- CPU Cores: ${cpu_cores}
- RAM: ${ram_gib} GB
- GPU: ${gpu_name}
- VRAM: ${vram}
- ROCm target: ${rocm_target}
EOF
```

- [ ] **Step 2: Rename installed profile section**

Change `Installed local_llm fleet profiles` to:

```text
Already Tuned Profiles:
```

Use command-oriented entries:

```text
1. qwen        oc-qwen-reliable --lean
2. qwen-coder  oc-qwen-coder-reliable --lean
3. gpt-oss     oc-gpt-oss-speed --lean
4. gemma       oc-gemma-reliable --lean
5. gemma-vision oc-gemma-vision-reliable --lean
6. qwen-27b    oc-qwen-27b-reliable --lean; long: oc-qwen-27b-long --lean
7. deepseek-r1 oc-deepseek-r1-reliable --lean
```

- [ ] **Step 3: Update README helper section**

Change the Model Discovery paragraph to:

```markdown
`model-discovery` queries Hugging Face live by default for GGUF candidates, detects the target model-server hardware, and prints the already tuned local profiles separately. Use `--installed-only` when you only want the current fleet.
```

Update examples:

```bash
model-discovery
model-discovery --query "qwen coder gguf" --limit 10
model-discovery --installed-only
model-discovery --local
model-discovery --detailed
```

- [ ] **Step 4: Run docs/test verification**

Run: `./test_oc_local.sh`

Expected: PASS.

Run: `bash -n scripts/model-discovery.sh scripts/hardware-analyzer.sh test_oc_local.sh && shellcheck scripts/model-discovery.sh scripts/hardware-analyzer.sh test_oc_local.sh`

Expected: no output, exit 0.

## Task 5: Install And Verify Live Behavior

**Files:**
- Installed outputs only: `/Users/cass/.local/bin/model-discovery`, `/Users/cass/.local/bin/hardware-analyzer`

- [ ] **Step 1: Install updated helpers**

Run:

```bash
install -m 0755 scripts/model-discovery.sh /Users/cass/.local/bin/model-discovery
install -m 0755 scripts/hardware-analyzer.sh /Users/cass/.local/bin/hardware-analyzer
```

Expected: no output, exit 0.

- [ ] **Step 2: Verify installed model discovery live path**

Run: `model-discovery --limit 5`

Expected: output includes `Hardware source: remote:ubt26`, `GPU:`, `VRAM:`, `ROCm target:`, `Hugging Face GGUF Candidates`, and `Already Tuned Profiles`.

- [ ] **Step 3: Verify installed-only path**

Run: `model-discovery --installed-only`

Expected: output includes `Already Tuned Profiles` and does not include `Hugging Face GGUF Candidates`.

- [ ] **Step 4: Verify remote hardware analyzer**

Run: `hardware-analyzer --remote ubt26`

Expected: output includes CPU, RAM, GPU, VRAM, ROCm target, architecture, and OS. Unknown GPU subfields are acceptable only if all fallback commands fail.

## Self-Review

- Spec coverage: live Hugging Face default is covered by Task 3; GPU detection by Task 2; installed fleet as separate section by Task 4; docs by Task 4; installed verification by Task 5.
- Placeholder scan: no `TBD`, `TODO`, or unspecified test steps remain.
- Type consistency: option names are consistent across tests, usage, docs, and implementation: `--query`, `--limit`, `--installed-only`, `--local`, `--host`.
