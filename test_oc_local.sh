#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
script="${OC_LOCAL_SCRIPT:-$repo_root/scripts/oc-local}"

run_dry() {
  "$script" --dry-run "$@"
}

run_info() {
  "$script" --info "$@"
}

assert_contains() {
  local haystack="$1"
  local needle="$2"
  if [[ "$haystack" != *"$needle"* ]]; then
    printf 'expected output to contain %q\noutput was:\n%s\n' "$needle" "$haystack" >&2
    return 1
  fi
}

assert_not_contains() {
  local haystack="$1"
  local needle="$2"
  if [[ "$haystack" == *"$needle"* ]]; then
    printf 'expected output not to contain %q\noutput was:\n%s\n' "$needle" "$haystack" >&2
    return 1
  fi
}

assert_line() {
  local haystack="$1"
  local expected_line="$2"
  if ! grep -qxF -- "$expected_line" <<<"$haystack"; then
    printf 'expected output to contain exact line %q\noutput was:\n%s\n' "$expected_line" "$haystack" >&2
    return 1
  fi
}

line_number_for() {
  local haystack="$1"
  local marker="$2"
  local line=''
  line="$(grep -nF -- "$marker" <<<"$haystack" | cut -d: -f1 | head -n 1 || true)"
  if [[ -z "$line" ]]; then
    printf 'expected output to contain marker %q for order check\noutput was:\n%s\n' "$marker" "$haystack" >&2
    return 1
  fi
  printf '%s\n' "$line"
}

help_output="$($script --help 2>&1)"
assert_contains "$help_output" "oc-local [family] [profile]"
assert_contains "$help_output" "--remote HOST"
assert_contains "$help_output" "--user USER"
assert_contains "$help_output" "-k"
assert_not_contains "$help_output" "speed     32k context"
assert_not_contains "$help_output" "tiny      40k context"
readme_contents="$(<"$repo_root/README.md")"
assert_contains "$readme_contents" "Qwen dense-thinking comparison"
assert_contains "$readme_contents" "not the responsive daily driver"
assert_contains "$readme_contents" "Qwen 35B defaults are vision-enabled"
assert_contains "$readme_contents" "Quant, KV Q4/Q5, and MMQ changes remain future benchmark/promotion work"
assert_not_contains "$readme_contents" "Qwen dense optimum"
assert_contains "$readme_contents" "## Helper Tools"
assert_contains "$readme_contents" "hardware-analyzer reports the machine it runs on"
assert_contains "$readme_contents" "model-discovery --detailed"
assert_contains "$readme_contents" "model-manager discover"
assert_contains "$readme_contents" "update-manager is a compatibility helper"
assert_contains "$readme_contents" "update-manager --config"
assert_contains "$readme_contents" "for family in qwen qwen-27b qwen-coder gemma gemma-vision gpt-oss deepseek-r1 qwen-opus qwen-heretic; do"
assert_contains "$readme_contents" "for script in scripts/oc-local scripts/model-manager.sh scripts/update-manager.sh scripts/model-discovery.sh scripts/hardware-analyzer.sh scripts/bench-mtp-remote.sh installer.sh scripts/start3.sh scripts/start8.sh scripts/start9.sh scripts/start10.sh scripts/start11.sh scripts/start12.sh scripts/start14.sh scripts/run-current-model.sh scripts/bench-installed-kv-remote.sh test_oc_local.sh; do bash -n \"\$script\" || exit 1; done"
assert_contains "$readme_contents" "shellcheck scripts/oc-local scripts/bench-mtp-remote.sh installer.sh scripts/start3.sh scripts/start8.sh scripts/start9.sh scripts/start10.sh scripts/start11.sh scripts/start12.sh scripts/start14.sh scripts/run-current-model.sh scripts/bench-installed-kv-remote.sh test_oc_local.sh"
assert_contains "$readme_contents" "systemctl --user restart llama-server.service"
assert_contains "$readme_contents" "run-current-model.sh"
assert_contains "$readme_contents" "REMOTE_SCRIPT=./start11.sh"
assert_contains "$readme_contents" 'localllm/qwen3.6-35b-a3b-mtp'
assert_contains "$readme_contents" "scripts/start11.sh scripts/start12.sh scripts/start14.sh scripts/run-current-model.sh"
assert_contains "$readme_contents" "journalctl --user -u llama-server.service"
assert_contains "$readme_contents" "Open WebUI listens on http://127.0.0.1:3002"
assert_contains "$readme_contents" "local-llm-switcher listens on http://127.0.0.1:3001"
assert_contains "$readme_contents" "Cloudflare stays pointed at port 3001"
assert_contains "$readme_contents" "GET /api/local-llm/models"
assert_contains "$readme_contents" "GET /api/local-llm/current"
assert_contains "$readme_contents" "POST /api/local-llm/switch"
assert_contains "$readme_contents" "GET /_switcher"
assert_contains "$readme_contents" "systemctl --user status local-llm-switcher.service llama-server.service"
assert_contains "$readme_contents" "docker ps --filter name=open-webui"
assert_contains "$readme_contents" "docker restart open-webui"
assert_contains "$readme_contents" "systemctl --user restart local-llm-switcher.service llama-server.service"
assert_contains "$readme_contents" "systemctl --user disable --now local-llm-switcher.service"
assert_contains "$readme_contents" "docker rm -f open-webui && docker run -d --name open-webui --restart unless-stopped --network host -e PORT=3001 -v open-webui:/app/backend/data ghcr.io/open-webui/open-webui:main"
assert_contains "$readme_contents" "--remote"
assert_not_contains "$readme_contents" "--target local"
assert_not_contains "$readme_contents" "--target remote:<host>"
assert_not_contains "$readme_contents" "OC_LOCAL_TARGET"
assert_not_contains "$readme_contents" "OC_LOCAL_LLAMA_DIR"
gitignore_contents="$(<"$repo_root/.gitignore")"
if ! grep -qxF '/runs/' <<<"$gitignore_contents"; then
  printf 'expected .gitignore to contain active exact line /runs/\n.gitignore was:\n%s\n' "$gitignore_contents" >&2
  exit 1
fi

model_discovery_output="$(OC_LOCAL_HF_FIXTURE="$repo_root/testdata/huggingface-model-search.json" OC_LOCAL_REMOTE_HOST=__none__ "$repo_root/scripts/model-discovery.sh" --limit 12)"
assert_contains "$model_discovery_output" "Model Discovery Results:"
assert_contains "$model_discovery_output" "Hardware source: local"
assert_contains "$model_discovery_output" "GPU:"
assert_contains "$model_discovery_output" "VRAM:"
assert_contains "$model_discovery_output" "ROCm target:"
assert_contains "$model_discovery_output" "Hugging Face GGUF Candidates"
assert_contains "$model_discovery_output" "unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF"
assert_contains "$model_discovery_output" "TargetOrg/Target-16B-GGUF | purpose=chat | class=target"
assert_contains "$model_discovery_output" "HugeOrg/Huge-80B-GGUF | purpose=reasoning | class=huge"
assert_contains "$model_discovery_output" "HugeOrg/Huge-405B-A22B-GGUF | purpose=reasoning | class=huge"
assert_contains "$model_discovery_output" "class=target"
assert_contains "$model_discovery_output" "class=small"
assert_contains "$model_discovery_output" "class=huge"
assert_contains "$model_discovery_output" "class=unknown"
assert_contains "$model_discovery_output" "Already Tuned Profiles"
assert_contains "$model_discovery_output" "oc-qwen-reliable --lean"
assert_not_contains "$model_discovery_output" "example/not-a-gguf-model"
assert_not_contains "$model_discovery_output" "not a Hugging Face search"
assert_not_contains "$model_discovery_output" "Recommended models:"
qwen_target_line="$(line_number_for "$model_discovery_output" "unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF")"
tiny_small_line="$(line_number_for "$model_discovery_output" "TinyOrg/Tiny-1B-GGUF")"
huge_line="$(line_number_for "$model_discovery_output" "HugeOrg/Huge-70B-GGUF")"
if (( qwen_target_line >= tiny_small_line || tiny_small_line >= huge_line )); then
  printf 'expected ranked order qwen target before tiny small before huge\noutput was:\n%s\n' "$model_discovery_output" >&2
  exit 1
fi

model_discovery_installed_output="$(OC_LOCAL_HF_FIXTURE="$repo_root/testdata/huggingface-model-search.json" OC_LOCAL_REMOTE_HOST=__none__ "$repo_root/scripts/model-discovery.sh" --installed-only)"
assert_contains "$model_discovery_installed_output" "Already Tuned Profiles"
assert_not_contains "$model_discovery_installed_output" "Hugging Face GGUF Candidates"

qwen_heretic_local_info="$(LLAMA_CPP_DIR=/tmp/local-llama run_info qwen-heretic reliable)"
assert_contains "$qwen_heretic_local_info" "--chat-template-file /tmp/local-llama/templates/qwen36-opencode.jinja"
assert_not_contains "$qwen_heretic_local_info" "/home/cass/llama.cpp/templates/qwen36-opencode.jinja"
qwen_heretic_remote_info="$(REMOTE_HOST=somehost run_info qwen-heretic reliable)"
assert_contains "$qwen_heretic_remote_info" "REMOTE_HOST: somehost"

model_discovery_help_output="$("$repo_root/scripts/model-discovery.sh" --help 2>&1)"
assert_contains "$model_discovery_help_output" "--query <text>"
assert_contains "$model_discovery_help_output" "--limit <n>"
assert_contains "$model_discovery_help_output" "maximum ranked candidates to print"
assert_not_contains "$model_discovery_help_output" "maximum Hugging Face results to request"
assert_contains "$model_discovery_help_output" "--installed-only"
model_manager_help_output="$("$repo_root/scripts/model-manager.sh" --help 2>&1)"
assert_contains "$model_manager_help_output" "Usage: model-manager"
assert_contains "$model_manager_help_output" "discover"
assert_contains "$model_manager_help_output" "select"
assert_contains "$model_manager_help_output" "benchmark"
assert_contains "$model_manager_help_output" "accept"
assert_contains "$model_manager_help_output" "status"
update_manager_output="$("$repo_root/scripts/update-manager.sh" 2>&1)"
assert_contains "$update_manager_output" "model-manager status"
assert_contains "$update_manager_output" "model-manager discover"
assert_contains "$update_manager_output" "model-manager benchmark"
update_manager_usage_status=0
update_manager_usage_output="$("$repo_root/scripts/update-manager.sh" --unknown 2>&1)" || update_manager_usage_status=$?
if [[ "$update_manager_usage_status" != 2 ]]; then
  printf 'expected update-manager unknown option to exit 2, got %s\noutput was:\n%s\n' "$update_manager_usage_status" "$update_manager_usage_output" >&2
  exit 1
