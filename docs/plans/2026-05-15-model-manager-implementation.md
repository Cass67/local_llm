# Model Manager Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a target-aware model lifecycle workflow that can discover, select, benchmark, and accept GGUF models for local or remote llama.cpp targets.

**Architecture:** Keep `scripts/oc-local` as the accepted-model runtime wrapper and add `scripts/model-manager.sh` as the orchestration entrypoint. Store transient discovery/selection/benchmark artifacts under ignored `runs/` directories, while accepted models continue to update source files, tests, and docs.

**Tech Stack:** Bash scripts, `llama.cpp`/`llama-server`, SSH, curl, existing shell test harness in `test_oc_local.sh`.

---

## Preconditions

- Read `/Users/cass/.config/opencode/BASH_STANDARDS.md` before editing shell scripts.
- Do not commit unless the user explicitly asks for commits.
- Preserve existing dirty worktree changes; do not revert unrelated files.
- Use `apply_patch` for manual edits.

## Verification Commands

Run these after each task that edits shell scripts:

```bash
bash -n scripts/oc-local scripts/model-discovery.sh scripts/update-manager.sh installer.sh test_oc_local.sh
```

If `scripts/model-manager.sh` exists, include it:

```bash
bash -n scripts/model-manager.sh
```

If `shellcheck` is available:

```bash
shellcheck scripts/oc-local scripts/model-manager.sh scripts/model-discovery.sh scripts/update-manager.sh installer.sh test_oc_local.sh
```

Always run:

```bash
./test_oc_local.sh
```

---

### Task 1: Ignore Runtime Artifacts

**Files:**
- Modify: `.gitignore`
- Test: `test_oc_local.sh`

**Step 1: Write the failing test**

Add assertions near the existing README/helper assertions in `test_oc_local.sh`:

```bash
gitignore_contents="$(<"$repo_root/.gitignore")"
assert_contains "$gitignore_contents" "runs/"
```

**Step 2: Run test to verify it fails**

Run:

```bash
./test_oc_local.sh
```

Expected: FAIL because `.gitignore` does not yet contain `runs/`.

**Step 3: Implement the minimal change**

Add this line to `.gitignore`:

```gitignore
runs/
```

**Step 4: Verify**

Run:

```bash
./test_oc_local.sh
```

Expected: PASS.

---

### Task 2: Add Target Parsing To oc-local Info/Dry-Run

**Files:**
- Modify: `scripts/oc-local`
- Test: `test_oc_local.sh`

**Step 1: Write failing tests**

Add tests after existing `run_info`/`run_dry` assertions for known families:

```bash
local_target_info="$(run_info --target local qwen reliable)"
assert_contains "$local_target_info" "target=local"
assert_contains "$local_target_info" "target_kind=local"
assert_contains "$local_target_info" "llama_dir=$HOME/llama.cpp"
assert_contains "$local_target_info" "base_url=http://127.0.0.1:8080/v1"

remote_target_info="$(OC_LOCAL_REMOTE_DIR=/srv/llama run_info --target remote:test-host qwen reliable)"
assert_contains "$remote_target_info" "target=remote:test-host"
assert_contains "$remote_target_info" "target_kind=remote"
assert_contains "$remote_target_info" "remote_host=test-host"
assert_contains "$remote_target_info" "llama_dir=/srv/llama"
assert_contains "$remote_target_info" "base_url=http://cass.lan:8080/v1"
```

Add a help assertion:

```bash
assert_contains "$help_output" "--target local|remote:<host>"
```

**Step 2: Run test to verify it fails**

Run:

```bash
./test_oc_local.sh
```

Expected: FAIL because `--target` is unknown.

**Step 3: Implement target option parsing**

In `scripts/oc-local`, add state near the existing option variables:

```bash
target="${OC_LOCAL_TARGET:-remote:${OC_LOCAL_REMOTE_HOST:-ubt26}}"
```

Accept `--target <target>` in both option parsing loops:

```bash
--target)
  if [[ $# -lt 2 ]]; then
    printf '%s requires local or remote:<host>\n' "$1" >&2
    usage
    exit 2
  fi
  target="$2"
  shift 2
  ;;
```

Add help text:

```text
  --target local|remote:<host>
             run llama.cpp locally or on a remote SSH host
```

After family/profile resolution, resolve the target:

