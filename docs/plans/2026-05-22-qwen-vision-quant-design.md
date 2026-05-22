# Qwen Vision And Quant Benchmark Design

## Goal

Make Qwen 35B vision-enabled by default and benchmark better Qwen 35B quant/KV profiles on `ubt26`.

## Scope

- Enable multimodal projector auto-loading for the existing `qwen` and `qwen-hauhau` 35B launchers.
- Keep existing shortcut names as the default UX.
- Benchmark Qwen 35B profiles using `q8_0` KV cache and candidate quants from the recent Qwen3.6 discussion.
- Test `GGML_HIP_FORCE_MMQ=1` as a benchmark variable before promoting it.

## Non-Goals

- Do not add separate `qwen-vision` shortcut families unless vision default proves too expensive.
- Do not promote GLM again.
- Do not replace the user systemd dynamic model selector.

## Launcher Changes

Change these launchers from `--no-mmproj` to `--mmproj-auto`:

- `scripts/start3.sh` for `qwen` / Qwen3.6 35B MTP.
- `scripts/start11.sh` for `qwen-hauhau` / Hauhau Qwen3.6 35B.

Update `scripts/oc-local` metadata so both families report `mmproj=enabled` in `--info` output.

## Benchmark Plan

Benchmark Qwen 35B on `ubt26` with a small matrix:

- Context: `32768` and `65536`.
- KV cache: `--cache-type-k q8_0 --cache-type-v q8_0`.
- Quants: current `IQ4_XS`, plus available `Q4_K_M`, `Q5_K_M`, and possibly `Q6_K` if the repo provides them and VRAM permits.
- Runtime variable: compare default HIP behavior with `GGML_HIP_FORCE_MMQ=1`.

Measure load success, prompt ingestion tok/s, decode tok/s, VRAM pressure, and whether vision projector loads successfully.

## Promotion Rule

Promote the best stable text+vision default only after it loads reliably under the user systemd service and passes a small chat completion probe. Prefer responsiveness and stability over theoretical quant quality.

If vision adds too much overhead, keep vision default as requested but document a future text-only fallback rather than adding it immediately.

## Tests And Docs

- Update tests to assert Qwen 35B launchers use `--mmproj-auto`.
- Update `--info` tests to expect `mmproj=enabled` for `qwen` and `qwen-hauhau`.
- Add a benchmark report documenting quant/KV/MMQ results.
- Update README recommendations after selecting a winner.