fi
assert_contains "$update_manager_usage_output" "Usage: update-manager [options]"
assert_not_contains "$update_manager_usage_output" "Usage: update-manager.sh"
manager_tmp="$(mktemp -d)"
mkdir -p "$manager_tmp/candidates" "$manager_tmp/selections" "$manager_tmp/benchmarks"
printf '{}\n' >"$manager_tmp/candidates/sample.json"
status_output="$(LOCAL_LLM_RUNS_DIR="$manager_tmp" "$repo_root/scripts/model-manager.sh" status)"
assert_contains "$status_output" "Model Manager Status"
assert_contains "$status_output" "Candidates: 1"
assert_contains "$status_output" "Selections: 0"
assert_contains "$status_output" "Benchmarks: 0"
discover_tmp="$(mktemp -d)"
discover_output="$(LOCAL_LLM_RUNS_DIR="$discover_tmp" OC_LOCAL_HF_FIXTURE="$repo_root/testdata/huggingface-model-search.json" "$repo_root/scripts/model-manager.sh" discover --target local --query "qwen coder gguf" --limit 3)"
assert_contains "$discover_output" "Model Discovery Results:"
assert_contains "$discover_output" "Hardware source: local"
assert_contains "$discover_output" "unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF"
discover_missing_target_output="$discover_tmp/missing-target.out"
if "$repo_root/scripts/model-manager.sh" discover --target >"$discover_missing_target_output" 2>&1; then
  printf 'expected discover --target without value to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$discover_missing_target_output")" "--target requires local or remote:<host>"
discover_missing_query_output="$discover_tmp/missing-query.out"
if "$repo_root/scripts/model-manager.sh" discover --query >"$discover_missing_query_output" 2>&1; then
  printf 'expected discover --query without value to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$discover_missing_query_output")" "--query requires text"
discover_missing_limit_output="$discover_tmp/missing-limit.out"
if "$repo_root/scripts/model-manager.sh" discover --limit >"$discover_missing_limit_output" 2>&1; then
  printf 'expected discover --limit without value to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$discover_missing_limit_output")" "--limit requires a number"
select_tmp="$(mktemp -d)"
select_output="$(LOCAL_LLM_RUNS_DIR="$select_tmp" "$repo_root/scripts/model-manager.sh" select --repo 'Example/Foo "Bar" GGUF' --family foo --alias foo-30b --purpose 'code "chat"' --target local)"
assert_contains "$select_output" 'Selected Example/Foo "Bar" GGUF'
selection_file_count="$(find "$select_tmp/selections" -maxdepth 1 -type f -name '*.json' | wc -l | tr -d ' ')"
if [[ "$selection_file_count" != 1 ]]; then
  printf 'expected one selection file, got %s\n' "$selection_file_count" >&2
  exit 1
fi
selection_file="$(find "$select_tmp/selections" -maxdepth 1 -type f -name '*.json' -print -quit)"
python3 - "$selection_file" 'Example/Foo "Bar" GGUF' foo foo-30b 'code "chat"' local <<'PY'
import json
import sys

path, repo, family, alias, purpose, target = sys.argv[1:]
with open(path, encoding="utf-8") as handle:
    selection = json.load(handle)
expected = {
    "repo": repo,
    "family": family,
    "alias": alias,
    "purpose": purpose,
    "target": target,
}
if selection != expected:
    raise SystemExit(f"unexpected selection JSON: {selection!r}")
PY
select_collision_tmp="$(mktemp -d)"
mkdir -p "$select_collision_tmp/bin"
cat >"$select_collision_tmp/bin/date" <<'EOF'
#!/usr/bin/env bash
printf '20260515-120000\n'
EOF
chmod +x "$select_collision_tmp/bin/date"
PATH="$select_collision_tmp/bin:$PATH" LOCAL_LLM_RUNS_DIR="$select_collision_tmp" "$repo_root/scripts/model-manager.sh" select --repo Example/Foo-GGUF --family foo --alias foo-30b --target local >/dev/null
PATH="$select_collision_tmp/bin:$PATH" LOCAL_LLM_RUNS_DIR="$select_collision_tmp" "$repo_root/scripts/model-manager.sh" select --repo Example/Foo-GGUF --family foo --alias foo-30b --target local >/dev/null
selection_collision_file_count="$(find "$select_collision_tmp/selections" -maxdepth 1 -type f -name '*.json' | wc -l | tr -d ' ')"
if [[ "$selection_collision_file_count" != 2 ]]; then
  printf 'expected two selection files for repeated selects, got %s\n' "$selection_collision_file_count" >&2
  exit 1
fi
select_missing_repo_output="$select_tmp/missing-repo.out"
if LOCAL_LLM_RUNS_DIR="$select_tmp" "$repo_root/scripts/model-manager.sh" select --family foo --alias foo-30b >"$select_missing_repo_output" 2>&1; then
  printf 'expected select without --repo to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$select_missing_repo_output")" "select requires --repo"
select_missing_family_output="$select_tmp/missing-family.out"
if LOCAL_LLM_RUNS_DIR="$select_tmp" "$repo_root/scripts/model-manager.sh" select --repo Example/Foo-GGUF --alias foo-30b >"$select_missing_family_output" 2>&1; then
  printf 'expected select without --family to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$select_missing_family_output")" "select requires --family"
select_missing_alias_output="$select_tmp/missing-alias.out"
if LOCAL_LLM_RUNS_DIR="$select_tmp" "$repo_root/scripts/model-manager.sh" select --repo Example/Foo-GGUF --family foo >"$select_missing_alias_output" 2>&1; then
  printf 'expected select without --alias to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$select_missing_alias_output")" "select requires --alias"
select_invalid_target_output="$select_tmp/invalid-target.out"
if LOCAL_LLM_RUNS_DIR="$select_tmp" "$repo_root/scripts/model-manager.sh" select --repo Example/Foo-GGUF --family foo --alias foo-30b --target nowhere >"$select_invalid_target_output" 2>&1; then
  printf 'expected select with invalid target to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$select_invalid_target_output")" "invalid target: nowhere"
select_empty_remote_output="$select_tmp/empty-remote.out"
if LOCAL_LLM_RUNS_DIR="$select_tmp" "$repo_root/scripts/model-manager.sh" select --repo Example/Foo-GGUF --family foo --alias foo-30b --target remote: >"$select_empty_remote_output" 2>&1; then
  printf 'expected select with empty remote host to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$select_empty_remote_output")" "remote target requires a host: remote:"
benchmark_tmp="$(mktemp -d)"
benchmark_output="$(LOCAL_LLM_RUNS_DIR="$benchmark_tmp" "$repo_root/scripts/model-manager.sh" benchmark --repo Example/Foo-GGUF --family foo --alias foo-30b --profiles reliable --target local --dry-run)"
assert_contains "$benchmark_output" "Benchmark plan"
assert_contains "$benchmark_output" "repo=Example/Foo-GGUF"
assert_contains "$benchmark_output" "family=foo"
assert_contains "$benchmark_output" "target=local"
assert_contains "$benchmark_output" "profiles=reliable"
benchmark_default_output="$(LOCAL_LLM_RUNS_DIR="$benchmark_tmp" OC_LOCAL_REMOTE_HOST=bench-host "$repo_root/scripts/model-manager.sh" benchmark --repo Example/Foo-GGUF --family foo --alias foo-30b --dry-run)"
assert_contains "$benchmark_default_output" "profiles=reliable"
assert_contains "$benchmark_default_output" "target=remote:bench-host"
benchmark_record_tmp="$(mktemp -d)"
record_output="$(LOCAL_LLM_RUNS_DIR="$benchmark_record_tmp" "$repo_root/scripts/model-manager.sh" benchmark --repo Example/Foo-GGUF --family foo --alias foo-30b --profiles reliable --target local --record-only)"
assert_contains "$record_output" "Wrote benchmark result"
benchmark_file_count="$(find "$benchmark_record_tmp/benchmarks" -maxdepth 1 -type f -name '*.json' | wc -l | tr -d ' ')"
if [[ "$benchmark_file_count" != 1 ]]; then
  printf 'expected one benchmark file, got %s\n' "$benchmark_file_count" >&2
  exit 1
fi
benchmark_file="$(find "$benchmark_record_tmp/benchmarks" -maxdepth 1 -type f -name '*.json' -print -quit)"
python3 - "$benchmark_file" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    result = json.load(handle)
expected_keys = {
    "target", "repo", "family", "alias", "profile", "ctx", "batch", "ubatch", "ngl",
    "load_status", "prompt_tok_s", "decode_tok_s", "command", "timestamp",
}
if set(result) != expected_keys:
    raise SystemExit(f"unexpected benchmark keys: {sorted(result)}")
expected_values = {
    "target": "local",
    "repo": "Example/Foo-GGUF",
    "family": "foo",
    "alias": "foo-30b",
    "profile": "reliable",
    "load_status": "not_run",
    "prompt_tok_s": None,
    "decode_tok_s": None,
}
for key, value in expected_values.items():
    if result[key] != value:
        raise SystemExit(f"unexpected {key}: {result[key]!r}")
