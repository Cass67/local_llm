#!/usr/bin/env bash
set -euo pipefail

# EPOCHREALTIME honours LC_NUMERIC, and a comma decimal point would corrupt the
# microsecond arithmetic below.
export LC_NUMERIC=C

llama_cpp_dir="${LLAMA_CPP_DIR:-$HOME/llama.cpp}"
usage() {
  cat >&2 <<'EOF'
usage: bench-parallel-remote.sh [options]

Sweeps --parallel x continuous-batching under concurrent load and records
aggregate throughput vs per-stream latency.

Options:
  --model PATH            Local GGUF path (skips -hf download)
  --repo REPO             Hugging Face repository path (ignored if --model given)
  --hf-file FILE          Specific GGUF filename (ignored if --model given)
  --alias ALIAS           Model alias identifier for the API
  --extra-args "ARGS"     Extra llama-server flags, appended verbatim
                          (use to replicate a live profile: spec, KV type, jinja)
  --docker-image IMG      Run llama-server in this image instead of a host build
                          (matches how runner clusters actually execute)
  --docker-args "ARGS"    docker run flags: devices, env, mounts, network
  --ctx N                 TOTAL context, split across slots (default: 99500)
  --batch N               Batch size (default: 4096)
  --ubatch N              Micro-batch size (default: 256)
  --tensor-split SPEC     Tensor split (default: 1,1)
                          Note: -fa / KV type / spec flags come via --extra-args
  --parallel LIST         Comma-separated slot counts (default: 1,2,4)
  --concurrency LIST      Comma-separated in-flight request counts (default: 1,2,4)
  --n-predict N           Tokens to generate per request (default: 256)
  --prompt-repeat N       Code-block repeats per prompt, ~120 tok each (default: 8)

Env:
  LLAMA_PARALLEL_BENCH_PORT   Server port (default: 8080)
  LLAMA_PARALLEL_KILL_EXISTING=true   Kill a running llama-server first
  LLAMA_PARALLEL_APPEND=true          Append to existing results.tsv
EOF
}

model=''
extra_args=''
docker_image=''
docker_args=''
bench_container="${LLAMA_PARALLEL_CONTAINER:-local-llm-bench-parallel}"
repo='unsloth/Qwen3.6-35B-A3B-GGUF'
hf_file='Qwen3.6-35B-A3B-UD-Q6_K_XL.gguf'
alias='qwen3.6-35b-moe-q6'
ctx='99500'
batch='4096'
ubatch='256'
tensor_split='1,1'
parallel_list='1,2,4'
concurrency_list='1,2,4'
n_predict='256'
prompt_repeat='8'

while [[ $# -gt 0 ]]; do
  case "$1" in
    --model)
      model="${2:-}"
      shift 2
      ;;
    --extra-args)
      extra_args="${2:-}"
      shift 2
      ;;
    --docker-image)
      docker_image="${2:-}"
      shift 2
      ;;
    --docker-args)
      docker_args="${2:-}"
      shift 2
      ;;
    --repo)
      repo="${2:-}"
      shift 2
      ;;
    --hf-file)
      hf_file="${2:-}"
      shift 2
      ;;
    --alias)
      alias="${2:-}"
      shift 2
      ;;
    --ctx)
      ctx="${2:-}"
      shift 2
      ;;
    --batch)
      batch="${2:-}"
      shift 2
      ;;
    --ubatch)
      ubatch="${2:-}"
      shift 2
      ;;
    --tensor-split)
      tensor_split="${2:-}"
      shift 2
      ;;
    --parallel)
      parallel_list="${2:-}"
      shift 2
      ;;
    --concurrency)
      concurrency_list="${2:-}"
      shift 2
      ;;
    --n-predict)
      n_predict="${2:-}"
      shift 2
      ;;
    --prompt-repeat)
      prompt_repeat="${2:-}"
      shift 2
      ;;
    --help | -h)
      usage
      exit 0
      ;;
    *)
      printf 'unknown option: %s\n' "$1" >&2
      usage
      exit 2
      ;;
  esac
