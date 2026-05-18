# Heretic Context Benchmark

## Result

`qwen-heretic` cannot reach 196k or 256k context on the RX 7900 XT with full GPU offload in the tested quants. The largest context that loaded and completed a small request was 131072 tokens with `IQ2_M`.

## Matrix

| Quant | Context | Status | Model MiB | KV MiB | RS MiB | Compute MiB | Prompt tok/s | Decode tok/s | Reason |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Q4_K_M | 65536 | loaded | 15387.77 | 4096.00 | 598.50 | 61.88 | 102.59 | 24.32 | completion_ok |
| Q4_K_M | 98304 | fail | 15387.77 | | | | | | oom |
| Q4_K_M | 131072 | fail | 15387.77 | | | | | | oom |
| Q4_K_M | 196608 | fail | 15387.77 | | | | | | oom |
| Q4_K_M | 262144 | fail | 15387.77 | | | | | | oom |
| Q4_K_S | 65536 | loaded | 14471.21 | 4096.00 | 598.50 | 61.88 | 94.25 | 24.87 | completion_ok after extended timeout rerun |
| Q4_K_S | 98304 | fail | 14471.21 | | | | | | oom |
| Q4_K_S | 131072 | fail | 14471.21 | | | | | | oom |
| Q4_K_S | 196608 | fail | 14471.21 | | | | | | oom |
| Q4_K_S | 262144 | fail | 14471.21 | | | | | | oom |
| IQ4_XS | 65536 | loaded | 14029.34 | 4096.00 | 598.50 | 61.88 | 114.09 | 32.92 | completion_ok after extended timeout rerun |
| IQ4_XS | 98304 | fail | 14029.34 | 6144.00 | | | | | oom |
| IQ4_XS | 131072 | fail | 14029.34 | | | | | | oom |
| IQ4_XS | 196608 | fail | 14029.34 | | | | | | oom |
| IQ4_XS | 262144 | fail | 14029.34 | | | | | | oom |
| IQ3_M | 65536 | loaded | 11762.52 | 4096.00 | 598.50 | 61.88 | 64.50 | 24.00 | completion_ok |
| IQ3_M | 98304 | loaded | 11762.52 | 6144.00 | 598.50 | 61.88 | 71.74 | 24.87 | completion_ok |
| IQ3_M | 131072 | fail | 11762.52 | 8192.00 | | | | | oom |
| IQ3_M | 196608 | fail | 11762.52 | | | | | | oom |
| IQ3_M | 262144 | fail | 11762.52 | | | | | | oom |
| IQ2_M | 65536 | loaded | 9469.08 | 4096.00 | 598.50 | 61.88 | 71.78 | 25.40 | completion_ok |
| IQ2_M | 98304 | loaded | 9469.08 | 6144.00 | 598.50 | 61.88 | 79.44 | 25.48 | completion_ok |
| IQ2_M | 131072 | loaded | 9469.08 | 8192.00 | 598.50 | 65.94 | 79.41 | 25.36 | completion_ok |
| IQ2_M | 196608 | fail | 9469.08 | | | | | | oom |
| IQ2_M | 262144 | fail | 9469.08 | | | | | | oom |

## Recommendation

Do not add a 196k or 256k `qwen-heretic` profile for full GPU offload on the RX 7900 XT. Add a 128k stretch profile only if `IQ2_M` quality is acceptable. Keep the current 65k `Q4_K_M` reliable profile for quality, use `IQ4_XS` as the fastest measured 65k profile, and use `IQ3_M` or `IQ2_M` for longer-context experiments.

The 256k target would require lower memory than `IQ2_M` full offload, partial CPU offload, fewer context buffers if llama.cpp exposes safe options, or more VRAM/multiple GPUs.