PY
benchmark_multi_tmp="$(mktemp -d)"
multi_record_output="$(LOCAL_LLM_RUNS_DIR="$benchmark_multi_tmp" "$repo_root/scripts/model-manager.sh" benchmark --repo Example/Foo-GGUF --family foo --alias foo-30b --profiles speed,reliable --target local --record-only)"
assert_contains "$multi_record_output" "Wrote benchmark result"
benchmark_multi_file_count="$(find "$benchmark_multi_tmp/benchmarks" -maxdepth 1 -type f -name '*.json' | wc -l | tr -d ' ')"
if [[ "$benchmark_multi_file_count" != 2 ]]; then
  printf 'expected two benchmark files, got %s\n' "$benchmark_multi_file_count" >&2
  exit 1
fi
python3 - "$benchmark_multi_tmp/benchmarks" <<'PY'
import json
import pathlib
import sys

benchmark_dir = pathlib.Path(sys.argv[1])
results = []
for path in benchmark_dir.glob("*.json"):
    with path.open(encoding="utf-8") as handle:
        result = json.load(handle)
    if "/" in path.name or "," in result["profile"]:
        raise SystemExit(f"unsafe benchmark result: {path.name} {result!r}")
    results.append(result)
profiles = sorted(result["profile"] for result in results)
if profiles != ["reliable", "speed"]:
    raise SystemExit(f"unexpected benchmark profiles: {profiles!r}")
if any(result["load_status"] != "not_run" for result in results):
    raise SystemExit(f"unexpected load status: {results!r}")
if any(result["prompt_tok_s"] is not None or result["decode_tok_s"] is not None for result in results):
    raise SystemExit(f"expected null token rates: {results!r}")
PY
benchmark_bad_profile_tmp="$(mktemp -d)"
benchmark_bad_profile_output="$benchmark_bad_profile_tmp/bad-profile.out"
if LOCAL_LLM_RUNS_DIR="$benchmark_bad_profile_tmp" "$repo_root/scripts/model-manager.sh" benchmark --repo Example/Foo-GGUF --family foo --alias foo-30b --profiles bad/profile --target local --record-only >"$benchmark_bad_profile_output" 2>&1; then
  printf 'expected benchmark with invalid profile path segment to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$benchmark_bad_profile_output")" "invalid benchmark profile: bad/profile"
benchmark_bad_profile_count="$(find "$benchmark_bad_profile_tmp/benchmarks" -maxdepth 1 -type f -name '*.json' 2>/dev/null | wc -l | tr -d ' ')"
if [[ "$benchmark_bad_profile_count" != 0 ]]; then
  printf 'expected invalid benchmark profile to write no files, got %s\n' "$benchmark_bad_profile_count" >&2
  exit 1
fi
benchmark_empty_entry_output="$benchmark_tmp/empty-profile-entry.out"
if LOCAL_LLM_RUNS_DIR="$benchmark_tmp" "$repo_root/scripts/model-manager.sh" benchmark --repo Example/Foo-GGUF --family foo --alias foo-30b --profiles speed,,reliable --target local --record-only >"$benchmark_empty_entry_output" 2>&1; then
  printf 'expected benchmark with empty profile entry to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$benchmark_empty_entry_output")" "--profiles contains an empty profile"
benchmark_trailing_empty_entry_output="$benchmark_tmp/trailing-empty-profile-entry.out"
if LOCAL_LLM_RUNS_DIR="$benchmark_tmp" "$repo_root/scripts/model-manager.sh" benchmark --repo Example/Foo-GGUF --family foo --alias foo-30b --profiles speed, --target local --record-only >"$benchmark_trailing_empty_entry_output" 2>&1; then
  printf 'expected benchmark with trailing empty profile entry to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$benchmark_trailing_empty_entry_output")" "--profiles contains an empty profile"
benchmark_missing_repo_output="$benchmark_tmp/missing-repo.out"
if LOCAL_LLM_RUNS_DIR="$benchmark_tmp" "$repo_root/scripts/model-manager.sh" benchmark --family foo --alias foo-30b --dry-run >"$benchmark_missing_repo_output" 2>&1; then
  printf 'expected benchmark without --repo to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$benchmark_missing_repo_output")" "benchmark requires --repo"
benchmark_missing_family_output="$benchmark_tmp/missing-family.out"
if LOCAL_LLM_RUNS_DIR="$benchmark_tmp" "$repo_root/scripts/model-manager.sh" benchmark --repo Example/Foo-GGUF --alias foo-30b --dry-run >"$benchmark_missing_family_output" 2>&1; then
  printf 'expected benchmark without --family to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$benchmark_missing_family_output")" "benchmark requires --family"
benchmark_missing_alias_output="$benchmark_tmp/missing-alias.out"
if LOCAL_LLM_RUNS_DIR="$benchmark_tmp" "$repo_root/scripts/model-manager.sh" benchmark --repo Example/Foo-GGUF --family foo --dry-run >"$benchmark_missing_alias_output" 2>&1; then
  printf 'expected benchmark without --alias to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$benchmark_missing_alias_output")" "benchmark requires --alias"
benchmark_invalid_target_output="$benchmark_tmp/invalid-target.out"
if LOCAL_LLM_RUNS_DIR="$benchmark_tmp" "$repo_root/scripts/model-manager.sh" benchmark --repo Example/Foo-GGUF --family foo --alias foo-30b --target nowhere --dry-run >"$benchmark_invalid_target_output" 2>&1; then
  printf 'expected benchmark with invalid target to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$benchmark_invalid_target_output")" "invalid target: nowhere"
benchmark_profiles_flag_value_output="$benchmark_tmp/profiles-flag-value.out"
if LOCAL_LLM_RUNS_DIR="$benchmark_tmp" "$repo_root/scripts/model-manager.sh" benchmark --repo Example/Foo-GGUF --family foo --alias foo-30b --profiles --dry-run >"$benchmark_profiles_flag_value_output" 2>&1; then
  printf 'expected benchmark --profiles without a value to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$benchmark_profiles_flag_value_output")" "--profiles requires a non-empty value"
benchmark_empty_profiles_output="$benchmark_tmp/empty-profiles.out"
if LOCAL_LLM_RUNS_DIR="$benchmark_tmp" "$repo_root/scripts/model-manager.sh" benchmark --repo Example/Foo-GGUF --family foo --alias foo-30b --profiles '' --dry-run >"$benchmark_empty_profiles_output" 2>&1; then
  printf 'expected benchmark with empty --profiles to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$benchmark_empty_profiles_output")" "--profiles requires a non-empty value"
benchmark_no_dry_run_output="$benchmark_tmp/no-dry-run.out"
if LOCAL_LLM_RUNS_DIR="$benchmark_tmp" "$repo_root/scripts/model-manager.sh" benchmark --repo Example/Foo-GGUF --family foo --alias foo-30b >"$benchmark_no_dry_run_output" 2>&1; then
  printf 'expected benchmark without --dry-run to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$benchmark_no_dry_run_output")" "benchmark currently supports --dry-run only"
accept_tmp="$(mktemp -d)"
cat >"$accept_tmp/foo.json" <<'EOF'
{"repo":"Example/Foo-GGUF","family":"foo","alias":"foo-30b","target":"local","profile":"reliable","load_status":"success"}
EOF
accept_output="$("$repo_root/scripts/model-manager.sh" accept "$accept_tmp/foo.json" --dry-run)"
assert_contains "$accept_output" "Accept plan"
assert_contains "$accept_output" "family=foo"
assert_contains "$accept_output" "alias=foo-30b"
assert_contains "$accept_output" "would update scripts/oc-local"
assert_contains "$accept_output" "would create scripts/start"
assert_contains "$accept_output" "would create scripts/start11.sh"
cp "$repo_root/scripts/oc-local" "$accept_tmp/oc-local.before"
cp "$repo_root/installer.sh" "$accept_tmp/installer.before"
cp "$repo_root/README.md" "$accept_tmp/README.before"
cp "$repo_root/test_oc_local.sh" "$accept_tmp/test_oc_local.before"
accept_start08="$repo_root/scripts/start08.sh"
accept_start08_original_backup=""
accept_start08_original_existed=0
if [[ -e "$accept_start08" ]]; then
  accept_start08_original_existed=1
  accept_start08_original_backup="$accept_tmp/start08.sh.before"
  cp "$accept_start08" "$accept_start08_original_backup"
fi
cleanup_accept_start08() {
  if [[ "$accept_start08_original_existed" == 1 ]]; then
    cp "$accept_start08_original_backup" "$accept_start08"
  else
    rm -f "$accept_start08"
  fi
}
trap cleanup_accept_start08 EXIT
accept_start08_trap_line="$(line_number_for "$(<"$repo_root/test_oc_local.sh")" "trap cleanup_accept_start08 EXIT")"
accept_start08_create_line="$(line_number_for "$(<"$repo_root/test_oc_local.sh")" "printf '#!/usr/bin/env bash\\n' >\"\$accept_start08\"")"
assert_not_contains "$(<"$repo_root/test_oc_local.sh")" "accept_start08_backup=\"\$accept_tmp/start08.sh.sentinel\""
if (( accept_start08_trap_line >= accept_start08_create_line )); then
  printf 'expected start08 cleanup trap before creating scripts/start08.sh\n' >&2
  exit 1
