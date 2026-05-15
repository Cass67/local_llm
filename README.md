# local_llm

Tooling for running local LLMs via llama.cpp, managed from a single, config-driven system.

## Architecture

- `configs/profiles.json`: single source of truth for model families and profiles.
- `scripts/oc-local`: central launcher; uses profiles.json to start models.
- `scripts/model-manager.sh`: model lifecycle (candidate -> benchmarked -> accepted -> wired into profiles.json).
- `scripts/update-manager.sh`: high-level update helper wired to model-manager.
- `scripts/hardware-analyzer.sh`: system capability detection.
- `scripts/model-discovery.sh`: recommendations + connection to model-manager.
- `scripts/lib.sh`: shared utilities (logging, JSON helpers, SSH runner, etc.).
- `runs/`: runtime metadata (per-run JSON files).

Simplified flow:

- You:
  - oc-local qwen reliable
- oc-local:
  - reads configs/profiles.json
  - builds llama-server command
  - writes runs/<profile>_*.json
- model-manager:
  - discovers/benchmarks/accepts models
  - updates profiles.json

## Quick Start

- List available profiles:
  - oc-local list-profiles
- Show a profile:
  - oc-local show qwen:reliable
- Start a model:
  - oc-local qwen reliable
  - oc-local qwen-coder reliable --lean
- Dry-run (no launch):
  - oc-local qwen reliable --dry-run
- Inspect recent runs:
  - oc-local last-runs 5

Symlinks like oc-qwen-reliable still work and map to:
  oc-local qwen reliable

## Profiles

A profile is: family:profile, for example:

- qwen:reliable
- qwen-coder:speed
- gemma:balanced
- gpt-oss:tiny

Each defines:
- model name and Hugging Face repo
- quantization
- context size
- batching, NGL, mmproj
- reasoning effort, output limits

All concrete settings live in configs/profiles.json.

## Model Lifecycle (model-manager)

Use model-manager.sh to manage candidate models:

- Discover:
  - model-manager.sh discover qwen
- List candidates:
  - model-manager.sh list-candidates
- Select a candidate:
  - model-manager.sh select qwen unsloth/Qwen3.6-35B-A3B-GGUF UD-Q3_K_XL
- Benchmark:
  - model-manager.sh benchmark qwen:<candidate-id>
- Accept (wire into profiles.json):
  - model-manager.sh accept qwen:<candidate-id>
- Status:
  - model-manager.sh status

## Notes

- No start*.sh scripts; all launch behavior is via oc-local + profiles.json.
- All shell scripts should source scripts/lib.sh for shared utilities.