```bash
target_kind=''
target_host=''
case "$target" in
  local)
    target_kind=local
    ;;
  remote:*)
    target_kind=remote
    target_host="${target#remote:}"
    if [[ -z "$target_host" ]]; then
      printf 'remote target requires a host: %s\n' "$target" >&2
      exit 2
    fi
    ;;
  *)
    printf 'unknown target: %s\n' "$target" >&2
    printf 'expected local or remote:<host>\n' >&2
    exit 2
    ;;
esac

remote_host="$target_host"
local_dir="${OC_LOCAL_LLAMA_DIR:-$HOME/llama.cpp}"
remote_dir="${OC_LOCAL_REMOTE_DIR:-/home/cass/llama.cpp}"
if [[ "$target_kind" == local ]]; then
  llama_dir="$local_dir"
  base_url="${OC_LOCAL_BASE_URL:-http://127.0.0.1:8080/v1}"
else
  llama_dir="$remote_dir"
  base_url="${OC_LOCAL_BASE_URL:-http://cass.lan:8080/v1}"
fi
```

Remove or replace the old unconditional assignments for `remote_host`, `remote_dir`, and `base_url` so they do not override target resolution.

In `--info` output, add:

```bash
printf 'target=%s\n' "$target"
printf 'target_kind=%s\n' "$target_kind"
printf 'llama_dir=%s\n' "$llama_dir"
```

Keep `remote_host` and `remote_dir` output for compatibility, but for local targets print them empty or existing defaults consistently.

In `--dry-run` output, add:

```bash
printf 'target=%s\n' "$target"
printf 'target_kind=%s\n' "$target_kind"
printf 'llama_dir=%s\n' "$llama_dir"
```

**Step 4: Verify**

Run:

```bash
bash -n scripts/oc-local test_oc_local.sh
./test_oc_local.sh
```

Expected: PASS.

---

### Task 3: Add Local Runtime Branch To oc-local

**Files:**
- Modify: `scripts/oc-local`
- Test: `test_oc_local.sh`

**Step 1: Write failing tests with stub commands**

In `test_oc_local.sh`, use a temp directory with stub `ssh`, `curl`, `opencode`, and a fake `start3.sh` to verify local execution does not use SSH.

Add near other temp command tests:

```bash
local_run_tmp="$(mktemp -d)"
trap 'rm -rf "$probe_tmp" "$local_run_tmp"' EXIT
mkdir -p "$local_run_tmp/bin" "$local_run_tmp/llama"

cat >"$local_run_tmp/bin/ssh" <<'EOF'
#!/usr/bin/env bash
printf 'ssh should not be used for local target\n' >&2
exit 1
EOF

cat >"$local_run_tmp/bin/curl" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF

cat >"$local_run_tmp/bin/opencode" <<'EOF'
#!/usr/bin/env bash
printf 'opencode args: %s\n' "$*"
EOF

cat >"$local_run_tmp/llama/start3.sh" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF

chmod +x "$local_run_tmp/bin/ssh" "$local_run_tmp/bin/curl" "$local_run_tmp/bin/opencode" "$local_run_tmp/llama/start3.sh"

local_run_output="$(PATH="$local_run_tmp/bin:$PATH" OC_LOCAL_LLAMA_DIR="$local_run_tmp/llama" OC_LOCAL_WAIT_SECONDS=1 "$script" --target local qwen reliable --lean 2>&1)"
assert_contains "$local_run_output" "Restarting local llama.cpp qwen profile reliable"
assert_contains "$local_run_output" "opencode args: -m localllm/qwen3.6-35b-a3b"
assert_not_contains "$local_run_output" "ssh should not be used"
```

**Step 2: Run test to verify it fails**

Run:

```bash
./test_oc_local.sh
```

Expected: FAIL because runtime still assumes SSH.

**Step 3: Implement local branch**

Replace the single remote start block with a target branch.

For remote, keep existing behavior.

For local:

```bash
if [[ "$target_kind" == local ]]; then
  printf 'Restarting local llama.cpp %s profile %s (%s context) in %s...\n' "$family" "$profile" "$context" "$llama_dir" >&2
  (
    cd "$llama_dir"
    pkill -f '[l]lama-server' || true
    log="llama-${remote_profile}.log"
    rm -f "$log"
    nohup "$remote_script" "$remote_profile" >"$log" 2>&1 < /dev/null &
  )

  printf 'Waiting for local llama.cpp API...\n' >&2
  deadline=$((SECONDS + wait_seconds))
  until curl -fsS 'http://127.0.0.1:8080/v1/models' >/dev/null 2>&1; do
    if (( SECONDS >= deadline )); then
      printf 'timed out waiting for local llama.cpp API after %s seconds\n' "$wait_seconds" >&2
      printf 'check local log: %s\n' "$llama_dir/llama-${remote_profile}.log" >&2
      exit 1
    fi
    sleep 2
  done
else
  # existing SSH start/wait block
fi
```