fi
printf '#!/usr/bin/env bash\n' >"$accept_start08"
accept_start08_output="$("$repo_root/scripts/model-manager.sh" accept "$accept_tmp/foo.json" --dry-run)"
assert_contains "$accept_start08_output" "would create scripts/start11.sh"
cmp -s "$repo_root/scripts/oc-local" "$accept_tmp/oc-local.before"
cmp -s "$repo_root/installer.sh" "$accept_tmp/installer.before"
cmp -s "$repo_root/README.md" "$accept_tmp/README.before"
cmp -s "$repo_root/test_oc_local.sh" "$accept_tmp/test_oc_local.before"
cleanup_accept_start08
cat >"$accept_tmp/invalid.json" <<'EOF'
{"repo":
EOF
accept_invalid_output="$accept_tmp/invalid.out"
if "$repo_root/scripts/model-manager.sh" accept "$accept_tmp/invalid.json" --dry-run >"$accept_invalid_output" 2>&1; then
  printf 'expected accept with invalid JSON to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$accept_invalid_output")" "benchmark JSON is invalid"
assert_not_contains "$(<"$accept_invalid_output")" "Traceback"
printf '[]\n' >"$accept_tmp/non-object.json"
accept_non_object_output="$accept_tmp/non-object.out"
if "$repo_root/scripts/model-manager.sh" accept "$accept_tmp/non-object.json" --dry-run >"$accept_non_object_output" 2>&1; then
  printf 'expected accept with non-object JSON to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$accept_non_object_output")" "benchmark JSON must be an object"
assert_not_contains "$(<"$accept_non_object_output")" "Traceback"
cat >"$accept_tmp/missing-family.json" <<'EOF'
{"repo":"Example/Foo-GGUF","alias":"foo-30b","target":"local","profile":"reliable","load_status":"success"}
EOF
accept_missing_output="$accept_tmp/missing-family.out"
if "$repo_root/scripts/model-manager.sh" accept "$accept_tmp/missing-family.json" --dry-run >"$accept_missing_output" 2>&1; then
  printf 'expected accept with missing family to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$accept_missing_output")" "benchmark JSON missing required field: family"
cat >"$accept_tmp/bad-family.json" <<'EOF'
{"repo":"Example/Foo-GGUF","family":30,"alias":"foo-30b","target":"local","profile":"reliable","load_status":"success"}
EOF
accept_bad_family_output="$accept_tmp/bad-family.out"
if "$repo_root/scripts/model-manager.sh" accept "$accept_tmp/bad-family.json" --dry-run >"$accept_bad_family_output" 2>&1; then
  printf 'expected accept with non-string family to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$accept_bad_family_output")" "benchmark JSON field must be a string: family"
python3 - "$accept_tmp/control.json" <<'PY'
import json
import sys

with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump(
        {
            "repo": "Example/Foo-GGUF",
            "family": "foo\nbar",
            "alias": "foo-30b",
            "target": "local",
            "profile": "reliable",
            "load_status": "success",
        },
        handle,
    )
    handle.write("\n")
PY
accept_control_output="$accept_tmp/control.out"
if "$repo_root/scripts/model-manager.sh" accept "$accept_tmp/control.json" --dry-run >"$accept_control_output" 2>&1; then
  printf 'expected accept with control character to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$accept_control_output")" "benchmark JSON field contains a control character: family"
cat >"$accept_tmp/failed-load.json" <<'EOF'
{"repo":"Example/Foo-GGUF","family":"foo","alias":"foo-30b","target":"local","profile":"reliable","load_status":"failed"}
EOF
accept_failed_load_output="$accept_tmp/failed-load.out"
if "$repo_root/scripts/model-manager.sh" accept "$accept_tmp/failed-load.json" --dry-run >"$accept_failed_load_output" 2>&1; then
  printf 'expected accept with unsuccessful load_status to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$accept_failed_load_output")" "benchmark JSON load_status is not success: failed"
installer_contents="$(<"$repo_root/installer.sh")"
assert_contains "$installer_contents" "qwen-27b"
assert_contains "$installer_contents" "oc-qwen-mtp"
assert_contains "$installer_contents" "oc-qwen-hauhau"
assert_contains "$installer_contents" "oc-qwen-hauhau-ses-2009"
assert_contains "$installer_contents" 'qwen-hauhau reliable "$@" --lean -s ses_2009bfccfffeEVdvBAajurVOi4'
assert_contains "$installer_contents" "ses_2009bfccfffeEVdvBAajurVOi4"
assert_contains "$installer_contents" "qwen-27b-hauhau"
assert_contains "$installer_contents" "oc-glm-hauhau"
assert_not_contains "$installer_contents" 'oc-local" glm-hauhau'
assert_contains "$installer_contents" "gemma-hauhau"
assert_contains "$installer_contents" "oc-qwen-27b-mtp"
assert_contains "$installer_contents" "oc-qwen-opus-mtp"
assert_contains "$installer_contents" "oc-qwen-heretic-mtp"
assert_contains "$installer_contents" "oc-qwen-27b-long"
assert_contains "$installer_contents" "scripts/model-manager.sh"

probe_tmp="$(mktemp -d)"
trap 'cleanup_accept_start08; rm -rf "$probe_tmp" "$manager_tmp" "$discover_tmp" "$select_tmp" "$select_collision_tmp" "$benchmark_tmp" "$benchmark_record_tmp" "$benchmark_multi_tmp" "$benchmark_bad_profile_tmp" "$accept_tmp"' EXIT
cat >"$probe_tmp/curl" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
url="${*: -1}"
case "$url" in
  *limit=12*)
    printf '[{"id":"FetchOrg/Fetch-16B-GGUF","downloads":1,"tags":["gguf"]}]\n'
    ;;
  *)
    printf 'expected Hugging Face fetch URL to request at least display limit, got: %s\n' "$url" >&2
    exit 1
    ;;
esac
EOF
chmod +x "$probe_tmp/curl"
fetch_limit_output="$(PATH="$probe_tmp:$PATH" OC_LOCAL_REMOTE_HOST=__none__ OC_LOCAL_HF_FETCH_LIMIT=3 "$repo_root/scripts/model-discovery.sh" --limit 12)"
assert_contains "$fetch_limit_output" "FetchOrg/Fetch-16B-GGUF"
cat >"$probe_tmp/ssh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
command_text="${*: -1}"
case "$command_text" in
  nproc)
    printf '16\n'
    ;;
  *free*)
    printf '64\n'
    ;;
  *rocminfo*)
    exit 0
    ;;
  *rocm-smi*)
    exit 0
    ;;
  *llama-server*)
    printf 'llama-server device 0: AMD Radeon RX 7900 XT (gfx1100) - 24560 MiB VRAM\n'
    ;;
  *)
    printf 'unknown\n'
    ;;
esac
EOF
chmod +x "$probe_tmp/ssh"
remote_fallback_output="$(PATH="$probe_tmp:$PATH" OC_LOCAL_HF_FIXTURE="$repo_root/testdata/huggingface-model-search.json" "$repo_root/scripts/model-discovery.sh" --host fake-host --installed-only)"
assert_contains "$remote_fallback_output" "Hardware source: remote:fake-host"
assert_contains "$remote_fallback_output" "GPU: llama-server device 0: AMD Radeon RX 7900 XT"

cat >"$probe_tmp/ssh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
command_text="${*: -1}"
case "$command_text" in
  nproc|*free*)
    exit 0
    ;;
  *rocminfo*)
    exit 0
    ;;
  *rocm-smi*)
    exit 0
    ;;
  *llama-server*)
    printf 'llama-server device 1: AMD Radeon PRO W7900 (gfx1100) - 48000 MiB VRAM\n'
    ;;
  *)
    printf 'unknown\n'
    ;;
esac
EOF
chmod +x "$probe_tmp/ssh"
remote_missing_cpu_output="$(PATH="$probe_tmp:$PATH" OC_LOCAL_HF_FIXTURE="$repo_root/testdata/huggingface-model-search.json" "$repo_root/scripts/model-discovery.sh" --host cpu-missing-host --installed-only)"
assert_contains "$remote_missing_cpu_output" "Hardware source: remote:cpu-missing-host"
assert_contains "$remote_missing_cpu_output" "CPU Cores: unknown"
assert_contains "$remote_missing_cpu_output" "RAM: unknown GB"
assert_contains "$remote_missing_cpu_output" "GPU: llama-server device 1: AMD Radeon PRO W7900"

cat >"$probe_tmp/ssh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
command_text="${*: -1}"
case "$command_text" in
  nproc|*free*|*rocminfo*|*rocm-smi*)
    exit 0
    ;;
  *"cd 'quote'\\''safe'"*)
    printf 'llama-server device 2: quoted remote dir GPU (gfx1100) - 24560 MiB VRAM\n'
    ;;
  *llama-server*)
    printf 'unsafe remote dir quoting: %s\n' "$command_text"
    ;;
  *)
    printf 'unknown\n'
    ;;
esac
EOF
chmod +x "$probe_tmp/ssh"
remote_quoted_dir_output="$(PATH="$probe_tmp:$PATH" OC_LOCAL_REMOTE_DIR="quote'safe" OC_LOCAL_HF_FIXTURE="$repo_root/testdata/huggingface-model-search.json" "$repo_root/scripts/model-discovery.sh" --host quoted-dir-host --installed-only)"
assert_contains "$remote_quoted_dir_output" "GPU: llama-server device 2: quoted remote dir GPU"
assert_not_contains "$remote_quoted_dir_output" "unsafe remote dir quoting"

cat >"$probe_tmp/ssh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
command_text="${*: -1}"
case "$command_text" in
  nproc)
    printf '16\n'
    ;;
  *free*)
    printf '64\n'
    ;;
  *rocminfo*Marketing*)
    printf 'AMD Radeon RX 7900 XT\n'
    ;;
  *rocminfo*gfx*)
    printf 'gfx1100\n'
    ;;
  *rocm-smi*|*llama-server*)
    exit 0
    ;;
  *)
    printf 'unknown\n'
    ;;
esac
EOF
chmod +x "$probe_tmp/ssh"
remote_rocminfo_gpu_output="$(PATH="$probe_tmp:$PATH" OC_LOCAL_HF_FIXTURE="$repo_root/testdata/huggingface-model-search.json" "$repo_root/scripts/model-discovery.sh" --host rocminfo-gpu-host --installed-only)"
assert_contains "$remote_rocminfo_gpu_output" "GPU: AMD Radeon RX 7900 XT"
assert_not_contains "$remote_rocminfo_gpu_output" "GPU: Intel"

cat >"$probe_tmp/nproc" <<'EOF'
#!/usr/bin/env bash
exit 1
EOF
cat >"$probe_tmp/free" <<'EOF'
#!/usr/bin/env bash
exit 1
EOF
cat >"$probe_tmp/rocminfo" <<'EOF'
#!/usr/bin/env bash
exit 1
EOF
cat >"$probe_tmp/rocm-smi" <<'EOF'
#!/usr/bin/env bash
exit 1
EOF
chmod +x "$probe_tmp/nproc" "$probe_tmp/free" "$probe_tmp/rocminfo" "$probe_tmp/rocm-smi"
local_probe_output="$(PATH="$probe_tmp:$PATH" OC_LOCAL_HF_FIXTURE="$repo_root/testdata/huggingface-model-search.json" "$repo_root/scripts/model-discovery.sh" --local --installed-only)"
assert_contains "$local_probe_output" "Hardware source: local"
assert_contains "$local_probe_output" "GPU: unknown"
assert_contains "$local_probe_output" "VRAM: unknown"

