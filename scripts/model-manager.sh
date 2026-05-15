#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
runs_dir="${LOCAL_LLM_RUNS_DIR:-$repo_root/runs}"

usage() {
    cat <<'EOF'
Usage: model-manager <command> [options]

Commands:
  discover   Find candidate models
  select     Select a candidate model
  benchmark  Benchmark a selected model
  accept     Accept benchmark results
  status     Show model-manager status

Options:
  -h, --help  Show this help
EOF
    printf '\nRepository: %s\n' "$repo_root"
}

not_implemented() {
    local command_name="$1"
    printf 'model-manager %s: not implemented yet\n' "$command_name" >&2
    return 1
}

ensure_runs_dirs() {
    mkdir -p "$runs_dir/candidates" "$runs_dir/selections" "$runs_dir/benchmarks"
}

count_json_files() {
    local dir="$1"
    local -a files=()

    if [[ -d "$dir" ]]; then
        shopt -s nullglob
        files=("$dir"/*.json)
        shopt -u nullglob
    fi

    printf '%s\n' "${#files[@]}"
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

cmd_discover() {
    local target="remote:${OC_LOCAL_REMOTE_HOST:-ubt26}"
    local query='GGUF'
    local limit=8
    local json=false

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --target)
                if [[ $# -lt 2 ]]; then
                    printf '%s\n' '--target requires local or remote:<host>' >&2
                    return 2
                fi
                target="$2"
                shift 2
                ;;
            --query)
                if [[ $# -lt 2 ]]; then
                    printf '%s\n' '--query requires text' >&2
                    return 2
                fi
                query="$2"
                shift 2
                ;;
            --limit)
                if [[ $# -lt 2 ]]; then
                    printf '%s\n' '--limit requires a number' >&2
                    return 2
                fi
                limit="$2"
                shift 2
                ;;
            --json)
                json=true
                shift
                ;;
            -h|--help)
                usage
                return 0
                ;;
            *)
                printf 'Unknown discover option: %s\n' "$1" >&2
                return 2
                ;;
        esac
    done

    case "$limit" in
        ''|*[!0-9]*)
            printf 'invalid limit: %s\n' "$limit" >&2
            return 2
            ;;
    esac

    case "$target" in
        local)
            ;;
        remote:*)
            if [[ -z "${target#remote:}" ]]; then
                printf 'remote target requires a host: %s\n' "$target" >&2
                return 2
            fi
            ;;
        *)
            printf 'invalid target: %s\n' "$target" >&2
            printf 'expected local or remote:<host>\n' >&2
            return 2
            ;;
    esac

    if [[ "$json" == true ]]; then
        python3 - "$target" "$query" "$limit" <<'PY'
import json
import sys

target, query, limit = sys.argv[1], sys.argv[2], int(sys.argv[3])
print(json.dumps({"target": target, "query": query, "limit": limit}, separators=(",", ":")))
PY
        return 0
    fi

    case "$target" in
        local)
            "$repo_root/scripts/model-discovery.sh" --local --query "$query" --limit "$limit"
            ;;
        remote:*)
            "$repo_root/scripts/model-discovery.sh" --host "${target#remote:}" --query "$query" --limit "$limit"
            ;;
    esac
}

cmd_select() {
    local target="remote:${OC_LOCAL_REMOTE_HOST:-ubt26}"
    local repo=''
    local family=''
    local alias=''
    local purpose=''

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --target)
                if [[ $# -lt 2 ]]; then
                    printf '%s\n' '--target requires local or remote:<host>' >&2
                    return 2
                fi
                target="$2"
                shift 2
                ;;
            --repo)
                if [[ $# -lt 2 ]]; then
                    printf '%s\n' '--repo requires a value' >&2
                    return 2
                fi
                repo="$2"
                shift 2
                ;;
            --family)
                if [[ $# -lt 2 ]]; then
                    printf '%s\n' '--family requires a value' >&2
                    return 2
                fi
                family="$2"
                shift 2
                ;;
            --alias)
                if [[ $# -lt 2 ]]; then
                    printf '%s\n' '--alias requires a value' >&2
                    return 2
                fi
                alias="$2"
                shift 2
                ;;
            --purpose)
                if [[ $# -lt 2 ]]; then
                    printf '%s\n' '--purpose requires a value' >&2
                    return 2
                fi
                purpose="$2"
                shift 2
                ;;
            -h|--help)
                usage
                return 0
                ;;
            *)
                printf 'Unknown select option: %s\n' "$1" >&2
                return 2
                ;;
        esac
    done

    if [[ -z "$repo" ]]; then
        printf '%s\n' 'select requires --repo' >&2
        return 2
    fi
    if [[ -z "$family" ]]; then
        printf '%s\n' 'select requires --family' >&2
        return 2
    fi
    if [[ -z "$alias" ]]; then
        printf '%s\n' 'select requires --alias' >&2
        return 2
    fi

    case "$target" in
        local)
            ;;
        remote:*)
            if [[ -z "${target#remote:}" ]]; then
                printf 'remote target requires a host: %s\n' "$target" >&2
                return 2
            fi
            ;;
        *)
            printf 'invalid target: %s\n' "$target" >&2
            printf 'expected local or remote:<host>\n' >&2
            return 2
            ;;
    esac

    if ! command -v python3 >/dev/null 2>&1; then
        printf '%s\n' 'python3 is required for selection JSON' >&2
        return 1
    fi

    ensure_runs_dirs
    local timestamp
    local safe_family
    local output_file
    local unique_suffix
    timestamp="$(date +%Y%m%d-%H%M%S)"
    safe_family="${family//[^A-Za-z0-9_.-]/-}"
    unique_suffix="$$"
    output_file="$runs_dir/selections/${timestamp}-${safe_family}-${unique_suffix}.json"
    while [[ -e "$output_file" ]]; do
        unique_suffix="${unique_suffix}x"
        output_file="$runs_dir/selections/${timestamp}-${safe_family}-${unique_suffix}.json"
    done

    python3 - "$output_file" "$repo" "$family" "$alias" "$target" "$purpose" <<'PY'
import json
import sys

output_file, repo, family, alias, target, purpose = sys.argv[1:]
selection = {"repo": repo, "family": family, "alias": alias, "target": target}
if purpose:
    selection["purpose"] = purpose
with open(output_file, "w", encoding="utf-8") as handle:
    json.dump(selection, handle, separators=(",", ":"))
    handle.write("\n")
PY

    printf 'Selected %s\n' "$repo"
    printf 'Wrote selection: %s\n' "$output_file"
}

cmd_benchmark() {
    local target="remote:${OC_LOCAL_REMOTE_HOST:-ubt26}"
    local repo=''
    local family=''
    local alias=''
    local profiles='reliable'
    local -a profile_list=()
    local dry_run=false
    local record_only=false

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --target)
                if [[ $# -lt 2 ]]; then
                    printf '%s\n' '--target requires local or remote:<host>' >&2
                    return 2
                fi
                target="$2"
                shift 2
                ;;
            --repo)
                if [[ $# -lt 2 ]]; then
                    printf '%s\n' '--repo requires a value' >&2
                    return 2
                fi
                repo="$2"
                shift 2
                ;;
            --family)
                if [[ $# -lt 2 ]]; then
                    printf '%s\n' '--family requires a value' >&2
                    return 2
                fi
                family="$2"
                shift 2
                ;;
            --alias)
                if [[ $# -lt 2 ]]; then
                    printf '%s\n' '--alias requires a value' >&2
                    return 2
                fi
                alias="$2"
                shift 2
                ;;
            --profiles)
                if [[ $# -lt 2 || -z "$2" || "$2" == --* ]]; then
                    printf '%s\n' '--profiles requires a non-empty value' >&2
                    return 2
                fi
                profiles="$2"
                shift 2
                ;;
            --dry-run)
                dry_run=true
                shift
                ;;
            --record-only)
                record_only=true
                shift
                ;;
            -h|--help)
                usage
                return 0
                ;;
            *)
                printf 'Unknown benchmark option: %s\n' "$1" >&2
                return 2
                ;;
        esac
    done

    if [[ -z "$repo" ]]; then
        printf '%s\n' 'benchmark requires --repo' >&2
        return 2
    fi
    if [[ -z "$family" ]]; then
        printf '%s\n' 'benchmark requires --family' >&2
        return 2
    fi
    if [[ -z "$alias" ]]; then
        printf '%s\n' 'benchmark requires --alias' >&2
        return 2
    fi

    ensure_runs_dirs

    case "$profiles" in
        ,*|*,|*,,*)
            printf '%s\n' '--profiles contains an empty profile' >&2
            return 2
            ;;
    esac

    IFS=, read -r -a profile_list <<<"$profiles"
    local profile
    for profile in "${profile_list[@]}"; do
        if [[ -z "$profile" ]]; then
            printf '%s\n' '--profiles contains an empty profile' >&2
            return 2
        fi
        case "$profile" in
            *[!A-Za-z0-9_.-]*)
                printf 'invalid benchmark profile: %s\n' "$profile" >&2
                return 2
                ;;
        esac
    done

    case "$target" in
        local)
            ;;
        remote:*)
            if [[ -z "${target#remote:}" ]]; then
                printf 'remote target requires a host: %s\n' "$target" >&2
                return 2
            fi
            ;;
        *)
            printf 'invalid target: %s\n' "$target" >&2
            printf 'expected local or remote:<host>\n' >&2
            return 2
            ;;
    esac

    if [[ "$dry_run" != true && "$record_only" != true ]]; then
        printf '%s\n' 'benchmark currently supports --dry-run only' >&2
        return 2
    fi

    if [[ "$record_only" == true ]]; then
        if ! command -v python3 >/dev/null 2>&1; then
            printf '%s\n' 'python3 is required for benchmark JSON' >&2
            return 1
        fi

        local timestamp
        local result_timestamp
        local safe_family
        local safe_profile
        local output_file
        local unique_suffix
        timestamp="$(date +%Y%m%d-%H%M%S)"
        result_timestamp="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        safe_family="${family//[^A-Za-z0-9_.-]/-}"
        for profile in "${profile_list[@]}"; do
            safe_profile="${profile//[^A-Za-z0-9_.-]/-}"
            unique_suffix="$$"
            output_file="$runs_dir/benchmarks/${timestamp}-${safe_family}-${safe_profile}-${unique_suffix}.json"
            while [[ -e "$output_file" ]]; do
                unique_suffix="${unique_suffix}x"
                output_file="$runs_dir/benchmarks/${timestamp}-${safe_family}-${safe_profile}-${unique_suffix}.json"
            done

            python3 - "$output_file" "$target" "$repo" "$family" "$alias" "$profile" "$result_timestamp" <<'PY'
import json
import sys

output_file, target, repo, family, alias, profile, timestamp = sys.argv[1:]
result = {
    "target": target,
    "repo": repo,
    "family": family,
    "alias": alias,
    "profile": profile,
    "ctx": None,
    "batch": None,
    "ubatch": None,
    "ngl": None,
    "load_status": "not_run",
    "prompt_tok_s": None,
    "decode_tok_s": None,
    "command": "",
    "timestamp": timestamp,
}
with open(output_file, "w", encoding="utf-8") as handle:
    json.dump(result, handle, separators=(",", ":"))
    handle.write("\n")
PY

            printf 'Wrote benchmark result: %s\n' "$output_file"
        done
        return 0
    fi

    printf 'Benchmark plan\n'
    printf 'repo=%s\n' "$repo"
    printf 'family=%s\n' "$family"
    printf 'alias=%s\n' "$alias"
    printf 'profiles=%s\n' "$profiles"
    printf 'target=%s\n' "$target"
}

cmd_accept() {
    local benchmark_file=''
    local dry_run=false
    local json_fields
    local repo
    local family
    local alias
    local target
    local profile
    local start_script
    local max_start=0
    local start_path
    local start_name
    local start_number
    local start_value

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --dry-run)
                dry_run=true
                shift
                ;;
            -h|--help)
                usage
                return 0
                ;;
            --*)
                printf 'Unknown accept option: %s\n' "$1" >&2
                return 2
                ;;
            *)
                if [[ -n "$benchmark_file" ]]; then
                    printf 'accept accepts one benchmark JSON file, got extra argument: %s\n' "$1" >&2
                    return 2
                fi
                benchmark_file="$1"
                shift
                ;;
        esac
    done

    if [[ -z "$benchmark_file" ]]; then
        printf '%s\n' 'accept requires a benchmark JSON file' >&2
        return 2
    fi

    if [[ "$dry_run" != true ]]; then
        printf '%s\n' 'accept currently supports --dry-run only' >&2
        return 2
    fi

    if ! command -v python3 >/dev/null 2>&1; then
        printf '%s\n' 'python3 is required to parse benchmark JSON' >&2
        return 1
    fi

    if ! json_fields="$(python3 - "$benchmark_file" <<'PY'
import json
import os
import sys

path = sys.argv[1]
if not os.path.exists(path):
    raise SystemExit(f"benchmark JSON not found: {path}")
if not os.path.isfile(path):
    raise SystemExit(f"benchmark JSON is not a file: {path}")
try:
    with open(path, encoding="utf-8") as handle:
        result = json.load(handle)
except OSError as exc:
    raise SystemExit(f"benchmark JSON is unreadable: {path}: {exc}") from exc
except json.JSONDecodeError as exc:
    raise SystemExit(f"benchmark JSON is invalid: {path}: {exc}") from exc

if not isinstance(result, dict):
    raise SystemExit("benchmark JSON must be an object")

required = ("repo", "family", "alias", "target", "profile", "load_status")
for key in required:
    if key not in result:
        raise SystemExit(f"benchmark JSON missing required field: {key}")
    if not isinstance(result[key], str):
        raise SystemExit(f"benchmark JSON field must be a string: {key}")
    if any(ord(char) < 32 or ord(char) == 127 for char in result[key]):
        raise SystemExit(f"benchmark JSON field contains a control character: {key}")

if result["load_status"] != "success":
    raise SystemExit(f"benchmark JSON load_status is not success: {result['load_status']}")
print("\t".join(result[key] for key in required[:-1]))
PY
)"; then
        return 1
    fi

    IFS=$'\t' read -r repo family alias target profile <<<"$json_fields"

    shopt -s nullglob
    for start_path in "$repo_root"/scripts/start*.sh; do
        start_name="${start_path##*/}"
        start_number="${start_name#start}"
        start_number="${start_number%.sh}"
        if [[ -n "$start_number" && "$start_number" != *[!0-9]* ]]; then
            start_value=$((10#$start_number))
            if (( start_value > max_start )); then
                max_start="$start_value"
            fi
        fi
    done
    shopt -u nullglob
    start_script="scripts/start$((max_start + 1)).sh"

    printf 'Accept plan\n'
    printf 'repo=%s\n' "$repo"
    printf 'family=%s\n' "$family"
    printf 'alias=%s\n' "$alias"
    printf 'target=%s\n' "$target"
    printf 'profile=%s\n' "$profile"
    printf 'Dry-run actions:\n'
    printf 'would create %s\n' "$start_script"
    printf 'would update scripts/oc-local\n'
    printf 'would update installer.sh\n'
    printf 'would update README.md\n'
    printf 'would update test_oc_local.sh\n'
}

main() {
    local command_name="${1:-}"

    case "$command_name" in
        -h|--help|'')
            usage
            ;;
        status)
            cmd_status
            ;;
        discover)
            cmd_discover "${@:2}"
            ;;
        select)
            cmd_select "${@:2}"
            ;;
        benchmark)
            cmd_benchmark "${@:2}"
            ;;
        accept)
            cmd_accept "${@:2}"
            ;;
        *)
            printf 'Unknown command: %s\n\n' "$command_name" >&2
            usage >&2
            return 1
            ;;
    esac
}

main "$@"
