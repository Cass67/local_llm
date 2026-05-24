# Installed KV Cache Benchmark - 2026-05-22

Historical benchmark record: hostnames and paths in this report describe the machine used for this dated run, not public defaults.

## Summary

This benchmark compared llama.cpp default KV cache behavior against explicit `q8_0/q8_0` and `q4_0/q4_0` KV cache modes across the installed reliable model families on `ubt26`. The earlier pass `/tmp/installed-kv-pass1.tsv` covered default and `q8_0`; `/tmp/installed-kv-q4.tsv` reran the matrix with `RUN_Q4=1` and is the most complete raw data used for the result table below.

No OOM or model-load failures were observed. Several rows are marked `error` only because the exact sanity probe did not return literal `ok`; those mismatches are prompt/model behavior in this runner, not necessarily load failures.

Overall recommendation: do not change launcher defaults from this single run. Default KV won most sane decode-throughput comparisons. `q4_0` is a follow-up candidate only for `qwen-coder`, where it improved decode throughput in this run.

## Environment

| Field | Value |
| --- | --- |
| Host | `ubt26` |
| GPU | RX 7900 XT class ROCm host, documented elsewhere in this repo as 20GB VRAM |
| Runtime directory | `/home/cass/llama.cpp` |
| Runtime binary | `/home/cass/llama.cpp/build/bin/llama-server` |
| Runner | `scripts/bench-installed-kv-remote.sh`, copied to `/home/cass/llama.cpp/bench-installed-kv-remote.sh` |
| Probe | `/v1/chat/completions`, prompt `Reply with exactly: ok`, `max_tokens: 64`, `temperature: 0` |
| Common flags | `-ngl 999 -c <context> --flash-attn on -b <batch> -ub <ubatch> --threads <nproc> --prio 2 --no-warmup` |
| KV modes | default llama.cpp KV, `--cache-type-k q8_0 --cache-type-v q8_0`, `--cache-type-k q4_0 --cache-type-v q4_0` |

The runner stopped the existing user `llama-server.service` for each direct benchmark command and restored it afterward. KV flags were benchmark-only variables, not launcher changes.

## Installed/Cached Inventory

| Family | Repo | Cached selector/file | Model alias | Context | mmproj | Notes |
| --- | --- | --- | --- | ---: | --- | --- |
| `qwen` | `unsloth/Qwen3.6-35B-A3B-MTP-GGUF` | `Qwen3.6-35B-A3B-UD-IQ4_XS.gguf` | `qwen3.6-35b-a3b-mtp` | 65536 | enabled | MTP draft enabled; Qwen thinking disabled by template kwargs. |
| `qwen-hauhau` | `HauhauCS/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive` | `Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-IQ4_XS.gguf` | `qwen3.6-35b-a3b-hauhau` | 65536 | enabled | Qwen thinking disabled by template kwargs. |
| `qwen-27b-hauhau` | `HauhauCS/Qwen3.6-27B-Uncensored-HauhauCS-Aggressive` | `Qwen3.6-27B-Uncensored-HauhauCS-Aggressive-IQ4_XS.gguf` | `qwen3.6-27b-hauhau` | 65536 | enabled | Qwen template file plus thinking disabled. |
| `gemma-hauhau` | `HauhauCS/Gemma4-26B-A4B-Uncensored-HauhauCS-Balanced` | `Gemma4-26B-A4B-Uncensored-HauhauCS-Balanced-IQ4_XS.gguf` | `gemma4-26b-a4b-hauhau` | 65536 | enabled | Sanity probe mismatched in all KV modes. |
| `qwen-27b` | `unsloth/Qwen3.6-27B-MTP-GGUF` | `Qwen3.6-27B-Q3_K_M.gguf` | `qwen3.6-27b-mtp` | 65536 | none | MTP draft enabled; sanity probe mismatched in all KV modes. |
| `qwen-coder` | `unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF` | `UD-Q3_K_XL` | `qwen3-coder-30b-a3b-instruct` | 65536 | none | Reasoning disabled. |
| `gemma` | `unsloth/gemma-4-31B-it-GGUF` | `UD-Q2_K_XL` | `gemma-4-31b-it` | 65536 | disabled | Text-only Gemma. |
| `gemma-vision` | `unsloth/gemma-4-31B-it-GGUF` | `UD-Q2_K_XL` | `gemma-4-31b-it-vision` | 32768 | enabled | Vision Gemma. |
| `gpt-oss` | `unsloth/gpt-oss-20b-GGUF` | `UD-Q8_K_XL` | `gpt-oss-20b` | 131072 | none | High reasoning effort template kwargs. |
| `deepseek-r1` | `unsloth/DeepSeek-R1-Distill-Qwen-32B-GGUF` | `Q3_K_M` | `deepseek-r1-distill-qwen-32b` | 16384 | none | Sanity probe mismatched in all KV modes. |
| `qwen-opus` | `noctrex/Qwopus3.6-27B-v1-preview-MTP-GGUF` | `Qwopus3.6-27B-v1-preview-MTP-IQ3_M.gguf` | `qwen3.6-27b-opus-mtp` | 65536 | none | MTP draft enabled. |
| `qwen-heretic` | `llmfan46/Qwen3.6-27B-uncensored-heretic-v2-Native-MTP-Preserved-GGUF` | `Qwen3.6-27B-uncensored-heretic-v2-Native-MTP-Preserved-Q3_K_M.gguf` | `qwen3.6-27b-heretic-mtp` | 65536 | none | Template file plus MTP draft; sanity probe mismatched in all KV modes. |

