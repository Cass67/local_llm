# Model Manager Design

## Goal

Build a hybrid workflow for discovering new GGUF models, selecting candidates, benchmarking them on local or remote llama.cpp targets, and accepting successful models into the local_llm suite.

The workflow should stay scriptable for repeatability, but offer interactive selection for manual exploration.

## Entry Points

Add a new orchestration script:

```bash
scripts/model-manager.sh
```

Installed as:

```bash
model-manager
```

Primary commands:

```bash
model-manager discover
model-manager select
model-manager benchmark
model-manager accept
model-manager status
```

Existing `oc-local` remains the runtime wrapper for accepted models, but becomes target-aware so the same profile suite can run against local or remote llama.cpp.

## Target Model

Use one target syntax across discovery, benchmark, and runtime:

```bash
--target local
--target remote:ubt26
```

Defaults:

```bash
OC_LOCAL_TARGET="${OC_LOCAL_TARGET:-remote:${OC_LOCAL_REMOTE_HOST:-ubt26}}"
OC_LOCAL_LLAMA_DIR="${OC_LOCAL_LLAMA_DIR:-$HOME/llama.cpp}"
OC_LOCAL_REMOTE_DIR="${OC_LOCAL_REMOTE_DIR:-/home/cass/llama.cpp}"
```

A resolved target carries:

```text
target_kind=local|remote
host=<host for remote targets>
llama_dir=<local or remote llama.cpp dir>
base_url=<OpenAI-compatible API URL>
server_port=8080
hardware_summary=<detected CPU/RAM/GPU/VRAM/ROCm info>
```

For remote targets, commands run over SSH in `OC_LOCAL_REMOTE_DIR`.

For local targets, commands run directly in `OC_LOCAL_LLAMA_DIR`.

## oc-local Runtime Changes

`oc-local` keeps the current family/profile resolution and generated OpenCode config behavior, but splits launch behavior by target.

Shared flow:

```text
parse options -> resolve target -> resolve family/profile -> build server command -> start target -> wait for API -> launch OpenCode
```

Remote target behavior:

```text
ssh host
cd remote_dir
pkill llama-server
nohup startN.sh profile > llama-profile.log &
wait with ssh curl http://127.0.0.1:8080/v1/models
wait from client against configured base_url
launch opencode
```

Local target behavior:

```text
cd local_llama_dir
pkill llama-server
nohup startN.sh profile > llama-profile.log &
wait with local curl http://127.0.0.1:8080/v1/models
base_url defaults to http://127.0.0.1:8080/v1
launch opencode
```

Example runtime commands:

```bash
oc-qwen-reliable --lean
oc-qwen-reliable --lean --target remote:ubt26
oc-qwen-reliable --lean --target local
```

Accepted `startN.sh` launchers should remain plain llama.cpp launchers that can run locally or remotely as long as they live beside a compatible llama.cpp build.

## model-manager Commands

### discover

Find and rank Hugging Face GGUF candidates for a target.

Examples:

```bash
model-manager discover --target remote:ubt26 --query "qwen coder gguf" --limit 20
model-manager discover --target local --query "7b gguf" --json
```

Responsibilities:

```text
detect target hardware
query Hugging Face GGUF models
rank candidates for detected hardware
print human-readable candidates
with --json in the first pass, emit only a metadata envelope for the discovery run
```

Future candidate records should include:

```text
repo
purpose
size_class
fit
reason
```

### select

Choose one or more discovered candidates.

Interactive mode:

```bash
model-manager select
```

Scriptable mode:

```bash
model-manager select --repo unsloth/Foo-GGUF --family foo --alias foo-30b --purpose code
```

Selection records are written for later benchmarking.

### benchmark

Benchmark selected candidates against a local or remote target.

Examples:

```bash
model-manager benchmark selected --target remote:ubt26
model-manager benchmark selected --target local
model-manager benchmark --repo Jackrong/foo-GGUF --family foo --profiles speed,reliable --target remote:ubt26
```

Remote benchmark behavior:

```text
ssh target host
cd target llama.cpp dir
start candidate llama-server command
wait for /v1/models
run prompt/decode probe
collect logs and stats
stop llama-server
write benchmark result
```

Local benchmark behavior is the same without SSH.

Benchmark result records include:

```text
target
repo
hf_file or quant
family
alias
profile
ctx
batch
ubatch
ngl
load_status
OOM/error status
VRAM if available
prompt tok/s
decode tok/s
llama-server command
log excerpt path
timestamp
```

### accept

Turn a successful benchmark into a permanent suite entry.

Example:

```bash
model-manager accept runs/benchmarks/foo.json
```

Acceptance updates:

```text
scripts/startN.sh
scripts/oc-local
installer.sh
README.md
test_oc_local.sh
```

Rules:

```text
do not replace existing defaults automatically
keep benchmark-only models labelled as candidates until explicitly promoted
preserve real aliases and localllm/<alias> model ids
keep tool_call=false
reasoning models use larger output limits and are not forced to --reasoning off
vision models preserve mmproj behavior
```

### status

Show workflow state:

```bash
model-manager status
```

Output includes:

```text
configured targets
recent candidates
selected candidates
benchmark results
accepted families
benchmark-only launchers that may be cleaned up
```

## Data Layout

Use repo-local runtime artifacts:

```text
runs/candidates/
runs/selections/
runs/benchmarks/
```

These should be ignored by git by default. Durable accepted suite changes remain in source files and docs.

## Implementation Slices

1. Add `--target local|remote:<host>` support to `scripts/oc-local`.
2. Add minimal `scripts/model-manager.sh` with `discover`, `select`, and `status`.
3. Add benchmark execution and benchmark result files.
4. Add accept generation/update workflow.
5. Decide whether `update-manager.sh` should call `model-manager status` or be retired.

## Non-Goals For The First Pass

Do not centralize all profiles into a declarative config yet.

Do not replace existing `startN.sh` launchers.

Do not auto-promote new models into recommended defaults.

Do not claim a model fits unless benchmark logs and a prompt/decode probe confirm it.