done

if [[ -z "$alias" ]] || [[ -z "$model" && (-z "$repo" || -z "$hf_file") ]]; then
  usage
  exit 2
fi

if [[ -n "$model" ]]; then
  model_flags=(-m "$model")
else
  model_flags=(-hf "$repo" --hf-file "$hf_file" --no-mmproj)
fi

read -r -a extra_flags <<<"$extra_args"
read -r -a docker_flags <<<"$docker_args"

results_dir="bench-parallel"
run_id="${LLAMA_PARALLEL_RUN_ID:-$(date +%Y%m%d-%H%M%S)}"
logs_dir="$results_dir/logs/$run_id"
results_tsv="$results_dir/results.tsv"
port="${LLAMA_PARALLEL_BENCH_PORT:-8080}"
server_pid=""

cd "$llama_cpp_dir"
mkdir -p "$logs_dir"

header='parallel	cont_batching	concurrency	ctx_per_slot	status	prompt_n	pred_n	accept	agg_pp_tok_s	agg_tg_tok_s	tg_min	tg_med	tg_max	ttft_ms_med	e2e_med_ms	e2e_max_ms	wall_ms	reason'
if [[ "${LLAMA_PARALLEL_APPEND:-false}" != true || ! -e "$results_tsv" ]]; then
  printf '%s\n' "$header" >"$results_tsv"
fi

stop_server() {
  if [[ -n "$docker_image" ]]; then
    docker rm -f "$bench_container" >/dev/null 2>&1 || true
    sleep 3
    return
  fi
  if [[ -n "$server_pid" ]] && kill -0 "$server_pid" >/dev/null 2>&1; then
    kill "$server_pid" >/dev/null 2>&1 || true
    wait "$server_pid" >/dev/null 2>&1 || true
  fi
  sleep 3
  server_pid=""
}

# Container logs live in the docker daemon, so refresh the on-disk copy before
# anything greps it.
refresh_log() {
  local log_file="$1"
  if [[ -n "$docker_image" ]]; then
    docker logs "$bench_container" >"$log_file" 2>&1 || true
  fi
}

clear_existing_servers() {
  if ! pgrep -f '[l]lama-server' >/dev/null 2>&1; then
    return
  fi

  if [[ "${LLAMA_PARALLEL_KILL_EXISTING:-false}" == true ]]; then
    pkill -f '[l]lama-server' >/dev/null 2>&1 || true
    sleep 5
    return
  fi

  printf '%s\n' 'Refusing to start: existing llama-server process found. Stop it first or set LLAMA_PARALLEL_KILL_EXISTING=true.' >&2
  exit 1
}

# Distinct prefix per stream so slots cannot share a cached prefix, which is
# what separate agents actually look like.
build_prompt_file() {
  local stream="$1"
  local out="$2"
  local i
  {
    printf 'Session %s. You are reviewing an unfamiliar service.\n\n' "$stream"
    for ((i = 0; i < prompt_repeat; i++)); do
      printf 'class Handler%d_%s:\n' "$i" "$stream"
      printf '    def __init__(self, pool, clock, retries=3):\n'
      printf '        self.pool = pool\n        self.clock = clock\n        self.retries = retries\n'
      printf '    def dispatch(self, req):\n'
      printf '        token = self.pool.acquire(req.tenant)\n'
      printf '        if token is None:\n            raise Backpressure(req.tenant)\n'
      printf '        return self._send(req, token, deadline=self.clock.now() + 30)\n\n'
    done
    printf 'Write a thorough review of the code above, at least 600 words, as numbered\n'
    printf 'sections covering: retry semantics, backpressure, deadline propagation,\n'
    printf 'tenant isolation, and testing strategy. Be specific and detailed.\n'
  } >"$out"
}

