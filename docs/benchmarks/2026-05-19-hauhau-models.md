# Hauhau Models Benchmark

Historical benchmark record: hostnames and paths in this report describe the machine used for this dated run, not public defaults.

## Environment

- Host: `ubt26`
- GPU: RX 7900 XT, 20GB VRAM
- Runtime: llama.cpp server from `/home/cass/llama.cpp`
- Existing `llama-server.service` had to be stopped before benchmarking.

## Results

| Family | Repo | GGUF | mmproj | Profile | Context | Status | Prompt tok/s | Decode tok/s |
| --- | --- | --- | --- | --- | ---: | --- | ---: | ---: |
| `qwen-27b-hauhau` | `HauhauCS/Qwen3.6-27B-Uncensored-HauhauCS-Aggressive` | `Qwen3.6-27B-Uncensored-HauhauCS-Aggressive-IQ4_XS.gguf` | yes | `reliable` | 65536 | completion OK | 116.81 | 33.57 |
| `gemma-hauhau` | `HauhauCS/Gemma4-26B-A4B-Uncensored-HauhauCS-Balanced` | `Gemma4-26B-A4B-Uncensored-HauhauCS-Balanced-IQ4_XS.gguf` | yes | `reliable` | 65536 | completion OK | 114.49 | 91.89 |

## Notes

- Qwen 27B Hauhau loaded its multimodal projector and completed at 65k context.
- Gemma Hauhau loaded its multimodal projector and completed at 65k context.
- GLM Hauhau was removed after follow-up testing. Although it loaded at 49k, it produced only slash characters (`////////////`) through both the embedded template and forced `chatglm4`, so it is not promoted.

## Installed Shortcuts

- `oc-qwen-27b-hauhau`, plus profile variants
- `oc-gemma-hauhau`, plus profile variants
