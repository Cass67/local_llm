# MTP Benchmark - 2026-05-18

## Summary

Clean MTP benchmarking identifies Qwen-family promotion candidates that completed a short MTP throughput run at `spec_draft_n_max=2`. These should only be promoted after quality smoke testing and baseline comparison, unless Task 5 separately validates those checks. The safest selected setting is `spec_n=2` for every successful family: it had the best decode TPS for all successful candidates, while `qwen-mtp` and `qwen-27b-mtp` loaded at `spec_n=4` but decoded slower. `spec_n>=8` OOMed for every tested candidate.

Other families remain unchanged because they were not benchmarked; no suitable MTP candidate was identified during search for this hardware/profile target.

The contaminated initial run was discarded for decision-making and preserved as `mtp-results-initial.csv` only for traceability. It was started while Gemma or another `llama-server` process was already loaded on the GPU, and it used earlier higher-quant candidate settings. The clean run used for this report is `mtp-results.csv`.

## Environment

| Field | Value |
| --- | --- |
| Host | `ubt26` |
| llama.cpp | `version: 9222 (9a532ae4b)` |
| Speculative mode | `--spec-type draft-mtp` |
| Sweep | `--spec-draft-n-max 2`, `4`, `8`, `12`, `16`, `24`, `32` |

Remote benchmark logs, when needed, are under `/home/cass/llama.cpp/bench-mtp/logs/<run_id>` on `ubt26`. This report does not claim those logs are locally preserved.

## Promotion Candidates

| Family | Status | Selected `spec_draft_n_max` | Rationale |
| --- | --- | ---: | --- |
| `qwen-mtp` | Promotion candidate pending quality/baseline validation | 2 | Highest clean decode TPS: 105.38 tok/s. `spec_n=4` loaded but decoded slower at 92.65 tok/s. |
| `qwen-27b-mtp` | Promotion candidate pending quality/baseline validation | 2 | Best clean decode TPS: 40.97 tok/s. `spec_n=4` loaded but decoded slower at 37.99 tok/s. |
| `qwen-heretic-mtp` | Promotion candidate pending quality/baseline validation | 2 | Clean `spec_n=2` completed at 38.89 tok/s; `spec_n=4` and above OOMed. |
| `qwen-opus-mtp` | Promotion candidate pending quality/baseline validation | 2 | Clean `spec_n=2` completed at 41.64 tok/s; `spec_n=4` and above OOMed. |

## Winners From Clean Run

Successful rows from `mtp-results.csv`:

| Family | Repo | GGUF | Ctx | Batch | UBatch | `spec_n` | Prompt TPS | Decode TPS |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `qwen-mtp` | `unsloth/Qwen3.6-35B-A3B-MTP-GGUF` | `Qwen3.6-35B-A3B-UD-IQ4_XS.gguf` | 65536 | 64 | 64 | 2 | 49.63 | 105.38 |
| `qwen-27b-mtp` | `unsloth/Qwen3.6-27B-MTP-GGUF` | `Qwen3.6-27B-Q3_K_M.gguf` | 65536 | 64 | 64 | 2 | 30.15 | 40.97 |
| `qwen-heretic-mtp` | `llmfan46/Qwen3.6-27B-uncensored-heretic-v2-Native-MTP-Preserved-GGUF` | `Qwen3.6-27B-uncensored-heretic-v2-Native-MTP-Preserved-Q3_K_M.gguf` | 65536 | 64 | 64 | 2 | 97.61 | 38.89 |
| `qwen-opus-mtp` | `noctrex/Qwopus3.6-27B-v1-preview-MTP-GGUF` | `Qwopus3.6-27B-v1-preview-MTP-IQ3_M.gguf` | 65536 | 64 | 64 | 2 | 54.28 | 41.64 |
| `qwen-mtp` | `unsloth/Qwen3.6-35B-A3B-MTP-GGUF` | `Qwen3.6-35B-A3B-UD-IQ4_XS.gguf` | 65536 | 64 | 64 | 4 | 50.92 | 92.65 |
| `qwen-27b-mtp` | `unsloth/Qwen3.6-27B-MTP-GGUF` | `Qwen3.6-27B-Q3_K_M.gguf` | 65536 | 64 | 64 | 4 | 39.11 | 37.99 |

## Not Benchmarked Or Unchanged Families

| Family | Status | Reason |
| --- | --- | --- |
| `qwen-coder` | Not benchmarked; leave unchanged | No suitable 30B coder MTP candidate identified during search. |
| `gemma` | Not benchmarked; leave unchanged | No obvious MTP GGUF candidate identified during search. |
| `gemma-vision` | Not benchmarked; leave unchanged | No obvious MTP GGUF candidate identified during search. |
| `gpt-oss` | Not benchmarked; leave unchanged | No obvious MTP GGUF candidate identified during search. |
| `deepseek-r1` | Not benchmarked; leave unchanged | No useful 32B distill MTP candidate identified during search. |

## Sweep Notes

| `spec_draft_n_max` | Result |
| ---: | --- |
| 2 | Successful for all four tested MTP candidates and best decode TPS for every successful family. |
| 4 | Loaded for `qwen-mtp` and `qwen-27b-mtp`, but decode TPS was lower than `spec_n=2`; OOMed for `qwen-heretic-mtp` and `qwen-opus-mtp`. |
| 8 | OOMed for all tested MTP candidates. |
| 12 | OOMed for all tested MTP candidates. |
| 16 | OOMed for all tested MTP candidates. |
| 24 | OOMed for all tested MTP candidates. |
| 32 | OOMed for all tested MTP candidates. |