Keep the final `base_url/models` wait after this branch so both target types verify the client-visible API.

**Step 4: Verify**

Run:

```bash
bash -n scripts/oc-local test_oc_local.sh
./test_oc_local.sh
```

Expected: PASS.

---

### Task 4: Create Minimal model-manager Script

**Files:**
- Create: `scripts/model-manager.sh`
- Modify: `installer.sh`
- Modify: `README.md`
- Test: `test_oc_local.sh`

**Step 1: Write failing tests**

Add assertions:

```bash
model_manager_help_output="$($repo_root/scripts/model-manager.sh --help 2>&1)"
assert_contains "$model_manager_help_output" "Usage: model-manager"
assert_contains "$model_manager_help_output" "discover"
assert_contains "$model_manager_help_output" "select"
assert_contains "$model_manager_help_output" "benchmark"
assert_contains "$model_manager_help_output" "accept"
assert_contains "$model_manager_help_output" "status"

installer_contents="$(<"$repo_root/installer.sh")"
assert_contains "$installer_contents" "scripts/model-manager.sh"

readme_contents="$(<"$repo_root/README.md")"
assert_contains "$readme_contents" "model-manager discover"
```

**Step 2: Run test to verify it fails**

Run:

```bash
./test_oc_local.sh
```

Expected: FAIL because the script and docs/install references do not exist.

**Step 3: Implement minimal script**

Create `scripts/model-manager.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
runs_dir="${LOCAL_LLM_RUNS_DIR:-$repo_root/runs}"

usage() {
  cat <<'EOF'
Usage: model-manager <command> [options]

Commands:
  discover   find GGUF candidates for a target
  select     select one or more candidates
  benchmark  benchmark selected candidates
  accept     accept a successful benchmark into the suite
  status     show candidates, selections, and benchmarks

Common options:
  --target local|remote:<host>
  -h, --help
EOF
}

command_name="${1:-}"
case "$command_name" in
  -h|--help|'')
    usage
    ;;
  discover|select|benchmark|accept|status)
    printf 'model-manager %s is not implemented yet\n' "$command_name" >&2
    exit 1
    ;;
  *)
    printf 'unknown command: %s\n' "$command_name" >&2
    usage >&2
    exit 2
    ;;
esac
```

Update `installer.sh`:

```bash
install -m 0755 scripts/model-manager.sh ~/.local/bin/model-manager
```

Update README helper section with minimal examples:

```bash
model-manager discover --target remote:ubt26 --query "qwen coder gguf"
model-manager status
```

**Step 4: Verify**

Run:

```bash
bash -n scripts/model-manager.sh installer.sh test_oc_local.sh
./test_oc_local.sh
```

Expected: PASS.

---

### Task 5: Implement model-manager status

**Files:**
- Modify: `scripts/model-manager.sh`
- Test: `test_oc_local.sh`

**Step 1: Write failing tests**

Add tests using isolated `LOCAL_LLM_RUNS_DIR`:

```bash
manager_tmp="$(mktemp -d)"
trap 'rm -rf "$probe_tmp" "$local_run_tmp" "$manager_tmp"' EXIT
mkdir -p "$manager_tmp/candidates" "$manager_tmp/selections" "$manager_tmp/benchmarks"
printf '{}\n' >"$manager_tmp/candidates/sample.json"

status_output="$(LOCAL_LLM_RUNS_DIR="$manager_tmp" "$repo_root/scripts/model-manager.sh" status)"
assert_contains "$status_output" "Model Manager Status"
assert_contains "$status_output" "Candidates: 1"
assert_contains "$status_output" "Selections: 0"
assert_contains "$status_output" "Benchmarks: 0"
```

**Step 2: Run test to verify it fails**

Run:

```bash
./test_oc_local.sh
```

Expected: FAIL because `status` exits as not implemented.

**Step 3: Implement status**

Add helpers:

