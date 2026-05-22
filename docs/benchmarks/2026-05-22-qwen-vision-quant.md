# Qwen Vision Quant Benchmark - 2026-05-22

## Summary

This benchmark kept the matrix intentionally small. Only already cached IQ4_XS model files were live-tested on `ubt26`; Q4_K_M and Q5_K_M candidates exist upstream but were not downloaded because each would require a large transfer and this task asked to avoid huge downloads when possible.

The Hauhau Qwen 35B IQ4_XS 65k candidate loaded with its multimodal projector and benchmark-only q8_0 KV cache flags. It was the best measured cached candidate by load health and short-probe throughput. `GGML_HIP_FORCE_MMQ=1` was slower in this run. During benchmarking, the chat probe did not return exactly `ok` because the template emitted reasoning text first. Follow-up launcher work added `--chat-template-kwargs '{"enable_thinking":false}'`, and final remote verification returned exactly `ok`.

Recommendation candidate: Hauhau Qwen 35B IQ4_XS 65k is the best measured candidate in this report, but this report alone does not justify quant, KV, MMQ, or default promotion. Validate the prompt/template behavior before any quality promotion, and run a follow-up benchmark only if Q4_K_M/Q5_K_M files are intentionally downloaded.

## Environment

| Field | Value |
| --- | --- |
| Host | `ubt26` |
| Runtime | `/home/cass/llama.cpp/build/bin/llama-server` |
| llama.cpp fingerprint | `b9222-9a532ae4b` from API responses |
| Probe | `/v1/chat/completions`, prompt `Reply with exactly: ok`, `max_tokens: 32`, `temperature: 0` |
| Common flags | `--mmproj-auto --cache-type-k q8_0 --cache-type-v q8_0 --flash-attn on -ngl 999 -b 64 -ub 64 --no-warmup` |

The q8_0 KV flags were part of the temporary benchmark commands only. At the time of this report, `scripts/start11.sh` does not set `--cache-type-k q8_0` or `--cache-type-v q8_0`; those flags should not be treated as promoted defaults.

## Complete HF File Inventory

Files below are all `.gguf` and mmproj entries returned by the Hugging Face tree APIs for the required repos on 2026-05-22.

### HauhauCS/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive

| File | Size bytes |
| --- | ---: |
| `Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-IQ2_M.gguf` | 11659235456 |
| `Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-IQ3_M.gguf` | 15440519296 |
| `Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-IQ4_NL.gguf` | 19779278976 |
| `Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-IQ4_XS.gguf` | 18728777856 |
| `Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-Q2_K_P.gguf` | 14981265536 |
| `Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-Q3_K_P.gguf` | 19023337600 |
| `Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-Q4_K_M.gguf` | 21166758016 |
| `Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-Q4_K_P.gguf` | 23424536704 |
| `Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-Q5_K_P.gguf` | 28027394176 |
| `Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-Q6_K_P.gguf` | 30649317504 |
| `Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-Q8_K_P.gguf` | 43605014656 |
| `mmproj-Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-f16.gguf` | 899283072 |

### unsloth/Qwen3.6-35B-A3B-MTP-GGUF

| File | Size bytes |
| --- | ---: |
| `BF16/Qwen3.6-35B-A3B-BF16-00001-of-00002.gguf` | 49913715456 |
| `BF16/Qwen3.6-35B-A3B-BF16-00002-of-00002.gguf` | 21152227104 |
| `Qwen3.6-35B-A3B-MXFP4_MOE.gguf` | 22182574368 |
| `Qwen3.6-35B-A3B-Q8_0.gguf` | 37801097504 |
| `Qwen3.6-35B-A3B-UD-IQ1_M.gguf` | 11366414624 |
| `Qwen3.6-35B-A3B-UD-IQ2_M.gguf` | 11882969376 |
| `Qwen3.6-35B-A3B-UD-IQ2_XXS.gguf` | 11819399456 |
| `Qwen3.6-35B-A3B-UD-IQ3_S.gguf` | 15346432288 |
| `Qwen3.6-35B-A3B-UD-IQ3_XXS.gguf` | 14069266720 |
| `Qwen3.6-35B-A3B-UD-IQ4_NL.gguf` | 18536192288 |
| `Qwen3.6-35B-A3B-UD-IQ4_XS.gguf` | 18209036576 |
| `Qwen3.6-35B-A3B-UD-Q2_K_XL.gguf` | 12574128416 |
| `Qwen3.6-35B-A3B-UD-Q3_K_M.gguf` | 17104402720 |
| `Qwen3.6-35B-A3B-UD-Q3_K_XL.gguf` | 17227569440 |
| `Qwen3.6-35B-A3B-UD-Q4_K_M.gguf` | 22663387424 |
| `Qwen3.6-35B-A3B-UD-Q4_K_S.gguf` | 21388319008 |
| `Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf` | 22853663008 |
| `Qwen3.6-35B-A3B-UD-Q5_K_M.gguf` | 27087812896 |
| `Qwen3.6-35B-A3B-UD-Q5_K_S.gguf` | 25538017568 |
| `Qwen3.6-35B-A3B-UD-Q5_K_XL.gguf` | 27159116064 |
| `Qwen3.6-35B-A3B-UD-Q6_K.gguf` | 30011242784 |
| `Qwen3.6-35B-A3B-UD-Q6_K_XL.gguf` | 32611711264 |
| `Qwen3.6-35B-A3B-UD-Q8_K_XL.gguf` | 39099447584 |
| `mmproj-BF16.gguf` | 902822528 |
| `mmproj-F16.gguf` | 899283584 |
| `mmproj-F32.gguf` | 1786305152 |

## Benchmark-Relevant Availability

