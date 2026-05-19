# Hauhau Models Benchmark

## Environment

- Host: `ubt26`
- GPU: RX 7900 XT, 20GB VRAM
- Runtime: llama.cpp server from `/home/cass/llama.cpp`
- Existing `llama-server.service` had to be stopped before benchmarking.

## Results

| Family | Repo | GGUF | mmproj | Profile | Context | Status | Prompt tok/s | Decode tok/s |
| --- | --- | --- | --- | --- | ---: | --- | ---: | ---: |
| `qwen-27b-hauhau` | `HauhauCS/Qwen3.6-27B-Uncensored-HauhauCS-Aggressive` | `Qwen3.6-27B-Uncensored-HauhauCS-Aggressive-IQ4_XS.gguf` | yes | `reliable` | 65536 | completion OK | 116.81 | 33.57 |
| `glm-hauhau` | `HauhauCS/GLM-4.7-Flash-Uncensored-HauhauCS-Aggressive` | `GLM-4.7-Flash-Uncensored-HauhauCS-Aggressive-Q4_K_M.gguf` | no | `balanced`/`reliable` | 49152 | completion OK | 74.60 | 65.15 |
| `gemma-hauhau` | `HauhauCS/Gemma4-26B-A4B-Uncensored-HauhauCS-Balanced` | `Gemma4-26B-A4B-Uncensored-HauhauCS-Balanced-IQ4_XS.gguf` | yes | `reliable` | 65536 | completion OK | 114.49 | 91.89 |

## Notes

- Qwen 27B Hauhau loaded its multimodal projector and completed at 65k context.
- Gemma Hauhau loaded its multimodal projector and completed at 65k context.
- GLM Hauhau `reliable` at 65k OOMed and segfaulted during allocation. The stable context is 49k, so `reliable` was reduced to 49152.
- GLM first pull was incomplete during the earliest attempt; after the model file was cached enough to load, 49k completed successfully.

## Installed Shortcuts

- `oc-qwen-27b-hauhau`, plus profile variants
- `oc-glm-hauhau`, plus profile variants
- `oc-gemma-hauhau`, plus profile variants