start_server() {
  local parallel="$1"
  local cont_batching="$2"
  local log_file="$3"
  local ready=false
  local iteration

  local cont_flag=()
  if [[ "$cont_batching" == off ]]; then
    cont_flag=(--no-cont-batching)
  fi

  stop_server
  : >"$log_file"

  printf 'BOOT parallel=%s cont_batching=%s ctx_per_slot=%s\n' \
    "$parallel" "$cont_batching" "$((ctx / parallel))"

  local server_args=(
    "${model_flags[@]}"
    --host 127.0.0.1
    --port "$port"
    -ngl 999
    --tensor-split "$tensor_split"
    -c "$ctx"
    -b "$batch"
    -ub "$ubatch"
    --parallel "$parallel"
    "${cont_flag[@]}"
    --threads 4
    --threads-batch 4
    --threads-http "$((parallel + 1))"
    --prio 2
    --no-warmup
    --alias "$alias"
    "${extra_flags[@]}"
  )

  if [[ -n "$docker_image" ]]; then
    docker run -d --name "$bench_container" \
      "${docker_flags[@]}" \
      "$docker_image" \
      llama-server "${server_args[@]}" \
      >/dev/null 2>>"$log_file"
  else
    ./build/bin/llama-server "${server_args[@]}" >>"$log_file" 2>&1 &
    server_pid="$!"
  fi

  for ((iteration = 1; iteration <= 240; iteration++)); do
    if curl -fsS --max-time 5 "http://127.0.0.1:$port/v1/models" 2>/dev/null | grep -q "$alias"; then
      ready=true
      break
    fi
    if [[ -n "$docker_image" ]]; then
      if [[ "$(docker inspect -f '{{.State.Running}}' "$bench_container" 2>/dev/null)" != true ]]; then
        break
      fi
    elif ! kill -0 "$server_pid" >/dev/null 2>&1; then
      break
    fi
    sleep 2
  done

  refresh_log "$log_file"

  [[ "$ready" == true ]]
}

run_load() {
  local parallel="$1"
  local cont_batching="$2"
  local concurrency="$3"
  local log_file="$4"
  local tag="p${parallel}-cb${cont_batching}-c${concurrency}"
  local status="success"
  local reason=""
  local stream pid pids wall_start wall_end wall_ms
  local ctx_per_slot=$((ctx / parallel))

  printf 'START %s\n' "$tag"

  # Build every request body first so jq/file I/O stays out of the timed window.
  for ((stream = 1; stream <= concurrency; stream++)); do
    build_prompt_file "$tag-$stream" "$logs_dir/$tag-$stream.prompt.txt"
    # A long-form instruction reaches max_tokens on its own. ignore_eos would
    # instead push the model past EOS into repetitive babble, which ngram-mod
    # accelerates wildly and makes tok/s incomparable between cells.
    jq -Rs --argjson n "$n_predict" --arg model "$alias" \
      '{model: $model, messages: [{role: "user", content: .}],
        max_tokens: $n, temperature: 0, cache_prompt: true}' \
      <"$logs_dir/$tag-$stream.prompt.txt" >"$logs_dir/$tag-$stream.request.json"
  done

  pids=()
  wall_start="${EPOCHREALTIME/./}"
  for ((stream = 1; stream <= concurrency; stream++)); do
    curl -fsS --max-time 900 "http://127.0.0.1:$port/v1/chat/completions" \
      -H 'Content-Type: application/json' \
      --data-binary "@$logs_dir/$tag-$stream.request.json" \
      -o "$logs_dir/$tag-$stream.response.json" \
      -w '%{time_total}' >"$logs_dir/$tag-$stream.e2e.txt" 2>>"$log_file" &
    pids+=("$!")
  done

  for pid in "${pids[@]}"; do
    if ! wait "$pid"; then
      status="error"
      reason="a request failed"
    fi
  done
  wall_end="${EPOCHREALTIME/./}"
  wall_ms=$(((wall_end - wall_start) / 1000))

  refresh_log "$log_file"
  if grep -Eiq 'hipMalloc failed|out of memory|OOM|cannot allocate memory|std::bad_alloc|CUDA_ERROR_OUT_OF_MEMORY' "$log_file"; then
    status="oom"
    reason="OOM detected"
  fi

  # Aggregate throughput is wall-clock based; per-stream numbers come from the
  # server's own timings block in each response.
  python3 - "$parallel" "$cont_batching" "$concurrency" "$ctx_per_slot" "$status" \
    "$wall_ms" "$reason" "$logs_dir/$tag" <<'PY' >>"$results_tsv"