cat >"$probe_tmp/ssh" <<'EOF'
#!/usr/bin/env bash
exit 255
EOF
chmod +x "$probe_tmp/ssh"
default_remote_failed_output="$(PATH="$probe_tmp:$PATH" OC_LOCAL_HF_FIXTURE="$repo_root/testdata/huggingface-model-search.json" "$repo_root/scripts/model-discovery.sh" --installed-only)"
assert_contains "$default_remote_failed_output" "Hardware source: local"

hardware_help_output="$("$repo_root/scripts/hardware-analyzer.sh" --help)"
assert_contains "$hardware_help_output" "--remote [host]"

bench_mtp_contents="$(<"$repo_root/scripts/bench-mtp-remote.sh")"
assert_contains "$bench_mtp_contents" "--spec-type draft-mtp"
assert_contains "$bench_mtp_contents" "--spec-draft-n-max"
assert_contains "$bench_mtp_contents" "qwen3.6-35b-a3b-mtp"
assert_contains "$bench_mtp_contents" "qwen3.6-27b-mtp"
assert_contains "$bench_mtp_contents" "detect_thread_count()"
assert_contains "$bench_mtp_contents" "sysctl -n hw.ncpu"
assert_contains "$bench_mtp_contents" "chat_completion_request()"
chat_request_arg='chat_request'
assert_contains "$bench_mtp_contents" "-d \"\$$chat_request_arg\""

run_current_contents="$(<"$repo_root/scripts/run-current-model.sh")"
assert_contains "$run_current_contents" "current-model.env"
assert_contains "$run_current_contents" "REMOTE_SCRIPT"
assert_contains "$run_current_contents" "REMOTE_PROFILE"
assert_contains "$run_current_contents" "exec \"\$REMOTE_SCRIPT\" \"\$REMOTE_PROFILE\""

start4_contents="$(<"$repo_root/scripts/start4.sh")"
start5_contents="$(<"$repo_root/scripts/start5.sh")"
start2_contents="$(<"$repo_root/scripts/start2.sh")"
start3_contents="$(<"$repo_root/scripts/start3.sh")"
start6_contents="$(<"$repo_root/scripts/start6.sh")"
start7_contents="$(<"$repo_root/scripts/start7.sh")"
start8_contents="$(<"$repo_root/scripts/start8.sh")"
start11_contents="$(<"$repo_root/scripts/start11.sh")"
start4_fastlong_block="${start4_contents#*fastlong)}"
start4_fastlong_block="${start4_fastlong_block%%balanced)*}"
start4_balanced_block="${start4_contents#*balanced)}"
start4_balanced_block="${start4_balanced_block%%reliable)*}"
start4_reliable_block="${start4_contents#*reliable)}"
start4_reliable_block="${start4_reliable_block%%tiny)*}"
assert_contains "$start4_contents" "--alias gemma-4-31b-it"
assert_contains "$start4_fastlong_block" "quant=\"UD-Q2_K_XL\""
assert_contains "$start4_balanced_block" "quant=\"UD-Q2_K_XL\""
assert_contains "$start4_reliable_block" "quant=\"UD-Q2_K_XL\""
assert_contains "$start4_contents" "--no-mmproj"
assert_contains "$start5_contents" "--alias gemma-4-31b-it-vision"
assert_contains "$start2_contents" "unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF"
assert_contains "$start2_contents" "--alias qwen3-coder-30b-a3b-instruct"
assert_contains "$start3_contents" "--mmproj-auto"
assert_contains "$start3_contents" "--chat-template-kwargs '{\"enable_thinking\":false}'"
assert_not_contains "$start3_contents" "--no-mmproj"
assert_contains "$start6_contents" "unsloth/gpt-oss-20b-GGUF"
assert_contains "$start6_contents" "--alias gpt-oss-20b"
assert_contains "$start6_contents" "reasoning_effort=high"
assert_contains "$start7_contents" "unsloth/DeepSeek-R1-Distill-Qwen-32B-GGUF"
assert_contains "$start7_contents" "Q3_K_M"
assert_contains "$start7_contents" "--alias deepseek-r1-distill-qwen-32b"
assert_contains "$start8_contents" "unsloth/Qwen3.6-27B-MTP-GGUF"
assert_contains "$start8_contents" "--spec-type draft-mtp"
assert_contains "$start8_contents" "--spec-draft-n-max 2"
assert_contains "$start8_contents" "--alias qwen3.6-27b-mtp"
assert_contains "$(<"$repo_root/scripts/start9.sh")" "--alias qwen3.6-27b-opus-mtp"
assert_contains "$(<"$repo_root/scripts/start10.sh")" "--alias qwen3.6-27b-heretic-mtp"
assert_contains "$start11_contents" "--mmproj-auto"
assert_contains "$start11_contents" "--chat-template-kwargs '{\"enable_thinking\":false}'"
assert_not_contains "$start11_contents" "--no-mmproj"
if [[ "$start5_contents" == *"--no-mmproj"* ]]; then
  printf 'expected start5.sh to allow mmproj for vision\n' >&2
  exit 1
fi

fastlong_output="$(run_dry fastlong)"
assert_contains "$fastlong_output" "profile=fastlong"
assert_contains "$fastlong_output" "family=qwen"
assert_contains "$fastlong_output" "context=49152"
assert_contains "$fastlong_output" "remote_start=./start3.sh fastlong"
assert_contains "$fastlong_output" "model=localllm/qwen3.6-35b-a3b-mtp"
assert_contains "$fastlong_output" '"qwen3.6-35b-a3b-mtp":{"name":"qwen3.6-35b-a3b-mtp"'
assert_contains "$fastlong_output" "plugin_mode=normal"

reliable_output="$(run_dry reliable --lean)"
assert_contains "$reliable_output" "profile=reliable"
assert_contains "$reliable_output" "family=qwen"
assert_contains "$reliable_output" "context=65536"
assert_contains "$reliable_output" "remote_start=./start3.sh reliable"
assert_contains "$reliable_output" "plugin_mode=lean"
assert_contains "$reliable_output" '"plugin":[]'

resume_output="$(run_dry reliable --lean -s ses_test123)"
assert_contains "$resume_output" "session_id=ses_test123"
assert_contains "$resume_output" "opencode_args=-s ses_test123"

resume_long_output="$(run_dry qwen reliable --session ses_test456 --lean)"
assert_contains "$resume_long_output" "session_id=ses_test456"
assert_contains "$resume_long_output" "opencode_args=-s ses_test456"

qwen_reliable_output="$(run_dry qwen reliable --lean)"
assert_contains "$qwen_reliable_output" "family=qwen"
assert_contains "$qwen_reliable_output" "profile=reliable"
assert_contains "$qwen_reliable_output" "target=remote:ubt26"
assert_contains "$qwen_reliable_output" "remote_host=ubt26"
assert_contains "$qwen_reliable_output" "remote_start=./start3.sh reliable"
qwen_mtp_wrapper_info="$(OC_LOCAL_SCRIPT="$script" "$repo_root/scripts/oc-local" --info qwen reliable --lean)"
assert_contains "$qwen_mtp_wrapper_info" "model_name=qwen3.6-35b-a3b-mtp"
assert_contains "$qwen_mtp_wrapper_info" "hf_repo=unsloth/Qwen3.6-35B-A3B-MTP-GGUF"
assert_contains "$qwen_mtp_wrapper_info" "quant=Qwen3.6-35B-A3B-UD-IQ4_XS.gguf"
assert_contains "$qwen_mtp_wrapper_info" "batch=64"
assert_contains "$qwen_mtp_wrapper_info" "ngl=999"
assert_contains "$qwen_mtp_wrapper_info" "alias=qwen3.6-35b-a3b-mtp"
assert_contains "$qwen_mtp_wrapper_info" "mmproj=enabled"
assert_contains "$qwen_mtp_wrapper_info" "--hf-file Qwen3.6-35B-A3B-UD-IQ4_XS.gguf"
assert_contains "$qwen_mtp_wrapper_info" "--mmproj-auto"
assert_contains "$qwen_mtp_wrapper_info" "--chat-template-kwargs '{\"enable_thinking\":false}'"
assert_not_contains "$qwen_mtp_wrapper_info" "--reasoning off"

qwen_hauhau_info="$(run_info qwen-hauhau reliable --lean)"
assert_contains "$qwen_hauhau_info" "family=qwen-hauhau"
assert_contains "$qwen_hauhau_info" "model_name=qwen3.6-35b-a3b-hauhau"
assert_contains "$qwen_hauhau_info" "hf_repo=HauhauCS/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive"
assert_contains "$qwen_hauhau_info" "quant=Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-IQ4_XS.gguf"
assert_contains "$qwen_hauhau_info" "alias=qwen3.6-35b-a3b-hauhau"
assert_contains "$qwen_hauhau_info" "remote_start=./start11.sh reliable"
assert_contains "$qwen_hauhau_info" "mmproj=enabled"
assert_contains "$qwen_hauhau_info" "--hf-file Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-IQ4_XS.gguf"
assert_contains "$qwen_hauhau_info" "--mmproj-auto"
assert_contains "$qwen_hauhau_info" "--chat-template-kwargs '{\"enable_thinking\":false}'"
assert_not_contains "$qwen_hauhau_info" "--reasoning off"

qwen_27b_hauhau_info="$(run_info qwen-27b-hauhau reliable --lean)"
assert_contains "$qwen_27b_hauhau_info" "family=qwen-27b-hauhau"
assert_contains "$qwen_27b_hauhau_info" "model_name=qwen3.6-27b-hauhau"
assert_contains "$qwen_27b_hauhau_info" "hf_repo=HauhauCS/Qwen3.6-27B-Uncensored-HauhauCS-Aggressive"
assert_contains "$qwen_27b_hauhau_info" "alias=qwen3.6-27b-hauhau"
assert_contains "$qwen_27b_hauhau_info" "remote_start=./start12.sh reliable"
assert_contains "$qwen_27b_hauhau_info" "--chat-template-file /home/cass/llama.cpp/templates/qwen36-opencode.jinja"
assert_contains "$qwen_27b_hauhau_info" "--chat-template-kwargs '{\"enable_thinking\":false}'"

