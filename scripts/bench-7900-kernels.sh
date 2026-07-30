#!/usr/bin/env bash
# bench-7900-kernels.sh - llama-bench sweep over backend x ubatch for the dual 7900 XT cluster.
# Runs on ubt26 (the GPU host).
#
# Answers: does ROCm beat Vulkan, and is the live -ub 512 leaving pp on the table.
#
# Usage:
#   ./bench-7900-kernels.sh                     # full sweep
#   ./bench-7900-kernels.sh --backends vulkan   # one backend
#   ./bench-7900-kernels.sh --ubatch 512,2048   # subset of ubatch sizes
#   ./bench-7900-kernels.sh --reps 5
#
# Stops the live runner container for the duration and restarts it on exit.

set -euo pipefail

MODEL="${BENCH_MODEL:-/home/cass/.cache/huggingface/hub/models--DavidAU--Qwen3.6-27B-Fable-Fusion-711-Uncensored-Heretic-NM-DAU-NEO-MAX-MTP-GGUF/snapshots/b73a29e861a1922ca7b508790c254c91158ec4bb/Qwen3.6-27B-Fable-Fus-711-UnHeretic-NM-DAU-NEO-MAX-NEO-MTP-Q8_0.gguf}"
LLAMA_DIR="${LLAMA_CPP_DIR:-$HOME/llama.cpp}"
RESULTS_DIR="${RESULTS_DIR:-$HOME/bench-results}"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
OUT="$RESULTS_DIR/7900-kernels-${TIMESTAMP}.jsonl"
LOG="$RESULTS_DIR/7900-kernels-${TIMESTAMP}.log"

# Model is 30 GB across 2x20 GB cards; 0.92 mirrors the live tensor-split.
TENSOR_SPLIT="${TENSOR_SPLIT:-1/0.92}"
CTX_BATCH=4096
PP_SIZES="2048,4096"
TG_SIZE=128
REPS=3
BACKENDS="vulkan,rocm"
UBATCHES="512,1024,2048"
SPLIT_MODES="layer"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --backends)
      BACKENDS="$2"
      shift 2
      ;;
    --ubatch)
      UBATCHES="$2"
      shift 2
      ;;
    --split-modes)
      SPLIT_MODES="$2"
      shift 2
      ;;
    --reps)
      REPS="$2"
      shift 2
      ;;
    --model)
      MODEL="$2"
      shift 2
      ;;
    -h | --help)
      sed -n '2,14p' "$0"
      exit 0
      ;;
    *)
      echo "unknown arg: $1" >&2
      exit 2
      ;;
  esac
done

[[ -f "$MODEL" ]] || {
  echo "model not found: $MODEL" >&2
  exit 1
}
mkdir -p "$RESULTS_DIR"

# The runner container owns ~18 GB on each card; nothing fits until it is gone.
RUNNER="$(docker ps --format '{{.Names}}' | grep '^local-llm-runner-cluster-' || true)"
restore_runner() {
  if [[ -n "$RUNNER" ]]; then
    echo "restarting $RUNNER" | tee -a "$LOG"
    docker start "$RUNNER" >/dev/null || echo "WARN: failed to restart $RUNNER" >&2
  fi
}
trap restore_runner EXIT

if [[ -n "$RUNNER" ]]; then
  echo "stopping $RUNNER for benchmark" | tee -a "$LOG"
  docker stop "$RUNNER" >/dev/null
  sleep 5
fi

run_backend() {
  local backend="$1" bin
  case "$backend" in
    vulkan) bin="$LLAMA_DIR/build-vulkan/bin/llama-bench" ;;
    rocm) bin="$LLAMA_DIR/build/bin/llama-bench" ;;
    *)
      echo "unknown backend: $backend" >&2
      return 1
      ;;
  esac
  [[ -x "$bin" ]] || {
    echo "SKIP $backend: no $bin" | tee -a "$LOG"
    return 0
  }

  echo "=== $backend (ub $UBATCHES, sm $SPLIT_MODES) ===" | tee -a "$LOG"
  # llama-bench expands the comma lists itself and reuses the loaded weights
  # across configs, so this is one model load per backend.
  GGML_VK_VISIBLE_DEVICES=0,1 HIP_VISIBLE_DEVICES=0,1 ROCR_VISIBLE_DEVICES=0,1 \
    "$bin" \
    -m "$MODEL" \
    -p "$PP_SIZES" -n "$TG_SIZE" \
    -b "$CTX_BATCH" -ub "$UBATCHES" \
    -ngl 999 -sm "$SPLIT_MODES" -ts "$TENSOR_SPLIT" -fa on \
    -r "$REPS" -o jsonl 2>>"$LOG" |
    sed "s/^{/{\"bench_backend\":\"$backend\",/" \
      >>"$OUT" || echo "FAILED $backend" | tee -a "$LOG"
}

IFS=',' read -ra BACKEND_LIST <<<"$BACKENDS"
for backend in "${BACKEND_LIST[@]}"; do
  run_backend "$backend"
done

echo
echo "results: $OUT"
echo "log:     $LOG"
python3 - "$OUT" <<'PY'
import json, sys
rows = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]
if not rows:
    sys.exit("no results")
print(f"{'backend':8} {'split':>7} {'ub':>6} {'test':>8} {'t/s':>9}")
for r in rows:
    test = f"pp{r['n_prompt']}" if r["n_prompt"] else f"tg{r['n_gen']}"
    print(f"{r['bench_backend']:8} {r['split_mode']:>7} {r['n_ubatch']:>6} {test:>8} {r['avg_ts']:>9.2f}")
PY
