# ROCm Dual-GPU Context Design

## Goal

Tune the existing accepted model launcher path for one `llama-server` process using both Radeon RX 7900 XT cards on host `ubt26`, prioritizing max practical context and highest stable tok/s for the current model.

## Scope

In scope:

- Existing accepted model only.
- Single `llama-server` instance.
- ROCm/HIP-first dual-GPU operation.
- Launcher/config support for context shifting.
- Benchmark and accept metadata preservation for dual-GPU and context-shift settings.

Out of scope:

- Discovering or selecting new models.
- Running two independent servers.
- Changing Cloudflare, Caddy, OpenCode web, or switcher routing.
- Removing Vulkan fallback support.

## Architecture

The project already stores accepted model settings in benchmark JSON and accepted metadata, then generates shell launchers that invoke `llama-server`. This change extends that existing metadata pipeline with ROCm dual-device visibility and `--ctx-shift` support.

The launcher remains the single source of truth for runtime flags. Benchmark commands produce the same fields that generated launchers consume, so a passing benchmark can be accepted without manual flag drift.

## Runtime Configuration

For the target host and model, the preferred runtime shape is:

- backend: default ROCm/HIP build, represented by the existing non-Vulkan `./build/bin/llama-server` path.
- visible devices: `0,1`.
- ROCm visibility env: export both `HIP_VISIBLE_DEVICES=0,1` and `ROCR_VISIBLE_DEVICES=0,1` when dual devices are configured for ROCm/default backend.
- GPU layer offload: `-ngl 999`.
- tensor split: `--tensor-split 1,1`.
- split mode: benchmark `row` and `layer`; use the faster stable result.
- context shift: pass `--ctx-shift` when configured so long chats can roll instead of failing when context fills.

## Data Flow

1. `model-manager benchmark` runs the current accepted model with explicit dual-GPU ROCm settings.
2. The remote benchmark starts `./build/bin/llama-server` with dual-device env, split flags, max context, and optional `--ctx-shift`.
3. Benchmark output records `backend`, `visible_devices`, `split_mode`, `tensor_split`, cache types, and `ctx_shift`.
4. `model-manager accept` reads those fields and writes accepted metadata.
5. Generated launchers include the same env and flags.
6. `run-current-model.sh` starts the selected generated launcher through `llama-server.service`.

## Error Handling

- Existing validation style is preserved: simple shell validation before command execution and Python validation before JSON/launcher writes.
- `ctx_shift` accepts only safe values supported by llama.cpp usage: boolean-like enablement (`on`, `true`, `1`) or explicit non-negative integer when a build exposes numeric behavior. Empty means omitted.
- ROCm visibility env is only emitted when visible devices are configured and backend is not Vulkan.
- Vulkan behavior stays unchanged: `GGML_VK_VISIBLE_DEVICES` remains Vulkan-only.

## Testing

Tests should cover the metadata and launcher pipeline without needing GPUs:

- Smoke tests continue to pass.
- Existing launcher generation tests or smoke fixtures should verify:
  - ROCm/default backend emits `HIP_VISIBLE_DEVICES` and `ROCR_VISIBLE_DEVICES`.
  - Vulkan backend still emits `GGML_VK_VISIBLE_DEVICES`.
  - `ctx_shift` is validated and preserved through benchmark JSON, accepted metadata, and generated launcher output.
  - Invalid `ctx_shift` values are rejected.

Manual verification on `ubt26` after deploy:

```bash
amd-smi
model-manager benchmark <current-source> --target remote:ubt26 --backend rocm --visible-devices 0,1 --split-mode row --tensor-split 1,1 --ctx-shift on --full
model-manager benchmark <current-source> --target remote:ubt26 --backend rocm --visible-devices 0,1 --split-mode layer --tensor-split 1,1 --ctx-shift on --full
```

Accept the faster stable benchmark, deploy, restart `llama-server.service`, then verify both GPUs show the same `llama-server` PID with meaningful VRAM use.
