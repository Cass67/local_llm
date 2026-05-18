#!/usr/bin/env bash
# Benchmark launcher for DavidAU Qwen3.6-27B Heretic Uncensored Finetune
# Follows add-discovered-model.md template
# Non-standard GGUF filenames → uses --hf-file approach

set -euo pipefail

# Model metadata
HF_REPO="DavidAU/Qwen3.6-27B-Heretic-Uncensored-FINETUNE-NEO-CODE-Di-IMatrix-MAX-GGUF"
ALIAS="qwen3.6-27b-heretic-code"

# Profile configurations
# Profile → (quant_file, ctx, batch, ubatch)
declare -A PROFILES=( 
  [speed]="Qwen3.6-27B-NEO-CODE-HERE-2T-OT-Q4_K_S.gguf|49152|128|128"
  [fastlong]="Qwen3.6-27B-NEO-CODE-HERE-2T-OT-Q4_K_S.gguf|49152|128|128"
  [balanced]="Qwen3.6-27B-NEO-CODE-HERE-2T-OT-Q4_K_S.gguf|49152|64|64"
  [reliable]="Qwen3.6-27B-NEO-CODE-HERE-2T-OT-Q4_K_M.gguf|32768|64|64"
  [tiny]="Qwen3.6-27B-NEO-CODE-HERE-2T-OT-IQ4_XS.gguf|65536|64|64"
)

# Common params (not a reasoning model → no --reasoning off)
common_params=(
  --no-mmproj
  --host 0.0.0.0
  --port 8080
  -ngl 999
  --flash-attn on
  -ub 128
  -b 128
  --threads "$(nproc)"
  --prio 2
  --no-warmup
  --temp 0.7
  --top-p 0.80
  --top-k 20
  --min-p 0.0
  --presence-penalty 1.5
  --repetition-penalty 1.0
  --alias "${ALIAS}"
)

show_usage() {
  echo "Usage: $0 <profile> [action]"
  echo "Profiles: speed, fastlong, balanced, reliable, tiny"
  echo "Actions: start (default), stop, status, info"
  echo ""
  echo "Example: $0 speed start"
}

run_server() {
  local profile="$1"
  [[ -n "${PROFILES[$profile]:-}" ]] || { echo "Unknown profile: $profile"; exit 1; }
  
  IFS='|' read -r hf_file ctx batch ubatch <<< "${PROFILES[$profile]}"
  
  echo "Starting ${HF_REPO}"
  echo "  Profile: ${profile}"
  echo "  Quant: ${hf_file}"
  echo "  Context: ${ctx}"
  echo "  Batch: ${batch}, ubatch: ${ubatch}"
  echo ""
  
  # First run downloads the GGUF via HF cache (~15-20 GB)
  nohup ./build/bin/llama-server \
    -hf "${HF_REPO}" \
    --hf-file "${hf_file}" \
    -c "${ctx}" \
    "${common_params[@]}" \
    &>"/tmp/bench-qwen-heretic-${profile}.log" &
  
  echo "Server PID: $!"
  echo "Log: /tmp/bench-qwen-heretic-${profile}.log"
  echo ""
  echo "Waiting for server to start (may take 2-10 min for first run - download)..."
  echo "Check download: du -sh ~/.cache/huggingface/hub/models--DavidAU--*/"
  echo "Check ready: curl -s http://localhost:8080/v1/models"
}

stop_server() {
  echo "Stopping llama-server..."
  pkill -f "llama-server.*${HF_REPO}" || true
  echo "Done."
}

show_status() {
  echo "Process:"
  pgrep -f "llama-server.*${HF_REPO}" && echo "Running" || echo "Not running"
  echo ""
  echo "Ready check:"
  curl -s http://localhost:8080/v1/models || echo "Not ready"
}

show_info() {
  echo "Model: ${HF_REPO}"
  echo "Alias: ${ALIAS}"
  echo "Vision: yes (mmproj-BF16.gguf available)"
  echo "Context: 256K native"
  echo ""
  echo "Available profiles:"
  for profile in "${!PROFILES[@]}"; do
    IFS='|' read -r hf_file ctx batch ubatch <<< "${PROFILES[$profile]}"
    echo "  ${profile}: ${hf_file} (ctx=${ctx}, b=${batch}, ub=${ubatch})"
  done
}

# Main
case "${1:-info}" in
  speed|fastlong|balanced|reliable|tiny)
    case "${2:-start}" in
      start) run_server "$1" ;;
      stop) stop_server ;;
      status) show_status ;;
      info) show_info ;;
      *) show_usage; exit 1 ;;
    esac
    ;;
  info) show_info ;;
  help|--help|-h) show_usage ;;
  *) show_usage; exit 1 ;;
esac