start12_contents="$(<"$repo_root/scripts/start12.sh")"
assert_contains "$start12_contents" "chat_template_file=\"\${llama_cpp_dir}/templates/qwen36-opencode.jinja\""
assert_contains "$start12_contents" "--chat-template-file \"\$chat_template_file\""
assert_contains "$start12_contents" "--chat-template-kwargs '{\"enable_thinking\":false}'"

if run_info glm-hauhau reliable --lean >/tmp/glm-hauhau-info 2>&1; then
  echo "expected glm-hauhau to be unavailable" >&2
  exit 1
fi

gemma_hauhau_info="$(run_info gemma-hauhau reliable --lean)"
assert_contains "$gemma_hauhau_info" "family=gemma-hauhau"
assert_contains "$gemma_hauhau_info" "model_name=gemma4-26b-a4b-hauhau"
assert_contains "$gemma_hauhau_info" "hf_repo=HauhauCS/Gemma4-26B-A4B-Uncensored-HauhauCS-Balanced"
assert_contains "$gemma_hauhau_info" "alias=gemma4-26b-a4b-hauhau"
assert_contains "$gemma_hauhau_info" "remote_start=./start14.sh reliable"

wrapper_tmp="$probe_tmp/wrappers"
mkdir -p "$wrapper_tmp"
ln -sf "$repo_root/scripts/oc-local" "$wrapper_tmp/oc-local"
ln -sf "$repo_root/scripts/lib.sh" "$wrapper_tmp/lib.sh"
ln -sf "$wrapper_tmp/oc-local" "$wrapper_tmp/oc-coder-reliable"
ln -sf "$wrapper_tmp/oc-local" "$wrapper_tmp/oc-qwen-coder-reliable"
ln -sf "$wrapper_tmp/oc-local" "$wrapper_tmp/oc-gemma-vision-reliable"
ln -sf "$wrapper_tmp/oc-local" "$wrapper_tmp/oc-deepseek-r1-reliable"

coder_wrapper_output="$(LOCAL_LLM_CONFIG_DIR="$repo_root/configs" "$wrapper_tmp/oc-coder-reliable" --dry-run --lean)"
assert_contains "$coder_wrapper_output" "qwen3-coder-30b-a3b-instruct"
assert_contains "$coder_wrapper_output" "--ctx-size 65536"

qwen_coder_wrapper_output="$(LOCAL_LLM_CONFIG_DIR="$repo_root/configs" "$wrapper_tmp/oc-qwen-coder-reliable" --dry-run --lean)"
assert_contains "$qwen_coder_wrapper_output" "qwen3-coder-30b-a3b-instruct"
assert_contains "$qwen_coder_wrapper_output" "--ctx-size 65536"

qwen_coder_wrapper_info="$(LOCAL_LLM_CONFIG_DIR="$repo_root/configs" "$wrapper_tmp/oc-qwen-coder-reliable" --info --lean)"
assert_contains "$qwen_coder_wrapper_info" "Profile: qwen-coder:reliable"

gemma_vision_wrapper_output="$(LOCAL_LLM_CONFIG_DIR="$repo_root/configs" "$wrapper_tmp/oc-gemma-vision-reliable" --dry-run --lean)"
assert_contains "$gemma_vision_wrapper_output" "gemma-4-31b-it-vision"
assert_contains "$gemma_vision_wrapper_output" "--ctx-size 32768"

deepseek_wrapper_output="$(LOCAL_LLM_CONFIG_DIR="$repo_root/configs" "$wrapper_tmp/oc-deepseek-r1-reliable" --dry-run --lean)"
assert_contains "$deepseek_wrapper_output" "deepseek-r1-distill-qwen-32b"
assert_contains "$deepseek_wrapper_output" "--ctx-size 65536"

default_target_host_output="$(OC_LOCAL_REMOTE_HOST=other-host run_info qwen reliable)"
assert_contains "$default_target_host_output" "target=remote:other-host"
assert_contains "$default_target_host_output" "remote_host=other-host"

default_target_override_output="$(OC_LOCAL_TARGET=local run_info qwen reliable)"
assert_contains "$default_target_override_output" "target=local"
assert_contains "$default_target_override_output" "target_kind=local"

local_target_info="$(run_info --target local qwen reliable)"
assert_contains "$local_target_info" "target=local"
assert_contains "$local_target_info" "target_kind=local"
assert_contains "$local_target_info" "remote_host="
assert_contains "$local_target_info" "remote_dir="
assert_contains "$local_target_info" "llama_dir=$HOME/llama.cpp"
assert_contains "$local_target_info" "base_url=http://127.0.0.1:8080/v1"

local_target_after_profile_info="$(run_info qwen reliable --target local)"
assert_contains "$local_target_after_profile_info" "target=local"
assert_contains "$local_target_after_profile_info" "target_kind=local"
assert_contains "$local_target_after_profile_info" "llama_dir=$HOME/llama.cpp"

remote_target_info="$(OC_LOCAL_REMOTE_DIR=/srv/llama run_info --target remote:test-host qwen reliable)"
assert_contains "$remote_target_info" "target=remote:test-host"
assert_contains "$remote_target_info" "target_kind=remote"
assert_contains "$remote_target_info" "remote_host=test-host"
assert_contains "$remote_target_info" "remote_dir=/srv/llama"
assert_contains "$remote_target_info" "llama_dir=/srv/llama"
assert_contains "$remote_target_info" "base_url=http://cass.lan:8080/v1"

remote_target_after_profile_info="$(OC_LOCAL_REMOTE_DIR=/srv/llama run_info qwen reliable --target remote:test-host)"
assert_contains "$remote_target_after_profile_info" "target=remote:test-host"
assert_contains "$remote_target_after_profile_info" "target_kind=remote"
assert_contains "$remote_target_after_profile_info" "remote_host=test-host"
assert_contains "$remote_target_after_profile_info" "remote_dir=/srv/llama"
assert_contains "$remote_target_after_profile_info" "llama_dir=/srv/llama"

local_target_dry="$(run_dry --target local qwen reliable)"
assert_contains "$local_target_dry" "target=local"
assert_contains "$local_target_dry" "target_kind=local"
assert_contains "$local_target_dry" "remote_host="
assert_contains "$local_target_dry" "remote_dir="
assert_contains "$local_target_dry" "llama_dir=$HOME/llama.cpp"

remote_target_before_profile_dry="$(OC_LOCAL_REMOTE_DIR=/srv/llama run_dry --target remote:test-host qwen reliable)"
assert_contains "$remote_target_before_profile_dry" "target=remote:test-host"
assert_contains "$remote_target_before_profile_dry" "target_kind=remote"
assert_contains "$remote_target_before_profile_dry" "remote_host=test-host"
assert_contains "$remote_target_before_profile_dry" "remote_dir=/srv/llama"
assert_contains "$remote_target_before_profile_dry" "llama_dir=/srv/llama"

local_target_after_profile_dry="$(run_dry qwen reliable --target local)"
assert_contains "$local_target_after_profile_dry" "target=local"
assert_contains "$local_target_after_profile_dry" "target_kind=local"
assert_contains "$local_target_after_profile_dry" "remote_host="
assert_contains "$local_target_after_profile_dry" "remote_dir="
assert_contains "$local_target_after_profile_dry" "llama_dir=$HOME/llama.cpp"

remote_target_after_profile_dry="$(OC_LOCAL_REMOTE_DIR=/srv/llama run_dry qwen reliable --target remote:test-host)"
assert_contains "$remote_target_after_profile_dry" "target=remote:test-host"
assert_contains "$remote_target_after_profile_dry" "target_kind=remote"
assert_contains "$remote_target_after_profile_dry" "remote_host=test-host"
assert_contains "$remote_target_after_profile_dry" "remote_dir=/srv/llama"
assert_contains "$remote_target_after_profile_dry" "llama_dir=/srv/llama"

gemma_reliable_output="$(run_dry gemma reliable --lean)"
assert_contains "$gemma_reliable_output" "family=gemma"
assert_contains "$gemma_reliable_output" "profile=reliable"
assert_contains "$gemma_reliable_output" "context=65536"
assert_contains "$gemma_reliable_output" "remote_start=./start4.sh reliable"
assert_contains "$gemma_reliable_output" "model=localllm/gemma-4-31b-it"
assert_contains "$gemma_reliable_output" '"gemma-4-31b-it":{"name":"gemma-4-31b-it"'
assert_contains "$gemma_reliable_output" "plugin_mode=lean"

gemma_vision_reliable_output="$(run_dry gemma-vision reliable --lean)"
assert_contains "$gemma_vision_reliable_output" "family=gemma-vision"
assert_contains "$gemma_vision_reliable_output" "profile=reliable"
assert_contains "$gemma_vision_reliable_output" "context=32768"
assert_contains "$gemma_vision_reliable_output" "remote_start=./start5.sh reliable"
assert_contains "$gemma_vision_reliable_output" "model=localllm/gemma-4-31b-it-vision"
assert_contains "$gemma_vision_reliable_output" '"gemma-4-31b-it-vision":{"name":"gemma-4-31b-it-vision"'
assert_contains "$gemma_vision_reliable_output" "plugin_mode=lean"