```bash
ensure_runs_dirs() {
  mkdir -p "$runs_dir/candidates" "$runs_dir/selections" "$runs_dir/benchmarks"
}

count_json_files() {
  local dir="$1"
  local count=0
  if [[ -d "$dir" ]]; then
    count="$(find "$dir" -maxdepth 1 -type f -name '*.json' | wc -l | tr -d ' ')"
  fi
  printf '%s\n' "$count"
}

cmd_status() {
  ensure_runs_dirs
  printf 'Model Manager Status\n'
  printf '====================\n'
  printf 'Runs dir: %s\n' "$runs_dir"
  printf 'Candidates: %s\n' "$(count_json_files "$runs_dir/candidates")"
  printf 'Selections: %s\n' "$(count_json_files "$runs_dir/selections")"
  printf 'Benchmarks: %s\n' "$(count_json_files "$runs_dir/benchmarks")"
}
```

Dispatch `status` to `cmd_status`.

**Step 4: Verify**

Run:

```bash
bash -n scripts/model-manager.sh test_oc_local.sh
./test_oc_local.sh
```

Expected: PASS.

---

### Task 6: Implement model-manager discover Wrapper

**Files:**
- Modify: `scripts/model-manager.sh`
- Test: `test_oc_local.sh`

**Step 1: Write failing tests**

Use the existing Hugging Face fixture:

```bash
discover_tmp="$(mktemp -d)"
trap 'rm -rf "$probe_tmp" "$local_run_tmp" "$manager_tmp" "$discover_tmp"' EXIT

discover_output="$(LOCAL_LLM_RUNS_DIR="$discover_tmp" OC_LOCAL_HF_FIXTURE="$repo_root/testdata/huggingface-model-search.json" "$repo_root/scripts/model-manager.sh" discover --target local --query "qwen coder gguf" --limit 3)"
assert_contains "$discover_output" "Model Discovery Results:"
assert_contains "$discover_output" "Hardware source: local"
assert_contains "$discover_output" "unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF"
```

**Step 2: Run test to verify it fails**

Run:

```bash
./test_oc_local.sh
```

Expected: FAIL because `discover` is not implemented.

**Step 3: Implement discover**

Parse options for `discover`:

```text
--target local|remote:<host>
--query <text>
--limit <n>
--json
```

For human-readable output, call existing `scripts/model-discovery.sh`:

```bash
case "$target" in
  local)
    "$repo_root/scripts/model-discovery.sh" --local --query "$query" --limit "$limit"
    ;;
  remote:*)
    "$repo_root/scripts/model-discovery.sh" --host "${target#remote:}" --query "$query" --limit "$limit"
    ;;
esac
```

For `--json`, first emit a simple metadata envelope even if candidates remain text-only in the first pass:

```json
{"target":"local","query":"qwen coder gguf","limit":3}
```

Do not overbuild JSON parsing in this task.

**Step 4: Verify**

Run:

```bash
bash -n scripts/model-manager.sh test_oc_local.sh
./test_oc_local.sh
```

Expected: PASS.

---

### Task 7: Implement Scriptable select

**Files:**
- Modify: `scripts/model-manager.sh`
- Test: `test_oc_local.sh`

**Step 1: Write failing tests**

Add:

```bash
select_tmp="$(mktemp -d)"
trap 'rm -rf "$probe_tmp" "$local_run_tmp" "$manager_tmp" "$discover_tmp" "$select_tmp"' EXIT

select_output="$(LOCAL_LLM_RUNS_DIR="$select_tmp" "$repo_root/scripts/model-manager.sh" select --repo Example/Foo-GGUF --family foo --alias foo-30b --purpose code --target local)"
assert_contains "$select_output" "Selected Example/Foo-GGUF"
selection_file_count="$(find "$select_tmp/selections" -maxdepth 1 -type f -name '*.json' | wc -l | tr -d ' ')"
if [[ "$selection_file_count" != 1 ]]; then
  printf 'expected one selection file, got %s\n' "$selection_file_count" >&2
  exit 1
fi
selection_contents="$(find "$select_tmp/selections" -maxdepth 1 -type f -name '*.json' -exec cat {} \;)"
assert_contains "$selection_contents" '"repo":"Example/Foo-GGUF"'
assert_contains "$selection_contents" '"family":"foo"'
assert_contains "$selection_contents" '"alias":"foo-30b"'
assert_contains "$selection_contents" '"target":"local"'
```

**Step 2: Run test to verify it fails**

Run:

```bash
./test_oc_local.sh
```

Expected: FAIL because `select` is not implemented.

**Step 3: Implement select**

Implement scriptable mode requiring `--repo`, `--family`, and `--alias`.

Write JSON safely enough for expected repo/family/alias values:

```bash
timestamp="$(date +%Y%m%d-%H%M%S)"
safe_family="${family//[^A-Za-z0-9_.-]/-}"
output_file="$runs_dir/selections/${timestamp}-${safe_family}.json"
```