import glob
import json
import statistics
import sys

parallel, cont, conc, ctx_slot, status, wall_ms, reason, prefix = sys.argv[1:9]
wall = int(wall_ms)

prompt_n = []
pred_n = []
tg = []
prompt_ms = []
draft_n = 0
draft_ok = 0
e2e = []
for path in sorted(glob.glob(f"{prefix}-*.response.json")):
    try:
        with open(path) as fh:
            t = json.load(fh)["timings"]
    except Exception:
        status = status if status != "success" else "error"
        reason = reason or f"unparseable response {path}"
        continue
    prompt_n.append(t["prompt_n"])
    pred_n.append(t["predicted_n"])
    tg.append(t["predicted_per_second"])
    prompt_ms.append(t["prompt_ms"])
    draft_n += t.get("draft_n", 0)
    draft_ok += t.get("draft_n_accepted", 0)

# Client-side latency is what an agent actually waits: it includes queue time,
# which the server's own prompt_ms deliberately excludes.
for path in sorted(glob.glob(f"{prefix}-*.e2e.txt")):
    try:
        with open(path) as fh:
            e2e.append(float(fh.read().strip()) * 1000)
    except Exception:
        pass


def fmt(v):
    return f"{v:.2f}" if isinstance(v, float) else str(v)


if tg and wall > 0:
    row = [
        parallel, cont, conc, ctx_slot, status,
        str(round(statistics.median(prompt_n))),
        str(round(statistics.median(pred_n))),
        fmt(draft_ok / draft_n) if draft_n else "",
        fmt(sum(prompt_n) / (wall / 1000)),
        fmt(sum(pred_n) / (wall / 1000)),
        fmt(min(tg)), fmt(statistics.median(tg)), fmt(max(tg)),
        fmt(statistics.median(prompt_ms)),
        fmt(statistics.median(e2e)) if e2e else "",
        fmt(max(e2e)) if e2e else "",
        str(wall), reason,
    ]
else:
    row = [parallel, cont, conc, ctx_slot, status] + [""] * 11 + [str(wall), reason]

print("\t".join(row))
PY

  printf 'END %s status=%s wall_ms=%s\n' "$tag" "$status" "$wall_ms"
  tail -n 1 "$results_tsv"
}

trap stop_server EXIT

command -v jq >/dev/null || {
  printf 'jq is required\n' >&2
  exit 1
}

clear_existing_servers
stop_server
printf 'RUN run_id=%s results=%s logs=%s\n' "$run_id" "$results_tsv" "$logs_dir"

IFS=',' read -r -a parallels <<<"$parallel_list"
IFS=',' read -r -a concurrencies <<<"$concurrency_list"

for parallel in "${parallels[@]}"; do
  for cont_batching in off on; do
    log_file="$logs_dir/p${parallel}-cb${cont_batching}.log"
    if ! start_server "$parallel" "$cont_batching" "$log_file"; then
      for concurrency in "${concurrencies[@]}"; do
        printf '%s\t%s\t%s\t%s\ttimeout\t\t\t\t\t\t\t\t\t\t\t\t\tserver did not become ready\n' \
          "$parallel" "$cont_batching" "$concurrency" "$((ctx / parallel))" >>"$results_tsv"
      done
      printf 'BOOT FAILED parallel=%s cont_batching=%s\n' "$parallel" "$cont_batching"
      continue
    fi
    for concurrency in "${concurrencies[@]}"; do
      run_load "$parallel" "$cont_batching" "$concurrency" "$log_file"
    done
    stop_server
  done
done

printf '\n=== %s ===\n' "$results_tsv"
column -t -s$'\t' "$results_tsv"
