# Hauhau Model Additions Design

## Goal

Add, benchmark, and install shortcuts for three Hauhau model families on `ubt26`:

- `HauhauCS/Qwen3.6-27B-Uncensored-HauhauCS-Aggressive`
- `HauhauCS/GLM-4.7-Flash-Uncensored-HauhauCS-Aggressive`
- `HauhauCS/Gemma4-26B-A4B-Uncensored-HauhauCS-Balanced`

## Design

Add three local_llm families:

- `qwen-27b-hauhau` using `scripts/start12.sh`
- `glm-hauhau` using `scripts/start13.sh`
- `gemma-hauhau` using `scripts/start14.sh`

Each family gets profile shortcuts for `speed`, `fastlong`, `balanced`, `reliable`, and `tiny`, plus a base shortcut that defaults to `reliable`.

Use the highest practical quant first:

- Qwen 27B Hauhau: `Qwen3.6-27B-Uncensored-HauhauCS-Aggressive-IQ4_XS.gguf`
- GLM Hauhau: `GLM-4.7-Flash-Uncensored-HauhauCS-Aggressive-Q4_K_M.gguf`
- Gemma Hauhau: `Gemma4-26B-A4B-Uncensored-HauhauCS-Balanced-IQ4_XS.gguf`

Qwen and Gemma repos include `mmproj` files. Include mmproj only if smoke/benchmark starts can fit on hardware. GLM is text-only because no mmproj file exists in the repo.

## Benchmark Policy

Start with `ctx=65536`, `batch=64`, `ubatch=64`. If a model fails to load or OOMs, retry `ctx=49152`; if needed, reduce quant. Record load status, VRAM buffer sizes where available, prompt/decode throughput, and selected profile values.

## Outputs

- New launchers: `scripts/start12.sh`, `scripts/start13.sh`, `scripts/start14.sh`
- Updated `scripts/oc-local`
- Updated `installer.sh`
- Updated `test_oc_local.sh`
- Benchmark report under `docs/benchmarks/`
- Installed local shortcuts in `~/.local/bin`
- Copied launchers to `/home/cass/llama.cpp` on `ubt26`