| Repo | File | Size | Cached on `ubt26` | Notes |
| --- | --- | ---: | --- | --- |
| `HauhauCS/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive` | `Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-IQ4_XS.gguf` | 18.7 GB | yes | Current live quant. |
| `HauhauCS/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive` | `mmproj-Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-f16.gguf` | 899 MB | yes | Loaded by `--mmproj-auto`. |
| `HauhauCS/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive` | `Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-Q4_K_M.gguf` | 21.2 GB | no | Available upstream; not downloaded. |
| `HauhauCS/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive` | `Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-Q5_K_P.gguf` | 28.0 GB | no | Closest Hauhau Q5 candidate; no `Q5_K_M` in repo listing. Not downloaded. |
| `unsloth/Qwen3.6-35B-A3B-MTP-GGUF` | `Qwen3.6-35B-A3B-UD-IQ4_XS.gguf` | 18.2 GB | yes | Cached MTP candidate. |
| `unsloth/Qwen3.6-35B-A3B-MTP-GGUF` | `mmproj-BF16.gguf` | 903 MB | yes | Loaded by `--mmproj-auto`. |
| `unsloth/Qwen3.6-35B-A3B-MTP-GGUF` | `mmproj-F16.gguf` | 899 MB | no | Available upstream. |
| `unsloth/Qwen3.6-35B-A3B-MTP-GGUF` | `Qwen3.6-35B-A3B-UD-Q4_K_M.gguf` | 22.7 GB | no | Available upstream; not downloaded. |
| `unsloth/Qwen3.6-35B-A3B-MTP-GGUF` | `Qwen3.6-35B-A3B-UD-Q5_K_M.gguf` | 27.1 GB | no | Available upstream; not downloaded. |

## Results

| Family | Repo | Model id | GGUF | Context | KV | MMQ | mmproj | Status | Prompt tok/s | Decode tok/s | Notes |
| --- | --- | --- | --- | ---: | --- | --- | --- | --- | ---: | ---: | --- |
| `qwen-hauhau` | `HauhauCS/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive` | `qwen3.6-35b-a3b-hauhau` | `Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-IQ4_XS.gguf` | 65536 | `q8_0/q8_0` benchmark-only | default | loaded, multimodal | loaded; reasoning-first probe during benchmark | 210.03 | 87.43 | Loaded without OOM in logs; no exact VRAM number captured. Benchmark probe emitted reasoning before final answer until follow-up launcher work disabled thinking. |
| `qwen-hauhau` | `HauhauCS/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive` | `qwen3.6-35b-a3b-hauhau` | `Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-IQ4_XS.gguf` | 65536 | `q8_0/q8_0` benchmark-only | `GGML_HIP_FORCE_MMQ=1` | loaded, multimodal | loaded; reasoning-first probe during benchmark | 66.02 | 62.49 | Loaded without OOM in logs; no exact VRAM number captured. Forced MMQ was slower than default on this short run. |
| `qwen-mtp` | `unsloth/Qwen3.6-35B-A3B-MTP-GGUF` | `qwen3.6-35b-a3b-mtp` | `Qwen3.6-35B-A3B-UD-IQ4_XS.gguf` | 65536 | `q8_0/q8_0` benchmark-only | default | loaded, multimodal | loaded; reasoning-first probe during benchmark | 123.88 | 79.04 | Loaded without OOM in logs; no exact VRAM number captured. Cached MTP IQ4_XS loaded with `mmproj-BF16.gguf`. |
| `qwen-hauhau` | `HauhauCS/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive` | not run | `Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-Q4_K_M.gguf` | 32768/65536 | `q8_0/q8_0` | not run | available upstream | unavailable locally | n/a | n/a | Not cached; skipped to avoid a 21.2 GB download. |
| `qwen-hauhau` | `HauhauCS/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive` | not run | `Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-Q5_K_P.gguf` | 32768 | `q8_0/q8_0` | not run | available upstream | unavailable locally | n/a | n/a | Closest Hauhau Q5 candidate; no `Q5_K_M` listed. Skipped to avoid a 28.0 GB download. |
| `qwen-mtp` | `unsloth/Qwen3.6-35B-A3B-MTP-GGUF` | not run | `Qwen3.6-35B-A3B-UD-Q4_K_M.gguf` | 32768/65536 | `q8_0/q8_0` | not run | available upstream | unavailable locally | n/a | n/a | Not cached; skipped to avoid a 22.7 GB download. |
| `qwen-mtp` | `unsloth/Qwen3.6-35B-A3B-MTP-GGUF` | not run | `Qwen3.6-35B-A3B-UD-Q5_K_M.gguf` | 32768 | `q8_0/q8_0` | not run | available upstream | unavailable locally | n/a | n/a | Not cached; skipped to avoid a 27.1 GB download. |

## Notes

- The live benchmark service was temporarily stopped for controlled runs and restored afterward to `REMOTE_SCRIPT=./start11.sh`, `REMOTE_PROFILE=reliable`.
- `/v1/models` reported `capabilities: ["completion", "multimodal"]` for the restored `qwen3.6-35b-a3b-hauhau` service at 65k context.
- The prompt is too short to be a stable throughput benchmark; these numbers are only useful for quick candidate screening.
- The benchmark exact-output issue was traced to Qwen thinking being enabled in the chat template, not to quant quality. Follow-up launcher verification with `enable_thinking=false` returned `content: "ok"` with `finish_reason: "stop"`.
- No benchmark run logged OOM or failed to load among the three cached IQ4_XS candidates. Exact VRAM usage was not captured, so this report only supports "loaded without observed OOM," not a precise VRAM headroom claim.
- No defaults are promoted by this report. In particular, q8_0 KV and `GGML_HIP_FORCE_MMQ=1` were benchmark variables, not launcher changes.