## Results

All `KV log` fields were empty in the raw TSV. The logs did not expose KV buffer parse data in this runner, so the table records `not exposed` for those cells.

| Family | Model | Quant | Context | KV mode | mmproj | Status | Prompt tok/s | Decode tok/s | KV log | Sanity | Notes |
| --- | --- | --- | ---: | --- | --- | --- | ---: | ---: | --- | --- | --- |
| `qwen` | `qwen3.6-35b-a3b-mtp` | `Qwen3.6-35B-A3B-UD-IQ4_XS.gguf` | 65536 | default | enabled | success | 36.22 | 59.05 | not exposed | ok |  |
| `qwen` | `qwen3.6-35b-a3b-mtp` | `Qwen3.6-35B-A3B-UD-IQ4_XS.gguf` | 65536 | `q8_0` | enabled | success | 30.13 | 54.49 | not exposed | ok |  |
| `qwen` | `qwen3.6-35b-a3b-mtp` | `Qwen3.6-35B-A3B-UD-IQ4_XS.gguf` | 65536 | `q4_0` | enabled | success | 48.41 | 57.87 | not exposed | ok |  |
| `qwen-hauhau` | `qwen3.6-35b-a3b-hauhau` | `Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-IQ4_XS.gguf` | 65536 | default | enabled | success | 65.98 | 139.18 | not exposed | ok |  |
| `qwen-hauhau` | `qwen3.6-35b-a3b-hauhau` | `Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-IQ4_XS.gguf` | 65536 | `q8_0` | enabled | success | 143.58 | 134.91 | not exposed | ok |  |
| `qwen-hauhau` | `qwen3.6-35b-a3b-hauhau` | `Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-IQ4_XS.gguf` | 65536 | `q4_0` | enabled | success | 138.99 | 133.44 | not exposed | ok |  |
| `qwen-27b-hauhau` | `qwen3.6-27b-hauhau` | `Qwen3.6-27B-Uncensored-HauhauCS-Aggressive-IQ4_XS.gguf` | 65536 | default | enabled | success | 126.75 | 64.39 | not exposed | ok |  |
| `qwen-27b-hauhau` | `qwen3.6-27b-hauhau` | `Qwen3.6-27B-Uncensored-HauhauCS-Aggressive-IQ4_XS.gguf` | 65536 | `q8_0` | enabled | success | 99.34 | 61.42 | not exposed | ok |  |
| `qwen-27b-hauhau` | `qwen3.6-27b-hauhau` | `Qwen3.6-27B-Uncensored-HauhauCS-Aggressive-IQ4_XS.gguf` | 65536 | `q4_0` | enabled | success | 154.45 | 61.20 | not exposed | ok |  |
| `gemma-hauhau` | `gemma4-26b-a4b-hauhau` | `Gemma4-26B-A4B-Uncensored-HauhauCS-Balanced-IQ4_XS.gguf` | 65536 | default | enabled | error | 71.02 | 89.26 | not exposed | mismatch | sanity mismatch |
| `gemma-hauhau` | `gemma4-26b-a4b-hauhau` | `Gemma4-26B-A4B-Uncensored-HauhauCS-Balanced-IQ4_XS.gguf` | 65536 | `q8_0` | enabled | error | 203.53 | 74.86 | not exposed | mismatch | sanity mismatch |
| `gemma-hauhau` | `gemma4-26b-a4b-hauhau` | `Gemma4-26B-A4B-Uncensored-HauhauCS-Balanced-IQ4_XS.gguf` | 65536 | `q4_0` | enabled | error | 222.08 | 75.19 | not exposed | mismatch | sanity mismatch |
| `qwen-27b` | `qwen3.6-27b-mtp` | `Qwen3.6-27B-Q3_K_M.gguf` | 65536 | default | none | error | 33.59 | 37.59 | not exposed | mismatch | sanity mismatch |
| `qwen-27b` | `qwen3.6-27b-mtp` | `Qwen3.6-27B-Q3_K_M.gguf` | 65536 | `q8_0` | none | error | 66.18 | 36.52 | not exposed | mismatch | sanity mismatch |
| `qwen-27b` | `qwen3.6-27b-mtp` | `Qwen3.6-27B-Q3_K_M.gguf` | 65536 | `q4_0` | none | error | 74.73 | 37.94 | not exposed | mismatch | sanity mismatch |
| `qwen-coder` | `qwen3-coder-30b-a3b-instruct` | `UD-Q3_K_XL` | 65536 | default | none | success | 45.95 | 87.81 | not exposed | ok |  |
| `qwen-coder` | `qwen3-coder-30b-a3b-instruct` | `UD-Q3_K_XL` | 65536 | `q8_0` | none | success | 165.10 | 68.29 | not exposed | ok |  |
| `qwen-coder` | `qwen3-coder-30b-a3b-instruct` | `UD-Q3_K_XL` | 65536 | `q4_0` | none | success | 149.89 | 102.72 | not exposed | ok |  |
| `gemma` | `gemma-4-31b-it` | `UD-Q2_K_XL` | 65536 | default | disabled | success | 66.13 | 60.32 | not exposed | ok |  |
| `gemma` | `gemma-4-31b-it` | `UD-Q2_K_XL` | 65536 | `q8_0` | disabled | success | 67.88 | 51.75 | not exposed | ok |  |
| `gemma` | `gemma-4-31b-it` | `UD-Q2_K_XL` | 65536 | `q4_0` | disabled | success | 80.25 | 51.98 | not exposed | ok |  |
| `gemma-vision` | `gemma-4-31b-it-vision` | `UD-Q2_K_XL` | 32768 | default | enabled | success | 84.59 | 58.36 | not exposed | ok |  |
| `gemma-vision` | `gemma-4-31b-it-vision` | `UD-Q2_K_XL` | 32768 | `q8_0` | enabled | success | 67.54 | 52.34 | not exposed | ok |  |
| `gemma-vision` | `gemma-4-31b-it-vision` | `UD-Q2_K_XL` | 32768 | `q4_0` | enabled | success | 71.35 | 50.41 | not exposed | ok |  |
| `gpt-oss` | `gpt-oss-20b` | `UD-Q8_K_XL` | 131072 | default | none | success | 202.89 | 128.33 | not exposed | ok |  |
| `gpt-oss` | `gpt-oss-20b` | `UD-Q8_K_XL` | 131072 | `q8_0` | none | success | 460.93 | 116.68 | not exposed | ok |  |
| `gpt-oss` | `gpt-oss-20b` | `UD-Q8_K_XL` | 131072 | `q4_0` | none | error | 485.02 | 118.50 | not exposed | mismatch | sanity mismatch |
| `deepseek-r1` | `deepseek-r1-distill-qwen-32b` | `Q3_K_M` | 16384 | default | none | error | 62.87 | 25.10 | not exposed | mismatch | sanity mismatch |
| `deepseek-r1` | `deepseek-r1-distill-qwen-32b` | `Q3_K_M` | 16384 | `q8_0` | none | error | 62.79 | 23.98 | not exposed | mismatch | sanity mismatch |
| `deepseek-r1` | `deepseek-r1-distill-qwen-32b` | `Q3_K_M` | 16384 | `q4_0` | none | error | 62.89 | 22.83 | not exposed | mismatch | sanity mismatch |
| `qwen-opus` | `qwen3.6-27b-opus-mtp` | `Qwopus3.6-27B-v1-preview-MTP-IQ3_M.gguf` | 65536 | default | none | success | 60.59 | 42.39 | not exposed | ok |  |
| `qwen-opus` | `qwen3.6-27b-opus-mtp` | `Qwopus3.6-27B-v1-preview-MTP-IQ3_M.gguf` | 65536 | `q8_0` | none | success | 82.70 | 40.57 | not exposed | ok |  |
| `qwen-opus` | `qwen3.6-27b-opus-mtp` | `Qwopus3.6-27B-v1-preview-MTP-IQ3_M.gguf` | 65536 | `q4_0` | none | success | 67.39 | 39.22 | not exposed | ok |  |
| `qwen-heretic` | `qwen3.6-27b-heretic-mtp` | `Qwen3.6-27B-uncensored-heretic-v2-Native-MTP-Preserved-Q3_K_M.gguf` | 65536 | default | none | error | 57.31 | 39.99 | not exposed | mismatch | sanity mismatch |
| `qwen-heretic` | `qwen3.6-27b-heretic-mtp` | `Qwen3.6-27B-uncensored-heretic-v2-Native-MTP-Preserved-Q3_K_M.gguf` | 65536 | `q8_0` | none | error | 70.13 | 39.67 | not exposed | mismatch | sanity mismatch |
| `qwen-heretic` | `qwen3.6-27b-heretic-mtp` | `Qwen3.6-27B-uncensored-heretic-v2-Native-MTP-Preserved-Q3_K_M.gguf` | 65536 | `q4_0` | none | error | 78.99 | 36.56 | not exposed | mismatch | sanity mismatch |

