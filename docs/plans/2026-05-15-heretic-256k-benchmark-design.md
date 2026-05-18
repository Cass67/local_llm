# Heretic 256k Benchmark Design

## Goal

Measure what quant/context combination is required for `qwen-heretic` to reach 128k, 196k, or 256k context on the RX 7900 XT.

## Method

Run a controlled load matrix on `ubt26`. Each trial stops any existing `llama-server`, starts Heretic with one quant/context pair and the OpenCode-compatible Qwen3.6 template override, waits for `/v1/models`, then runs a small completion if the model loads.

## Matrix

Quants:

- `Qwen3.6-27B-NEO-CODE-HERE-2T-OT-Q4_K_M.gguf`
- `Qwen3.6-27B-NEO-CODE-HERE-2T-OT-Q4_K_S.gguf`
- `Qwen3.6-27B-NEO-CODE-HERE-2T-OT-IQ4_XS.gguf`
- `Qwen3.6-27B-NEO-CODE-HERE-2T-OT-IQ3_M.gguf`
- `Qwen3.6-27B-NEO-CODE-HERE-2T-OT-IQ2_M.gguf`

Contexts:

- `65536`
- `98304`
- `131072`
- `196608`
- `262144`

## Recorded Data

- load status
- OOM or error reason
- model buffer
- KV buffer
- recurrent/state buffer
- compute buffer
- memory breakdown/free VRAM
- prompt tokens/sec
- decode tokens/sec

## Success Criteria

256k is possible only if the model loads and completes a small request. It is useful only if decode speed and memory headroom are acceptable for OpenCode.