Use `python3` for JSON escaping if available; otherwise fail clearly:

```bash
command -v python3 >/dev/null 2>&1 || { printf 'python3 is required for selection JSON\n' >&2; exit 1; }
```

Generate JSON with Python using args, not shell interpolation.

**Step 4: Verify**

Run:

```bash
bash -n scripts/model-manager.sh test_oc_local.sh
./test_oc_local.sh
```

Expected: PASS.

---

### Task 8: Add Benchmark Skeleton

**Files:**
- Modify: `scripts/model-manager.sh`
- Test: `test_oc_local.sh`

**Step 1: Write failing tests**

Add a dry-run benchmark test:

```bash
benchmark_tmp="$(mktemp -d)"
trap 'rm -rf "$probe_tmp" "$local_run_tmp" "$manager_tmp" "$discover_tmp" "$select_tmp" "$benchmark_tmp"' EXIT

benchmark_output="$(LOCAL_LLM_RUNS_DIR="$benchmark_tmp" "$repo_root/scripts/model-manager.sh" benchmark --repo Example/Foo-GGUF --family foo --alias foo-30b --profiles reliable --target local --dry-run)"
assert_contains "$benchmark_output" "Benchmark plan"
assert_contains "$benchmark_output" "repo=Example/Foo-GGUF"
assert_contains "$benchmark_output" "family=foo"
assert_contains "$benchmark_output" "target=local"
assert_contains "$benchmark_output" "profiles=reliable"
```

**Step 2: Run test to verify it fails**

Run:

```bash
./test_oc_local.sh
```

Expected: FAIL because `benchmark` is not implemented.

**Step 3: Implement dry-run benchmark skeleton**

Support:

```text
benchmark --repo <repo> --family <family> --alias <alias> --profiles <csv> --target <target> --dry-run
```

Print the resolved plan. Do not start llama-server yet.

**Step 4: Verify**

Run:

```bash
bash -n scripts/model-manager.sh test_oc_local.sh
./test_oc_local.sh
```

Expected: PASS.

---

### Task 9: Add Benchmark Result Writing

**Files:**
- Modify: `scripts/model-manager.sh`
- Test: `test_oc_local.sh`

**Step 1: Write failing tests**

Add a no-run result-writing mode to avoid live model work in unit tests:

```bash
benchmark_record_tmp="$(mktemp -d)"
trap 'rm -rf "$probe_tmp" "$local_run_tmp" "$manager_tmp" "$discover_tmp" "$select_tmp" "$benchmark_tmp" "$benchmark_record_tmp"' EXIT

record_output="$(LOCAL_LLM_RUNS_DIR="$benchmark_record_tmp" "$repo_root/scripts/model-manager.sh" benchmark --repo Example/Foo-GGUF --family foo --alias foo-30b --profiles reliable --target local --record-only)"
assert_contains "$record_output" "Wrote benchmark result"
benchmark_file_count="$(find "$benchmark_record_tmp/benchmarks" -maxdepth 1 -type f -name '*.json' | wc -l | tr -d ' ')"
if [[ "$benchmark_file_count" != 1 ]]; then
  printf 'expected one benchmark file, got %s\n' "$benchmark_file_count" >&2
  exit 1
fi
benchmark_contents="$(find "$benchmark_record_tmp/benchmarks" -maxdepth 1 -type f -name '*.json' -exec cat {} \;)"
assert_contains "$benchmark_contents" '"repo":"Example/Foo-GGUF"'
assert_contains "$benchmark_contents" '"profile":"reliable"'
assert_contains "$benchmark_contents" '"load_status":"not_run"'
```

**Step 2: Run test to verify it fails**

Run:

```bash
./test_oc_local.sh
```

Expected: FAIL because benchmark result writing does not exist.

**Step 3: Implement result writing**

Create benchmark JSON with fields from the design:

```text
target, repo, family, alias, profile, ctx, batch, ubatch, ngl, load_status, prompt_tok_s, decode_tok_s, command, timestamp
```

For `--record-only`, set:

```text
load_status=not_run
prompt_tok_s=null
decode_tok_s=null
```

This establishes the data shape before live benchmark execution.

**Step 4: Verify**

Run:

```bash
bash -n scripts/model-manager.sh test_oc_local.sh
./test_oc_local.sh
```

Expected: PASS.

---

### Task 10: Add accept Dry-Run

