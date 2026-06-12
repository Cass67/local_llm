#!/usr/bin/env bash
# bench-ctx-batch.sh - Benchmark context/batch combinations for real coding-agent workload
# Runs on ubt26 (the GPU host)
#
# Usage:
#   ./bench-ctx-batch.sh                    # full benchmark (all 20 configs)
#   ./bench-ctx-batch.sh --ctx 65536        # single context size
#   ./bench-ctx-batch.sh --batch 4096 --ubatch 256  # single batch config
#   ./bench-ctx-batch.sh --quick            # reduced set (3 ctx × 2 batch)
#
# Results saved to TSV in ./bench-results/
#
# Override model with environment variables:
#   BENCH_MODEL_REPO=... BENCH_MODEL_FILE=... BENCH_MODEL_ALIAS=... ./bench-ctx-batch.sh

set -euo pipefail

LLAMA_BIN="${LLAMA_BIN:-$HOME/llama.cpp/build-vulkan/bin/llama-server}"
PORT=8080
RESULTS_DIR="./bench-results"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
RESULTS_FILE="$RESULTS_DIR/ctx-batch-${TIMESTAMP}.tsv"
LOG_DIR="$RESULTS_DIR/logs-${TIMESTAMP}"
MODEL_REPO="${BENCH_MODEL_REPO:-DavidAU/Qwen3.6-27B-Heretic-Uncensored-FINETUNE-NEO-CODE-Di-IMatrix-MAX-GGUF}"
MODEL_FILE="${BENCH_MODEL_FILE:-Qwen3.6-27B-NEO-CODE-HERE-2T-OT-Q6_K.gguf}"
MODEL_ALIAS="${BENCH_MODEL_ALIAS:-qwen3.6-27b-bench}"
NPROC="$(nproc 2>/dev/null || echo 16)"
WAIT_TIMEOUT=180
PROMPT_TIMEOUT=600
CACHE_RAM=16384

# Defaults
CTX_SIZES=(16384 32768 65536 98304 131072)
BATCH_CONFIGS=("1024:128" "2048:128" "4096:256" "8192:512")
QUICK_MODE=false
FILTER_CTX=""
FILTER_BATCH=""
FILTER_UBATCH=""
SERVICE_WAS_ACTIVE=false

# Parse args
while [[ $# -gt 0 ]]; do
	case "$1" in
	--ctx)
		FILTER_CTX="$2"
		shift 2
		;;
	--batch)
		FILTER_BATCH="$2"
		shift 2
		;;
	--ubatch)
		FILTER_UBATCH="$2"
		shift 2
		;;
	--quick)
		QUICK_MODE=true
		shift
		;;
	--model-file)
		MODEL_FILE="$2"
		shift 2
		;;
	--model-repo)
		MODEL_REPO="$2"
		shift 2
		;;
	--alias)
		MODEL_ALIAS="$2"
		shift 2
		;;
	--help | -h)
		echo "Usage: $0 [--ctx N] [--batch N] [--ubatch N] [--quick] [--model-file FILE] [--model-repo REPO] [--alias ALIAS]"
		exit 0
		;;
	*)
		echo "Unknown option: $1" >&2
		exit 2
		;;
	esac
done

if [[ "$QUICK_MODE" == true ]]; then
	CTX_SIZES=(32768 65536 98304)
	BATCH_CONFIGS=("2048:128" "4096:256")
fi

if [[ -n "$FILTER_CTX" ]]; then
	CTX_SIZES=("$FILTER_CTX")
fi

if [[ -n "$FILTER_BATCH" && -n "$FILTER_UBATCH" ]]; then
	BATCH_CONFIGS=("${FILTER_BATCH}:${FILTER_UBATCH}")
elif [[ -n "$FILTER_BATCH" ]]; then
	NEW_CONFIGS=()
	for bc in "${BATCH_CONFIGS[@]}"; do
		IFS=: read -r b _ <<<"$bc"
		if [[ "$b" == "$FILTER_BATCH" ]]; then
			NEW_CONFIGS+=("$bc")
		fi
	done
	BATCH_CONFIGS=("${NEW_CONFIGS[@]}")
fi

# Prompts (exact from spec)
PROMPT_SMALL='Write a Python function that parses a JSON file, validates schema, and returns structured error messages. Keep it minimal.'

PROMPT_MEDIUM='Refactor this authentication middleware to remove race conditions, improve error handling, and add structured logging. Explain assumptions before applying changes.'

PROMPT_LARGE='You are working on a real codebase.

Module A:
class Auth:
def login(self, user, password):
pass

Module B:
class SessionManager:
def validate(self, token):
pass

Problem:

intermittent null pointer during authentication
occurs under concurrent requests
must preserve API contract
fix with minimal changes
Return a patch only.'

mkdir -p "$RESULTS_DIR" "$LOG_DIR"