gemma_vision_info_output="$(run_info gemma-vision reliable --lean)"
assert_contains "$gemma_vision_info_output" "family=gemma-vision"
assert_contains "$gemma_vision_info_output" "profile=reliable"
assert_contains "$gemma_vision_info_output" "model=localllm/gemma-4-31b-it-vision"
assert_contains "$gemma_vision_info_output" "remote_start=./start5.sh reliable"
assert_contains "$gemma_vision_info_output" "hf_repo=unsloth/gemma-4-31B-it-GGUF"
assert_contains "$gemma_vision_info_output" "quant=UD-Q2_K_XL"
assert_contains "$gemma_vision_info_output" "ctx=32768"
assert_contains "$gemma_vision_info_output" "batch=64"
assert_contains "$gemma_vision_info_output" "ubatch=64"
assert_contains "$gemma_vision_info_output" "ngl=999"
assert_contains "$gemma_vision_info_output" "mmproj=enabled"
assert_contains "$gemma_vision_info_output" "alias=gemma-4-31b-it-vision"
assert_contains "$gemma_vision_info_output" "plugin_mode=lean"
assert_contains "$gemma_vision_info_output" "./build/bin/llama-server -hf unsloth/gemma-4-31B-it-GGUF:UD-Q2_K_XL"
assert_contains "$gemma_vision_info_output" "OPENCODE_CONFIG_CONTENT="

qwen_coder_reliable_output="$(run_dry qwen-coder reliable --lean)"
assert_contains "$qwen_coder_reliable_output" "family=qwen-coder"
assert_contains "$qwen_coder_reliable_output" "profile=reliable"
assert_contains "$qwen_coder_reliable_output" "context=65536"
assert_contains "$qwen_coder_reliable_output" "remote_start=./start2.sh reliable"
assert_contains "$qwen_coder_reliable_output" "model=localllm/qwen3-coder-30b-a3b-instruct"

qwen_coder_info_output="$(run_info qwen-coder reliable --lean)"
assert_contains "$qwen_coder_info_output" "family=qwen-coder"
assert_contains "$qwen_coder_info_output" "remote_start=./start2.sh reliable"
assert_contains "$qwen_coder_info_output" "hf_repo=unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF"
assert_contains "$qwen_coder_info_output" "quant=UD-Q3_K_XL"
assert_contains "$qwen_coder_info_output" "ctx=65536"
assert_contains "$qwen_coder_info_output" "batch=128"
assert_contains "$qwen_coder_info_output" "ubatch=128"
assert_contains "$qwen_coder_info_output" "ngl=999"
assert_contains "$qwen_coder_info_output" "alias=qwen3-coder-30b-a3b-instruct"
assert_contains "$qwen_coder_info_output" "command=./build/bin/llama-server -hf unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF:UD-Q3_K_XL"

gpt_oss_reliable_output="$(run_dry gpt-oss reliable --lean)"
assert_contains "$gpt_oss_reliable_output" "family=gpt-oss"
assert_contains "$gpt_oss_reliable_output" "profile=reliable"
assert_contains "$gpt_oss_reliable_output" "context=131072"
assert_contains "$gpt_oss_reliable_output" "remote_start=./start6.sh reliable"
assert_contains "$gpt_oss_reliable_output" "model=localllm/gpt-oss-20b"

gpt_oss_info_output="$(run_info gpt-oss reliable --lean)"
assert_contains "$gpt_oss_info_output" "family=gpt-oss"
assert_contains "$gpt_oss_info_output" "remote_start=./start6.sh reliable"
assert_contains "$gpt_oss_info_output" "hf_repo=unsloth/gpt-oss-20b-GGUF"
assert_contains "$gpt_oss_info_output" "quant=UD-Q8_K_XL"
assert_contains "$gpt_oss_info_output" "ctx=131072"
assert_contains "$gpt_oss_info_output" "batch=128"
assert_contains "$gpt_oss_info_output" "ubatch=128"
assert_contains "$gpt_oss_info_output" "ngl=999"
assert_contains "$gpt_oss_info_output" "reasoning_effort=high"
assert_contains "$gpt_oss_info_output" "output_limit=16384"
assert_contains "$gpt_oss_info_output" "alias=gpt-oss-20b"
assert_contains "$gpt_oss_info_output" "command=./build/bin/llama-server -hf unsloth/gpt-oss-20b-GGUF:UD-Q8_K_XL"
assert_contains "$gpt_oss_info_output" "--chat-template-kwargs '{\"reasoning_effort\":\"high\"}'"

gpt_oss_speed_info_output="$(run_info gpt-oss speed --lean)"
assert_contains "$gpt_oss_speed_info_output" "family=gpt-oss"
assert_contains "$gpt_oss_speed_info_output" "profile=speed"
assert_contains "$gpt_oss_speed_info_output" "ctx=131072"
assert_contains "$gpt_oss_speed_info_output" "batch=1024"
assert_contains "$gpt_oss_speed_info_output" "ubatch=1024"
assert_contains "$gpt_oss_speed_info_output" "reasoning_effort=medium"

gpt_oss_fastlong_info_output="$(run_info gpt-oss fastlong --lean)"
assert_contains "$gpt_oss_fastlong_info_output" "family=gpt-oss"
assert_contains "$gpt_oss_fastlong_info_output" "profile=fastlong"
assert_contains "$gpt_oss_fastlong_info_output" "reasoning_effort=medium"

gpt_oss_balanced_info_output="$(run_info gpt-oss balanced --lean)"
assert_contains "$gpt_oss_balanced_info_output" "family=gpt-oss"
assert_contains "$gpt_oss_balanced_info_output" "profile=balanced"
assert_contains "$gpt_oss_balanced_info_output" "reasoning_effort=high"

gpt_oss_tiny_info_output="$(run_info gpt-oss tiny --lean)"
assert_contains "$gpt_oss_tiny_info_output" "family=gpt-oss"
assert_contains "$gpt_oss_tiny_info_output" "profile=tiny"
assert_contains "$gpt_oss_tiny_info_output" "reasoning_effort=high"

deepseek_reliable_output="$(run_dry deepseek-r1 reliable --lean)"
assert_contains "$deepseek_reliable_output" "family=deepseek-r1"
assert_contains "$deepseek_reliable_output" "profile=reliable"
assert_contains "$deepseek_reliable_output" "context=16384"
assert_contains "$deepseek_reliable_output" "remote_start=./start7.sh reliable"
assert_contains "$deepseek_reliable_output" "model=localllm/deepseek-r1-distill-qwen-32b"

deepseek_info_output="$(run_info deepseek-r1 reliable --lean)"
assert_contains "$deepseek_info_output" "family=deepseek-r1"
assert_contains "$deepseek_info_output" "remote_start=./start7.sh reliable"
assert_contains "$deepseek_info_output" "hf_repo=unsloth/DeepSeek-R1-Distill-Qwen-32B-GGUF"
assert_contains "$deepseek_info_output" "quant=Q3_K_M"
assert_contains "$deepseek_info_output" "ctx=16384"
assert_contains "$deepseek_info_output" "batch=64"
assert_contains "$deepseek_info_output" "ubatch=64"
assert_contains "$deepseek_info_output" "ngl=999"
assert_contains "$deepseek_info_output" "output_limit=16384"
assert_contains "$deepseek_info_output" "alias=deepseek-r1-distill-qwen-32b"
assert_contains "$deepseek_info_output" "command=./build/bin/llama-server -hf unsloth/DeepSeek-R1-Distill-Qwen-32B-GGUF:Q3_K_M"
assert_not_contains "$deepseek_info_output" "--reasoning off"

qwen_27b_output="$(run_dry qwen-27b reliable --lean)"
assert_contains "$qwen_27b_output" "family=qwen-27b"
qwen_27b_mtp_wrapper_output="$(OC_LOCAL_SCRIPT="$script" "$repo_root/scripts/oc-local" --dry-run --lean qwen-27b reliable)"
assert_contains "$qwen_27b_mtp_wrapper_output" "family=qwen-27b"
assert_contains "$qwen_27b_output" "profile=reliable"
assert_contains "$qwen_27b_output" "context=65536"
assert_contains "$qwen_27b_output" "remote_start=./start8.sh reliable"
assert_contains "$qwen_27b_output" "model=localllm/qwen3.6-27b"

qwen_27b_info_output="$(run_info qwen-27b reliable --lean)"
assert_contains "$qwen_27b_info_output" "family=qwen-27b"
assert_contains "$qwen_27b_info_output" "remote_start=./start8.sh reliable"
assert_contains "$qwen_27b_info_output" "hf_repo=unsloth/Qwen3.6-27B-GGUF"
assert_contains "$qwen_27b_info_output" "quant=IQ4_XS"
assert_contains "$qwen_27b_info_output" "ctx=65536"
assert_contains "$qwen_27b_info_output" "batch=64"
assert_contains "$qwen_27b_info_output" "ubatch=64"
assert_contains "$qwen_27b_info_output" "ngl=999"
assert_contains "$qwen_27b_info_output" "output_limit=16384"
assert_contains "$qwen_27b_info_output" "alias=qwen3.6-27b"
assert_contains "$qwen_27b_info_output" "command=./build/bin/llama-server -hf unsloth/Qwen3.6-27B-GGUF:IQ4_XS"
assert_contains "$qwen_27b_info_output" "--no-mmproj"
assert_not_contains "$qwen_27b_info_output" "--reasoning off"

qwen_27b_speed_info_output="$(run_info qwen-27b speed --lean)"
assert_contains "$qwen_27b_speed_info_output" "family=qwen-27b"
assert_contains "$qwen_27b_speed_info_output" "profile=speed"
assert_contains "$qwen_27b_speed_info_output" "quant=IQ4_XS"
assert_contains "$qwen_27b_speed_info_output" "ctx=49152"
assert_contains "$qwen_27b_speed_info_output" "batch=128"
assert_contains "$qwen_27b_speed_info_output" "ubatch=128"

qwen_27b_tiny_info_output="$(run_info qwen-27b tiny --lean)"
assert_contains "$qwen_27b_tiny_info_output" "family=qwen-27b"
assert_contains "$qwen_27b_tiny_info_output" "profile=tiny"
assert_contains "$qwen_27b_tiny_info_output" "quant=UD-Q3_K_XL"
assert_contains "$qwen_27b_tiny_info_output" "ctx=98304"
assert_contains "$qwen_27b_tiny_info_output" "batch=64"
assert_contains "$qwen_27b_tiny_info_output" "ubatch=64"

