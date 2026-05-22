# Installed Model KV Cache Benchmark Design

## Goal

Benchmark KV cache settings across installed reliable launcher families on `ubt26`, then decide whether any launcher defaults should use explicit KV quantization.

## Scope

Benchmark installed reliable families that are already represented by shortcuts and cached GGUFs:

- `qwen`
- `qwen-hauhau`
- `qwen-27b-hauhau`
- `gemma-hauhau`
- `qwen-27b`
- `qwen-coder`
- `gemma`
- `gemma-vision`
- `gpt-oss`
- `deepseek-r1`
- `qwen-opus`
- `qwen-heretic`

## Approach

Use a two-pass benchmark.

Pass 1 benchmarks each reliable family with:

- default KV cache, meaning no explicit `--cache-type-k` or `--cache-type-v`.
- `q8_0/q8_0` using `--cache-type-k q8_0 --cache-type-v q8_0`.

Pass 2 benchmarks `q4_0/q4_0` for candidates that fail, are memory-bound, or show enough benefit potential to justify a lower-quality KV cache. During execution, `RUN_Q4=1` was used across all families to get complete comparison data because pass 1 showed no OOM/load failures and q8/default tradeoffs were mixed.

## Measurements

For each run, record:

- family, model id, repo, quant, context, batch, ubatch, mmproj mode.
- KV mode: default, `q8_0/q8_0`, or `q4_0/q4_0`.
- load status and any OOM/failure reason.
- prompt tok/s and decode tok/s from llama.cpp logs or API timings.
- KV buffer size/log lines when available.
- API sanity probe result.
- multimodal capability for families that should load mmproj.

## Promotion Rules

Do not change launcher defaults during the benchmark.

After results are collected:

- Prefer explicit `q8_0/q8_0` only when it is stable and matches or improves practical throughput without hurting output sanity.
- Use `q4_0/q4_0` only when it enables a target context or prevents OOM/VRAM pressure.
- Keep default KV when explicit KV is slower, unstable, or inconclusive.

## Output

Write findings to:

- `docs/benchmarks/2026-05-22-installed-kv-cache.md`

Only after reviewing that report should launcher defaults be promoted in a separate small change.