## Recommendations

| Family | Recommendation | Rationale |
| --- | --- | --- |
| `qwen` | default | All modes passed sanity; default had the best decode throughput at 59.05 tok/s. |
| `qwen-hauhau` | default | All modes passed sanity; default had the best decode throughput at 139.18 tok/s. |
| `qwen-27b-hauhau` | default | All modes passed sanity; default had the best decode throughput at 64.39 tok/s. |
| `gemma-hauhau` | inconclusive | All modes loaded and produced metrics, but all sanity probes mismatched. Default decode was fastest, but the prompt behavior needs separate validation. |
| `qwen-27b` | inconclusive | All modes loaded and produced metrics, but all sanity probes mismatched. Decode differences were small, with `q4_0` slightly ahead of default. |
| `qwen-coder` | q4_0 | All modes passed sanity; `q4_0` had the best decode throughput at 102.72 tok/s. Treat this as a follow-up candidate, not a promoted default, because this is one short probe. |
| `gemma` | default | All modes passed sanity; default had the best decode throughput at 60.32 tok/s. |
| `gemma-vision` | default | All modes passed sanity; default had the best decode throughput at 58.36 tok/s. |
| `gpt-oss` | default | Default and `q8_0` passed sanity; default had the best decode throughput at 128.33 tok/s. `q4_0` mismatched the sanity probe. |
| `deepseek-r1` | inconclusive | All modes loaded and produced metrics, but all sanity probes mismatched. Default decode was fastest, but prompt behavior needs separate validation. |
| `qwen-opus` | default | All modes passed sanity; default had the best decode throughput at 42.39 tok/s. |
| `qwen-heretic` | inconclusive | All modes loaded and produced metrics, but all sanity probes mismatched. Default decode was slightly fastest. |

## Promotion Summary

No launchers should change immediately from this report, and this task did not promote launcher defaults in code.

Possible later work: rerun a longer `qwen-coder` benchmark with `q4_0/q4_0` KV and a more representative coding prompt. If it repeats the decode improvement without quality regressions, the `qwen-coder` launcher family is the only candidate from this data for a future explicit KV default. All other sane comparisons favor keeping default KV. Families with sanity mismatches should first get prompt/template validation rather than KV promotion.

## Raw Data Notes

- `/tmp/installed-kv-pass1.tsv` existed and captured the initial default plus `q8_0` pass.
- `/tmp/installed-kv-q4.tsv` was generated with `RUN_Q4=1` and includes default, `q8_0`, and `q4_0` for all 12 families; it is the source of the table above.
- Empty `kv_log` fields mean the logs did not expose KV buffer parse data in this runner.
- `error` rows in this report are exact-output sanity mismatches, not observed OOM or load failures.