# TSV header
printf 'ctx\tbatch\tubatch\tprompt_type\tprompt_tokens\tcompletion_tokens\tprompt_ms\tcompletion_ms\tpp_tok_s\ttg_tok_s\tttft_ms\tstatus\tnotes\n' >"$RESULTS_FILE"

echo "=== ctx/batch benchmark ===" >&2
echo "Results: $RESULTS_FILE" >&2
echo "Logs: $LOG_DIR/" >&2
echo "Configs: ${#CTX_SIZES[@]} ctx × ${#BATCH_CONFIGS[@]} batch = $((${#CTX_SIZES[@]} * ${#BATCH_CONFIGS[@]})) total" >&2
echo "" >&2

server_pid=""
server_log=""

stop_service() {
	if systemctl --user is-active --quiet llama-server.service 2>/dev/null; then
		SERVICE_WAS_ACTIVE=true
		echo "  Stopping systemd llama-server.service" >&2
		systemctl --user stop llama-server.service 2>/dev/null || true
		sleep 5
	fi
}

restore_service() {
	stop_tracked_server
	if [[ "$SERVICE_WAS_ACTIVE" == true ]]; then
		echo "  Restoring systemd llama-server.service" >&2
		systemctl --user start llama-server.service 2>/dev/null || true
	fi
}

stop_tracked_server() {
	if [[ -n "$server_pid" ]] && kill -0 "$server_pid" 2>/dev/null; then
		kill "$server_pid" 2>/dev/null || true
		wait "$server_pid" 2>/dev/null || true
	fi
	server_pid=""
	# Kill anything on our port
	local pids
	pids="$(lsof -ti:"${PORT}" 2>/dev/null || true)"
	if [[ -n "$pids" ]]; then
		# shellcheck disable=SC2086
		kill $pids 2>/dev/null || true
	fi
	sleep 3
}

wait_for_server() {
	local attempt
	for ((attempt = 1; attempt <= WAIT_TIMEOUT; attempt++)); do
		if curl -sfS --max-time 5 "http://127.0.0.1:${PORT}/v1/models" 2>/dev/null | grep -q "$MODEL_ALIAS"; then
			return 0
		fi
		if [[ -n "$server_pid" ]] && ! kill -0 "$server_pid" 2>/dev/null; then
			return 1
		fi
		sleep 2
	done
	return 1
}

run_prompt() {
	local ctx="$1"
	local batch="$2"
	local ubatch="$3"
	local prompt_type="$4"
	local prompt="$5"
	local result_file="$LOG_DIR/ctx${ctx}-b${batch}-u${ubatch}-${prompt_type}.json"

	local prompt_json
	prompt_json="$(python3 -c "import json,sys; print(json.dumps(sys.stdin.read()))" <<<"$prompt")"

	local request
	request=$(printf '{"model":"%s","messages":[{"role":"user","content":%s}],"max_tokens":2048,"temperature":0.6,"stream":false}' \
		"$MODEL_ALIAS" "$prompt_json")

	if ! curl -sfS --max-time "${PROMPT_TIMEOUT}" \
		-H "Content-Type: application/json" \
		-d "$request" \
		"http://127.0.0.1:${PORT}/v1/chat/completions" \
		>"$result_file" 2>"${result_file}.curlerr"; then
		local curl_status=$?
		local notes="curl_error_${curl_status}"
		if [[ -f "$server_log" ]] && grep -qi 'out of memory\|hipMalloc failed\|cannot allocate\|std::bad_alloc\|OOM\|VK_ERROR' "$server_log" 2>/dev/null; then
			notes="${notes}_oom"
		fi
		printf '%s\t%s\t%s\t%s\t\t\t\t\t\t\t\terror\t%s\n' "$ctx" "$batch" "$ubatch" "$prompt_type" "$notes" >>"$RESULTS_FILE"
		return 1
	fi

	# Parse timing from llama-server response JSON using jq
	local prompt_tokens completion_tokens prompt_ms completion_ms pp_tps tg_tps ttft_ms
	prompt_tokens="$(jq -r '.usage.prompt_tokens // ""' "$result_file" 2>/dev/null || echo "")"
	completion_tokens="$(jq -r '.usage.completion_tokens // ""' "$result_file" 2>/dev/null || echo "")"
	prompt_ms="$(jq -r '.timings.prompt_ms // ""' "$result_file" 2>/dev/null || echo "")"
	completion_ms="$(jq -r '.timings.predicted_ms // ""' "$result_file" 2>/dev/null || echo "")"
	pp_tps="$(jq -r '.timings.prompt_per_second // ""' "$result_file" 2>/dev/null || echo "")"
	tg_tps="$(jq -r '.timings.predicted_per_second // ""' "$result_file" 2>/dev/null || echo "")"
	ttft_ms="$(jq -r '.timings.time_to_first_token_ms // .timings.prompt_ms // ""' "$result_file" 2>/dev/null || echo "")"

	# Round to 2 decimal places
	pp_tps="$(python3 -c "print(round(float('${pp_tps:-0}'),2))" 2>/dev/null || echo "$pp_tps")"
	tg_tps="$(python3 -c "print(round(float('${tg_tps:-0}'),2))" 2>/dev/null || echo "$tg_tps")"
	prompt_ms="$(python3 -c "print(round(float('${prompt_ms:-0}'),1))" 2>/dev/null || echo "$prompt_ms")"
	completion_ms="$(python3 -c "print(round(float('${completion_ms:-0}'),1))" 2>/dev/null || echo "$completion_ms")"

	local notes="ok"

	printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
		"$ctx" "$batch" "$ubatch" "$prompt_type" \
		"${prompt_tokens:-NA}" "${completion_tokens:-NA}" \
		"${prompt_ms:-NA}" "${completion_ms:-NA}" \
		"${pp_tps:-NA}" "${tg_tps:-NA}" "${ttft_ms:-NA}" \
		"ok" "${notes}" >>"$RESULTS_FILE"

	sleep 2
	return 0
}