qwen_27b_long_alias_output="$(OC_LOCAL_SCRIPT="$script" "$repo_root/scripts/oc-local" --info qwen-27b tiny --lean)"
assert_contains "$qwen_27b_long_alias_output" "ctx=98304"

resume_info_output="$(run_info gpt-oss speed --lean -s ses_test789)"
assert_contains "$resume_info_output" "session_id=ses_test789"
assert_contains "$resume_info_output" "opencode_args=-s ses_test789"

exec_no_session_output="$(OC_LOCAL_PRINT_EXEC=true OC_LOCAL_WAIT_SECONDS=1 run_dry qwen-27b speed --lean)"
assert_not_contains "$exec_no_session_output" "opencode_args=-s"

exec_session_output="$(OC_LOCAL_PRINT_EXEC=true OC_LOCAL_WAIT_SECONDS=1 run_dry qwen-27b speed --lean -s ses_test999)"
assert_contains "$exec_session_output" "session_id=ses_test999"
assert_contains "$exec_session_output" "opencode_args=-s ses_test999"

speed_output="$(run_dry speed)"
assert_contains "$speed_output" "context=32768"

balanced_output="$(run_dry balanced)"
assert_contains "$balanced_output" "context=49152"

invalid_output="$probe_tmp/oc-local-invalid.out"
if run_dry nope >"$invalid_output" 2>&1; then
  printf 'expected invalid profile to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$invalid_output")" "Usage:"

invalid_target_output="$probe_tmp/oc-local-invalid-target.out"
if run_info --target remote: qwen reliable >"$invalid_target_output" 2>&1; then
  printf 'expected invalid target to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$invalid_target_output")" "remote target requires a host"

runtime_tmp="$probe_tmp/local-runtime"
runtime_bin="$runtime_tmp/bin"
runtime_llama="$runtime_tmp/llama"
mkdir -p "$runtime_bin" "$runtime_llama"
local_info_output="$(OC_LOCAL_LLAMA_DIR="$runtime_llama" run_info --target local qwen reliable --lean)"
assert_line "$local_info_output" "llama_dir=$runtime_llama"
assert_line "$local_info_output" "remote_host="
assert_line "$local_info_output" "remote_dir="
local_dry_output="$(OC_LOCAL_LLAMA_DIR="$runtime_llama" run_dry --target local qwen reliable --lean)"
assert_line "$local_dry_output" "llama_dir=$runtime_llama"
assert_line "$local_dry_output" "remote_host="
assert_line "$local_dry_output" "remote_dir="
cat >"$runtime_bin/ssh" <<'EOF'
#!/usr/bin/env bash
printf 'ssh failure: local runtime must not use ssh\n' >&2
exit 1
EOF
cat >"$runtime_bin/curl" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
cat >"$runtime_bin/opencode" <<'EOF'
#!/usr/bin/env bash
printf 'opencode args:'
for arg in "$@"; do
  printf ' %s' "$arg"
done
printf '\n'
EOF
cat >"$runtime_bin/pkill" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
cat >"$runtime_llama/start3.sh" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$1" >start3.marker
exit 0
EOF
chmod +x "$runtime_bin/ssh" "$runtime_bin/curl" "$runtime_bin/opencode" "$runtime_bin/pkill" "$runtime_llama/start3.sh"
local_runtime_output="$(PATH="$runtime_bin:$PATH" OC_LOCAL_LLAMA_DIR="$runtime_llama" OC_LOCAL_WAIT_SECONDS=1 "$script" --target local qwen reliable --lean 2>&1)"
assert_contains "$local_runtime_output" "Restarting local llama.cpp qwen profile reliable"
assert_contains "$local_runtime_output" "opencode args: -m localllm/qwen3.6-35b-a3b"
assert_not_contains "$local_runtime_output" "ssh failure"
assert_contains "$(<"$runtime_llama/start3.marker")" "reliable"

start9_contents="$(<"$repo_root/scripts/start9.sh")"
assert_contains "$start9_contents" "Jackrong/Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled-GGUF"
assert_contains "$start9_contents" "--alias qwen3.5-27b-opus-reasoning"

start10_contents="$(<"$repo_root/scripts/start10.sh")"
assert_contains "$start10_contents" "DavidAU/Qwen3.6-27B-Heretic-Uncensored-FINETUNE-NEO-CODE-Di-IMatrix-MAX-GGUF"
assert_contains "$start10_contents" "chat_template_file=\"\${llama_cpp_dir}/templates/qwen36-opencode.jinja\""
assert_contains "$start10_contents" "--chat-template-file \"\$chat_template_file\""
assert_not_contains "$start10_contents" "--chat-template-file /home/cass/llama.cpp/templates/qwen36-opencode.jinja"
assert_contains "$start10_contents" "--alias qwen3.6-27b-heretic-code"

qwen_opus_output="$(run_dry qwen-opus reliable --lean)"
assert_contains "$qwen_opus_output" "family=qwen-opus"
assert_contains "$qwen_opus_output" "profile=reliable"
assert_contains "$qwen_opus_output" "context=65536"
assert_contains "$qwen_opus_output" "remote_start=./start9.sh reliable"
assert_contains "$qwen_opus_output" "model=localllm/qwen3.5-27b-opus-reasoning"

qwen_opus_info_output="$(run_info qwen-opus reliable --lean)"
assert_contains "$qwen_opus_info_output" "family=qwen-opus"
assert_contains "$qwen_opus_info_output" "remote_start=./start9.sh reliable"
assert_contains "$qwen_opus_info_output" "hf_repo=Jackrong/Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled-GGUF"
assert_contains "$qwen_opus_info_output" "quant=Qwen3.5-27B.Q3_K_M.gguf"
assert_contains "$qwen_opus_info_output" "ctx=65536"
assert_contains "$qwen_opus_info_output" "batch=64"
assert_contains "$qwen_opus_info_output" "ubatch=64"
assert_contains "$qwen_opus_info_output" "ngl=999"
assert_contains "$qwen_opus_info_output" "output_limit=16384"
assert_contains "$qwen_opus_info_output" "alias=qwen3.5-27b-opus-reasoning"
assert_contains "$qwen_opus_info_output" "command=./build/bin/llama-server -hf Jackrong/Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled-GGUF --hf-file Qwen3.5-27B.Q3_K_M.gguf"
assert_contains "$qwen_opus_info_output" "--no-mmproj"
assert_not_contains "$qwen_opus_info_output" "--reasoning off"

qwen_heretic_output="$(run_dry qwen-heretic reliable --lean)"
assert_contains "$qwen_heretic_output" "family=qwen-heretic"
assert_contains "$qwen_heretic_output" "profile=reliable"
assert_contains "$qwen_heretic_output" "context=65536"
assert_contains "$qwen_heretic_output" "remote_start=./start10.sh reliable"
assert_contains "$qwen_heretic_output" "model=localllm/qwen3.6-27b-heretic-code"

qwen_heretic_speed_info_output="$(run_info qwen-heretic speed --lean)"
assert_contains "$qwen_heretic_speed_info_output" "quant=Qwen3.6-27B-NEO-CODE-HERE-2T-OT-IQ4_XS.gguf"
assert_contains "$qwen_heretic_speed_info_output" "ctx=65536"
assert_contains "$qwen_heretic_speed_info_output" "batch=64"
assert_contains "$qwen_heretic_speed_info_output" "ubatch=64"
assert_contains "$qwen_heretic_speed_info_output" "--chat-template-kwargs '{\"enable_thinking\":false}'"

qwen_heretic_fastlong_info_output="$(run_info qwen-heretic fastlong --lean)"
assert_contains "$qwen_heretic_fastlong_info_output" "quant=Qwen3.6-27B-NEO-CODE-HERE-2T-OT-IQ3_M.gguf"
assert_contains "$qwen_heretic_fastlong_info_output" "ctx=98304"
assert_contains "$qwen_heretic_fastlong_info_output" "batch=64"
assert_contains "$qwen_heretic_fastlong_info_output" "ubatch=64"

qwen_heretic_tiny_info_output="$(run_info qwen-heretic tiny --lean)"
assert_contains "$qwen_heretic_tiny_info_output" "quant=Qwen3.6-27B-NEO-CODE-HERE-2T-OT-IQ2_M.gguf"
assert_contains "$qwen_heretic_tiny_info_output" "ctx=131072"
assert_contains "$qwen_heretic_tiny_info_output" "batch=64"
assert_contains "$qwen_heretic_tiny_info_output" "ubatch=64"

qwen_heretic_info_output="$(run_info qwen-heretic reliable --lean)"
assert_contains "$qwen_heretic_info_output" "family=qwen-heretic"
assert_contains "$qwen_heretic_info_output" "remote_start=./start10.sh reliable"
assert_contains "$qwen_heretic_info_output" "hf_repo=DavidAU/Qwen3.6-27B-Heretic-Uncensored-FINETUNE-NEO-CODE-Di-IMatrix-MAX-GGUF"
assert_contains "$qwen_heretic_info_output" "quant=Qwen3.6-27B-NEO-CODE-HERE-2T-OT-Q4_K_M.gguf"
assert_contains "$qwen_heretic_info_output" "ctx=65536"
assert_contains "$qwen_heretic_info_output" "batch=64"
assert_contains "$qwen_heretic_info_output" "ubatch=64"
assert_contains "$qwen_heretic_info_output" "ngl=999"
assert_contains "$qwen_heretic_info_output" "output_limit=16384"
assert_contains "$qwen_heretic_info_output" "alias=qwen3.6-27b-heretic-code"
assert_contains "$qwen_heretic_info_output" "command=./build/bin/llama-server -hf DavidAU/Qwen3.6-27B-Heretic-Uncensored-FINETUNE-NEO-CODE-Di-IMatrix-MAX-GGUF --hf-file Qwen3.6-27B-NEO-CODE-HERE-2T-OT-Q4_K_M.gguf"
assert_contains "$qwen_heretic_info_output" "--chat-template-file /home/cass/llama.cpp/templates/qwen36-opencode.jinja"
assert_contains "$qwen_heretic_info_output" "--no-mmproj"
assert_not_contains "$qwen_heretic_info_output" "--reasoning off"

printf 'oc-local dry-run tests passed\n'