**Files:**
- Modify: `scripts/model-manager.sh`
- Test: `test_oc_local.sh`

**Step 1: Write failing tests**

Create a fixture benchmark file in a temp dir and call accept dry-run:

```bash
accept_tmp="$(mktemp -d)"
trap 'rm -rf "$probe_tmp" "$local_run_tmp" "$manager_tmp" "$discover_tmp" "$select_tmp" "$benchmark_tmp" "$benchmark_record_tmp" "$accept_tmp"' EXIT
cat >"$accept_tmp/foo.json" <<'EOF'
{"repo":"Example/Foo-GGUF","family":"foo","alias":"foo-30b","target":"local","profile":"reliable","load_status":"success"}
EOF

accept_output="$($repo_root/scripts/model-manager.sh accept "$accept_tmp/foo.json" --dry-run)"
assert_contains "$accept_output" "Accept plan"
assert_contains "$accept_output" "family=foo"
assert_contains "$accept_output" "alias=foo-30b"
assert_contains "$accept_output" "would update scripts/oc-local"
assert_contains "$accept_output" "would create scripts/start"
```

**Step 2: Run test to verify it fails**

Run:

```bash
./test_oc_local.sh
```

Expected: FAIL because `accept` is not implemented.

**Step 3: Implement accept dry-run only**

Parse benchmark JSON with Python and print an accept plan.

Do not modify files in this task.

Dry-run output should list:

```text
scripts/startN.sh
scripts/oc-local
installer.sh
README.md
test_oc_local.sh
```

**Step 4: Verify**

Run:

```bash
bash -n scripts/model-manager.sh test_oc_local.sh
./test_oc_local.sh
```

Expected: PASS.

---

### Task 11: Update update-manager To Point At model-manager

**Files:**
- Modify: `scripts/update-manager.sh`
- Modify: `README.md`
- Test: `test_oc_local.sh`

**Step 1: Write failing tests**

Add assertions:

```bash
update_manager_output="$($repo_root/scripts/update-manager.sh 2>&1)"
assert_contains "$update_manager_output" "model-manager status"
assert_contains "$update_manager_output" "model-manager discover"

readme_contents="$(<"$repo_root/README.md")"
assert_contains "$readme_contents" "update-manager is a compatibility helper"
```

**Step 2: Run test to verify it fails**

Run:

```bash
./test_oc_local.sh
```

Expected: FAIL because update-manager still points at `model-discovery.sh --detailed` and placeholder model updates.

**Step 3: Implement compatibility messaging**

Keep `update-manager` non-destructive. Update its output to say model lifecycle work now lives in `model-manager`:

```text
To inspect model workflow state, run:
  model-manager status

To discover and benchmark models, run:
  model-manager discover --target remote:ubt26 --query "qwen coder gguf"
```

Do not make `update-manager` mutate files.

**Step 4: Verify**

Run:

```bash
bash -n scripts/update-manager.sh test_oc_local.sh
./test_oc_local.sh
```

Expected: PASS.

---

### Task 12: Final Verification

**Files:**
- Verify all changed shell scripts and docs.

**Step 1: Syntax checks**

Run:

```bash
bash -n scripts/oc-local scripts/model-manager.sh scripts/model-discovery.sh scripts/update-manager.sh installer.sh test_oc_local.sh
```

Expected: no output, exit 0.

**Step 2: Shellcheck if available**

Run:

```bash
if command -v shellcheck >/dev/null 2>&1; then shellcheck scripts/oc-local scripts/model-manager.sh scripts/model-discovery.sh scripts/update-manager.sh installer.sh test_oc_local.sh; fi
```

Expected: no errors. If warnings appear, fix them unless they are clearly unrelated pre-existing issues.

**Step 3: Test suite**

Run:

```bash
./test_oc_local.sh
```

Expected: existing success message, currently `oc-local dry-run tests passed`.

**Step 4: Manual smoke checks**

Run:

```bash
scripts/oc-local --target local qwen reliable --info
scripts/oc-local --target remote:ubt26 qwen reliable --info
scripts/model-manager.sh --help
scripts/model-manager.sh status
```

Expected: all commands exit 0 and print resolved settings without starting a model.

**Step 5: Review diff**

Run:

```bash
git diff -- scripts/oc-local scripts/model-manager.sh scripts/update-manager.sh installer.sh README.md test_oc_local.sh .gitignore docs/plans/2026-05-15-model-manager-design.md docs/plans/2026-05-15-model-manager-implementation.md
```

Expected: diff only contains intended model-manager and target-support changes.