start_server() {
	local ctx="$1"
	local batch="$2"
	local ubatch="$3"

	stop_tracked_server
	sleep 2

	server_log="$LOG_DIR/server-ctx${ctx}-b${batch}-u${ubatch}.log"

	echo "  Starting server: ctx=$ctx batch=$batch ubatch=$ubatch" >&2

	GGML_VK_VISIBLE_DEVICES=0,1 \
		"$LLAMA_BIN" \
		-hf "$MODEL_REPO" \
		--hf-file "$MODEL_FILE" \
		--host 127.0.0.1 \
		--port "$PORT" \
		-ngl 999 \
		--split-mode layer \
		--tensor-split 1,1 \
		--flash-attn on \
		-c "$ctx" \
		-b "$batch" \
		-ub "$ubatch" \
		--cache-ram "$CACHE_RAM" \
		--threads "$NPROC" \
		--prio 2 \
		--no-warmup \
		--timeout 600 \
		--parallel 1 \
		--no-cont-batching \
		--temp 0.6 \
		--top-p 0.95 \
		--top-k 20 \
		--min-p 0.0 \
		--presence-penalty 0.5 \
		--repeat-penalty 1.0 \
		--reasoning on \
		--alias "$MODEL_ALIAS" \
		>>"$server_log" 2>&1 &

	server_pid=$!

	if ! wait_for_server; then
		echo "  FAILED: server did not start (pid=$server_pid)" >&2
		if [[ -f "$server_log" ]] && grep -qi 'out of memory\|hipMalloc failed\|cannot allocate\|std::bad_alloc\|OOM\|VK_ERROR' "$server_log" 2>/dev/null; then
			echo "  OOM detected" >&2
			for pt in small medium large; do
				printf '%s\t%s\t%s\t%s\t\t\t\t\t\t\t\toom\tserver_oom\n' "$ctx" "$batch" "$ubatch" "$pt" >>"$RESULTS_FILE"
			done
			stop_tracked_server
			return 1
		fi
		stop_tracked_server
		return 1
	fi

	echo "  Server ready (pid=$server_pid)" >&2
	return 0
}

trap restore_service EXIT

stop_service

total_configs=$((${#CTX_SIZES[@]} * ${#BATCH_CONFIGS[@]}))
current=0

for ctx in "${CTX_SIZES[@]}"; do
	for bc in "${BATCH_CONFIGS[@]}"; do
		IFS=: read -r batch ubatch <<<"$bc"
		current=$((current + 1))
		echo "" >&2
		echo "=== [$current/$total_configs] ctx=$ctx batch=$batch ubatch=$ubatch ===" >&2

		if ! start_server "$ctx" "$batch" "$ubatch"; then
			echo "  SKIP: could not start server" >&2
			continue
		fi

		# Warmup
		echo "  Warmup..." >&2
		curl -sfS --max-time 120 \
			-H "Content-Type: application/json" \
			-d "{\"model\":\"${MODEL_ALIAS}\",\"messages\":[{\"role\":\"user\",\"content\":\"ok\"}],\"max_tokens\":8,\"temperature\":0}" \
			"http://127.0.0.1:${PORT}/v1/chat/completions" \
			>/dev/null 2>&1 || true
		sleep 2

		echo "  [1/3] small prompt..." >&2
		run_prompt "$ctx" "$batch" "$ubatch" "small" "$PROMPT_SMALL" || true

		echo "  [2/3] medium prompt..." >&2
		run_prompt "$ctx" "$batch" "$ubatch" "medium" "$PROMPT_MEDIUM" || true

		echo "  [3/3] large prompt..." >&2
		run_prompt "$ctx" "$batch" "$ubatch" "large" "$PROMPT_LARGE" || true

		echo "  Done ctx=$ctx batch=$batch" >&2
	done
done

echo "" >&2
echo "=== Benchmark complete ===" >&2
echo "Results TSV: $RESULTS_FILE" >&2
echo "" >&2
echo "=== Results ===" >&2
column -t -s $'\t' "$RESULTS_FILE" >&2
