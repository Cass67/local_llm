# Multi-GPU parallelism on the 7900s: measurements and decisions (2026-07-30)

Record of the investigation that produced lltop's **Split / parallelism** panel
(commits `803f5d3`, `0445691`). Companion doc:
[tinygrad-rdna3-plan-2026-07-30.md](tinygrad-rdna3-plan-2026-07-30.md).

Hardware at time of measurement: 2× RX 7900 XT (`03:00.0`, `06:00.0`) + Tesla P40
(`07:00.0`), Vulkan runner `7900sv` serving Qwen3.6-27B Fable-Fusion Q8_0,
`--split-mode layer --tensor-split 1,0.92`, 92k ctx, q8 KV, MTP + ngram-mod.

> **Final outcome:** sections 1–10 preserve investigation chronology. Section 11
> supersedes their cross-backend performance conclusions. Forced-hipBLAS
> ROCm+RCCL tensor mode at 92k/ubatch 512 completed the representative request in
> 18.03–18.64 s versus Vulkan's 31.70 s and became production. Canonical benchmark:
> [Local RCCL result](#local-rccl-result).

---

## 1. Why rocm-smi/amd-smi wasted our time

`gpu_busy_percent` (what rocm-smi, amd-smi, and nvtop all read) is a **single
instantaneous sample**. Under a layer split each card is busy in millisecond
bursts, so the value is bimodal and one read per second is a coin flip.

Sampled at ~200 Hz for 3 s under load, 590 samples per card:

| | `03:00.0` (panel showed 0%) | `06:00.0` (panel showed 32%) |
|---|---|---|
| reads that were 0% | **49%** | 39% |
| reads that were ≥90% | 38% | 33% |
| median | **6.5%** | 50% |
| mean of 590 reads | 44.1% | 48.1% |
| fdinfo engine% (integrated) | 41.0% | 53.9% |

The mean matches fdinfo within noise. **sysfs isn't wrong about the number, it's
unusable at one sample per second.** No amount of patching the *smi tools helps —
the metric has no accumulator.

Same cause for `SCLK S: 35Mhz` alongside 108 W draw: `pp_dpm_sclk` is one
instantaneous DPM level. Real clock via `hwmon/freq1_input` swings 25 → 1757 MHz.

## 2. The instrument that works: DRM fdinfo

`/proc/<pid>/fdinfo/*` for amdgpu exposes per-client, per-PCI-device
**cumulative** counters: `drm-engine-gfx`, `drm-engine-compute` (ns),
`drm-memory-vram`, keyed by `drm-pdev` + `drm-client-id`.

- Dedupe by `(drm-pdev, drm-client-id)` — every fd of a client repeats identical
  counters.
- Host `/proc` needs root for container processes, so read it through
  `docker exec <runner> sh -c 'cat /proc/1/fdinfo/*'` (~46 ms, docker group is
  enough). Split config comes from `/proc/1/cmdline` in the same exec.
- Deltas over a 1 s window integrate every burst, so phase is irrelevant — it
  cannot alias.

Derived headline metric: **aggregate GPU-equivalents** = Σ per-GPU engine% / 100.

## 3. Layer split cannot exceed ~1.00 GPU-equiv

Decode, steady state: `0.91–1.01 / 2.00`, per-card 40–56%.

Prompt processing, 5 Hz sampling — clean alternation, never overlap:

```
03:00.0    0.0%  06:00.0   94.1%
03:00.0   97.0%  06:00.0    0.0%
03:00.0    0.0%  06:00.0  101.3%
03:00.0  109.0%  06:00.0    0.0%
peak aggregate 1.15 GPU-equiv
```

Each card *can* be pegged; they're just never pegged simultaneously. The 40–56%
figures are each card's **share of the alternation**, not per-card inefficiency.
Aggregate ≈1.0 also means the pipeline is nearly gapless — one GPU is almost
always busy, never both.

## 4. `--parallel` does not create device overlap

Scratch runner, Qwen2.5-1.5B Q4 layer-split across both x16 cards, own container
on port 8090, `7900sv` idle and verified before/after.

| config | concurrent reqs | agg p90 | agg max | wall |
|---|---|---|---|---|
| `--parallel 1` | 4 (queued) | 0.88 | 0.89 | 7.0 s (4×300 tok) |
| `--parallel 4` | 2 | 0.84 | 0.84 | 2.8 s |
| `--parallel 4` | 4 | 0.84 | 0.84 | 4.4 s |
| `--parallel 4` | 8 | 0.84 | 0.85 | 7.6 s (8×300 tok) |

Aggregate never budges across slots 1→4 and concurrency 2→8. Throughput does:

- `--parallel 1`, 4 reqs → ~171 tok/s
- `--parallel 4`, 4 reqs → ~273 tok/s (**1.6×**)
- `--parallel 4`, 8 reqs → ~316 tok/s (**1.85×**)

**Batching buys 1.85× more work out of the same GPU-seconds. It never buys more
GPU-seconds.** llama.cpp widens the batch; it does not deepen the pipeline. One
batch traverses device 0 then device 1, and no second microbatch exists to fill
the idle stage. (0.85 rather than 1.00 here because a 1.5B has proportionally
more per-token CPU/sync overhead than the 27B's 0.91–1.01.)

Still worth raising `--parallel` for concurrent agent traffic — for arithmetic
intensity, not utilization.

## 5. Decode is memory-bound, so "engine 100%" ≠ maxed

Under decode load: SCLK 1194–1496 MHz (200 Hz mean 832 / 688 MHz, peak 1863)
against ~2400 MHz boost, while **MCLK sits pinned at its top DPM state**.
Firmware won't raise core clock because shaders are waiting on VRAM.

29 GiB of Q8_0 weights stream per forward pass; at one token in flight every
matmul is a GEMV, ~1 weight byte per FLOP. RDNA3 needs arithmetic intensity in
the tens before ALUs bind. That's why prefill (`-b 4096`) hits 100% engine and
high clocks while decode doesn't — batching is the only lever on intensity.

## 6. PCIe topology

| slot | link | note |
|---|---|---|
| `03:00.0` | Gen4 x16 | |
| `06:00.0` | Gen4 x16 | |
| `07:00.0` | **OCuLink Gen3 x4** | 3.94 GB/s theoretical, ~3.2–3.5 practical. `nvidia-smi` reports gen.max 3 / width.current 4; a `LnkSta` of 2.5GT/s is idle downtraining, not the cap |

**Correction to an earlier claim in this session:** Gen3 x4 does *not* bottleneck
layer-split decode. One boundary per card pair carries a single hidden state per
token — ~10 KB at ~5K dims f16, ~0.5 MB/s at 50 tok/s, four orders of magnitude
under the link. Even the Gen1 x4 it idles at is ~2000× that.

Where x4 actually costs:
- **prefill** — `5120 × 4096 × 2` ≈ 42 MB per boundary per chunk, ~11 ms at
  3.9 GB/s against a few hundred ms of chunk compute → low single-digit %
- **model load** — 16 GiB ≈ 5 s of link time, likely hidden behind disk
- **latency** — OCuLink retimer hop on every per-token sync. Small transfers at
  high frequency are latency-bound. Real but modest.

Tensor parallelism is the case where the x4 link does bite: 2 all-reduces per
layer, ~128 round-trips per token. Bandwidth is fine (~85 MB/s at 50 tok/s);
128 × ~30 µs ≈ 4 ms/token of sync against a ~20 ms budget is the tax. NVLink is
single-digit µs, which is what datacenter interconnect actually buys.

## 7. Hardware change: P40 → third 7900 XT

Target: 3× 20 GiB homogeneous, all Vulkan, 60 GiB total. Consequences:

- CUDA cluster `ffeb3c8f` and the cuda runner backend become dead.
- The existing `P40v` cluster (vulkan, `07:00.0`, port 8082) is already the right
  shape post-swap — rename, load a suitable model.
- Router needs **no rule edits**: 15 rules name `P40` as cluster or fallback, and
  `router_rules.json` supports `cluster_remap`, so one line repoints them.
- **The easy/hard tier taxonomy loses its premise.** It exists because the P40 was
  slow. Three identical cards means routing by *model role*, not hardware tier;
  rule names like "web & internet search → weak cluster" will read as misleading.

## 8. Lane layout for 3 cards

Per-card budget ~19 GiB usable. Approximate fits:

| lane | fits |
|---|---|
| 1 card (~19 GiB) | 27B Q4_K_M ≈ 16.5 GiB + q8 KV at ~32–48k ctx (tight); 12–14B Q8 comfortable |
| 2 cards (~38 GiB) | 27B Q8 29 GiB + ~5 GiB KV at 92k ctx — the current `7900sv` |
| 3 cards (~57 GiB) | 40B Q8 or 70B Q4 — capacity only, still 1.00 GPU-equiv |

**Revised decision:** the two primary cards now run one ROCm+RCCL tensor lane for
the 27B Q8 model; one interactive stream can use both cards concurrently. Card 3
should still start as its own single-card lane on `07:00.0`. Do not add its Gen3 x4
link to the RCCL group until a three-way benchmark beats the two-card result; the
collective tax, not layer-split behavior, is now the concern.

### Keeping two lanes coherent

- Same family at a lower quant (27B Q4_K_M on the single card) keeps tokenizer,
  template, and persona aligned — style stays consistent, fidelity drops.
- Pin identical across lanes: quant family, jinja template, system prompt, sampler
  params, `--reasoning`. Spec decoding and `--cache-reuse` are output-neutral.
- **Two replicas of the same model is not supported today.** `_cluster_to_model` is
  cluster → one alias, rules select by content, and there's no least-busy or
  round-robin; the reverse alias→cluster lookup would be ambiguous. Would need
  in-flight-slot selection **plus** conversation stickiness — without stickiness
  every follow-up turn lands on the cold replica and reprocesses the whole prompt,
  losing more to cache misses than the second card gains.
- Different models per lane works today via the tier ratchet: it re-evaluates
  against full message history each turn, so a session stays on one cluster.

## 9. Why other stacks don't have this ceiling

| stack | multi-GPU mode | maxes cards? | RDNA3 today |
|---|---|---|---|
| llama.cpp layer split | PP, depth 1 | no, ~1.0 GPU-equiv | what we run |
| vLLM / SGLang TP | all-reduce per layer | yes, needs fast interconnect | CDNA-targeted; gfx1100 unofficial |
| vLLM / SGLang PP | microbatched stages | yes, with concurrency | same problem |

Two mechanisms break 1.00: tensor parallel collectives or pipeline parallel
**with multiple microbatches in flight** (stage 1 on request B while stage 2 works
on request A). llama.cpp layer split has neither, but its ROCm tensor mode plus
RCCL does: two-card target inference now overlaps successfully despite separate
Gen3 x8 root ports.

vLLM's ROCm path remains CDNA-oriented and gfx1100 support remains community-grade.
The production TP stack found here is llama.cpp+RCCL, not vLLM/SGLang. Three-card
TP over the additional Gen3 x4 OCuLink remains unmeasured and should not replace
an independent third lane by assumption.

## 10. tinygrad's actual position

What customers use it for, none of it LLM serving:

1. **comma.ai / openpilot** — tinygrad replaced the model runtime so the driving
   model runs on the comma three's Snapdragon 845 GPU. Value is compiling a small
   vision model onto oddball silicon with almost no dependencies.
2. **tinybox as training iron** — local FLOPS instead of rented tokens, MLPerf
   *Training* results competitive with systems ~10× the price.
3. **Backend portability / driver sovereignty** — CUDA, AMD, Metal, QCOM, WebGPU
   from one ~12k-line stack, own RDNA3 userspace driver (AM) underneath.

This box has the opposite serving profile: optimized llama.cpp ROCm+RCCL now beats
Vulkan here and already provides continuous batching, prefix cache reuse, and MTP,
none of which tinygrad provides.

**tinygrad becomes interesting here the day a fine-tune is on the roadmap**, not
the day we want faster inference. Training is batched by nature, so the pipeline
ceiling doesn't apply, and sharding across three cards is exactly what tinybox red
exists to run. Evaluation plan with kill criteria:
[tinygrad-rdna3-plan-2026-07-30.md](tinygrad-rdna3-plan-2026-07-30.md).

---

## 11. Follow-up: RCCL changes the tensor-parallel conclusion

The ROCm tensor test in §9 used HIP peer copies but the build did **not** include
RCCL. Current llama.cpp has a separate all-reduce path enabled at build time with
`-DGGML_HIP_RCCL=ON`; it is disabled by default because upstream found it was not
universally beneficial.

External results posted on llama.cpp draft PR
[#25051](https://github.com/ggml-org/llama.cpp/pull/25051) used Qwen3.6-27B Q4_K_L
on Radeon Pro W7900 (RDNA3/gfx1100):

| mode | GPUs | pp512 tok/s | tg128 tok/s |
|---|---:|---:|---:|
| ROCm layer | baseline | 843.56 | 28.52 |
| ROCm tensor + RCCL | 2 | 1429.22 | 37.50 |
| ROCm tensor + RCCL | 4 | 1992.92 | 45.54 |
| ROCm tensor + RCCL | 5 | 2033.37 | 48.57 |

Two-card RCCL tensor measured 1.69× baseline prefill and 1.31× baseline decode.
This invalidates the claim that llama.cpp/RDNA3 cannot scale one request beyond
one GPU; it does **not** prove the same gain on ubt26.

ubt26-specific constraints and their resolution:

- Both primary RX 7900 XTs sit behind separate Gen3 x8 root ports (~7.9 GB/s
  theoretical), regardless of their Gen4 x16 card-facing links. Two-card RCCL
  still wins decisively on the measured workload.
- The planned third card's OCuLink Gen3 x4 path should remain an independent lane
  unless a benchmark disproves the expected collective bottleneck.
- Tensor mode cannot auto-fit and requires f16/bf16 KV. Manual fitting proved the
  production Q8 model fits at 92,160 context; ubatch, not context alone, determines
  safe request-time headroom.
- Build space was reclaimed, then a ROCm 7.2/RCCL 2.27.7 image was built with
  `-DGGML_HIP_RCCL=ON`.
- The Vulkan TP work in PR #25051 remains draft. Its AMD direct-DMA path regressed
  badly and was removed; do not revive the local Vulkan peer-copy patches.

The executed test plan compared layer/tensor modes, synthetic prefill/decode,
32k and 92k contexts, ubatch 512–2048, realistic requests, repeated-request
stability, VRAM headroom, power, and correctness. The acceptance threshold was
15% lower end-to-end latency; the final profile improved it by 41–43%.

### Local RCCL result

Built llama.cpp `9ebfc3a` with ROCm 7.2 and RCCL 2.27.7. That sha was pinned in
`runner/rocm/Dockerfile` on the belief that an earlier llama.cpp was faster; that
finding did not hold up, so the pin was removed and the ROCm runner tracks
`master` like the Vulkan and CUDA runners. The sha below is only what these
numbers were measured on. The production Q8
model fit at 92,160 context with f16 KV, MTP+ngram, and mmproj: 19.29/18.15 GiB
VRAM used. RCCL initialized both cards correctly.

`llama-bench`, same ROCm build and Q8 model:

| mode | pp512 | pp4096 | tg128 |
|---|---:|---:|---:|
| ROCm layer | 165.41 | 273.11 | 18.93 |
| ROCm tensor + RCCL | 285.96 | 281.10 | 31.26 |

RCCL gives real parallel decode and short-prefill scaling. Long prefill barely
moves because communication/backend overhead catches compute gain.

Real full-profile request, 5,431 prompt tokens + 400 generated tokens:

| mode | clock cap | e2e | prefill | decode |
|---|---:|---:|---:|---:|
| ROCm layer | 1900 MHz | 36.95 s | 233.64 t/s | 29.26 t/s |
| ROCm tensor + RCCL | 1500 MHz | 40.49 s | 182.74 t/s | 37.26 t/s |
| ROCm tensor + RCCL | 1900 MHz | 35.10 s | 217.13 t/s | 39.76 t/s |
| live Vulkan layer | 1900 MHz | **31.70 s** | **388.10 t/s** | 22.65 t/s |

Reducing context alone did not solve the initial prefill gap: the 32k baseline
still took 34.89 s at 216.6 prefill t/s and 40.9 decode t/s. Kernel selection was
the missing lever.

The first uncapped simultaneous-load attempt hard-reset the host while lltop
showed ~488 W combined GPU socket power and ~2.9 GHz. Reapplying the persisted
1900 MHz OD ceiling made the repeat stable at 306 W combined peak and ~1.995 GHz
observed. PSU is a Seasonic SSR-850FX 850 W; each GPU uses its own PSU cable.
Third card is planned on a separate 800 W eGPU PSU.

That conclusion was superseded by the kernel sweep. Current upstream uses the
CUDA-named `GGML_CUDA_FORCE_CUBLAS` option for both CUDA and HIP; the apparent
HIP-specific `GGML_HIP_FORCE_MMQ` option is fork-specific and compiled a
byte-identical binary on mainline.

Forced hipBLAS (`-DGGML_CUDA_FORCE_CUBLAS=ON`) was the missing prefill fix:

| tensor kernel / ubatch | pp4096 | tg128 |
|---|---:|---:|
| auto/MMQ, 512 | 233.01 | 28.61 |
| auto/MMQ, 2048 | 271.44 | 28.60 |
| forced hipBLAS, 512 | 791.21 | 28.61 |
| forced hipBLAS, 1024 | 824.40 | 28.59 |
| forced hipBLAS, 2048 | **876.71** | 28.61 |

Forced MMQ was within 0.4% of auto, proving auto already selected the same path.
The current upstream commit has no active `GGML_HIP_ROCWMMA_FATTN` CMake path, so
that proposed variant was dropped rather than benchmarking another no-op image.

Real full-profile results with forced hipBLAS:

| context / ubatch | e2e | prefill | decode | minimum free VRAM |
|---|---:|---:|---:|---:|
| 32k / 2048 | **17.37 s** | 728.59 t/s | 40.44 t/s | 2.37 GiB |
| 92k / 1024 | 17.69 s | 687.89 t/s | 40.98 t/s | 0.36 GiB after request |
| 92k / 512, 3 runs | 18.03–18.64 s | 669.51–686.86 t/s | 38.55–42.05 t/s | 0.77 GiB |
| live Vulkan 92k / 512 | 31.70 s | 388.10 t/s | 22.65 t/s | — |

**Final decision:** deploy forced-hipBLAS ROCm+RCCL tensor at 92k/ubatch 512. It
is 41–43% faster end-to-end than the Vulkan profile while retaining full context
and surviving three distinct full requests. Ub1024 is faster but its 363 MiB
headroom is rejected; ub2048 at 92k died during the request. Keep Vulkan
`balanced` and its image as rollback. The MTP draft context emits an RCCL-init
fallback warning because that context is single-device; target-model tensor RCCL
continues to operate.

### KV cache must stay f16 under RCCL

The `rccl` profile runs `--cache-type-k f16 --cache-type-v f16`, and that is not
an oversight carried over from benchmarking — tensor split + RCCL requires it.
Do not copy the q8_0 KV tuning from the Vulkan `balanced` profile, which uses
`split_mode: layer` and is free to quantize. The cost is VRAM: f16 KV at 92,160
context is what puts the pair at 19.29/18.15 GiB, so there is no headroom to
raise context without dropping back to layer split.

This bit once already: the UI opened on `balanced` (q8_0 KV, layer split) while
the live RCCL runner was on `rccl` (f16 KV, tensor split), which reads as a
config drift bug but is just two profiles in one family. The family default is
now `rccl` so the UI opens on the profile that is actually serving.

Active deployment:

- image: `local-llm-runner-rocm:latest` (same image as experimental `:cublas`)
- cluster: `7900srccl`, ROCm, port 8086
- profile: `rccl` (family default); Vulkan `balanced` retained
- router remap: `7900sv` → `7900srccl`
- tuning: 1900 MHz / -75 mV / 238+253 W

Artifacts on ubt26:

- initial llama-bench: `~/bench-results/rocm-rccl-q8-20260730-141422/`
- kernel sweep: `~/bench-results/rocm-rccl-cublas-ub2048-20260730-152041/`
- 32k maximum-speed test: `~/bench-results/rocm-rccl-cublas-real-20260730-152513/`
- 92k stability: `~/bench-results/rocm-rccl-cublas-92k-stability-20260730-152918/`

This section is the canonical result; the Vulkan and continuous-batching benchmark
docs link here where their older cross-backend conclusions are superseded.

### Three-card RCCL follow-up

A third RX 7900 XT was added at `09:00.0` behind the PCH's Gen3 x4 root port;
the original pair remain behind separate Gen3 x8 root ports. The three-card
profile used tensor split `1,1,1` at the same 92k/ubatch-512 shape.

Initial RCCL startup failed because Docker's default 64 MiB `/dev/shm` was too
small. `NCCL_DEBUG=INFO` showed ring construction succeeding, then
`failed to extend /dev/shm/...: No space left on device`. Raising runner
`ShmSize` to 1 GiB allowed RCCL to initialize and consumed about 216 MiB; no
butterfly/internal-all-reduce fallback warnings remained.

That did **not** make three-way execution viable. First full requests caused an
abrupt host reboot before completion, both before and after:

- adding `iommu=pt` (IOMMU default domain changed from translated to passthrough),
- tuning all three cards to 1900 MHz / -75 mV,
- capping them at 238/253/238 W, and
- using the exact forced-hipBLAS cublas image from the successful two-card run.

No amdgpu fault/reset was persisted before either reboot. AMD topology reports
P2P disabled between every pair; RCCL therefore uses shared-memory/host transport,
and the third card is additionally separated behind the PCH x4 path and its own
IOMMU group. **Decision: reject three-card RCCL tensor mode on this topology.**
Keep `03:00.0` + `06:00.0` as the production RCCL pair and use `09:00.0` as an
independent lane. The 1 GiB runner shm fix remains correct and required for larger
RCCL communicators, but does not override the hardware/topology failure.

References: [upstream multi-GPU guide](https://github.com/ggml-org/llama.cpp/blob/master/docs/multi-gpu.md),
[RCCL](https://github.com/ROCm/rccl), and an example of current RX 7900 XT tensor
mode immaturity ([#22793](https://github.com/ggml-org/llama.cpp/issues/22793)).

---

## Open decisions

- Whether `07:00.0` stays permanently excluded from TP experiments (recommend yes,
  §6).
- Whether to add least-busy + sticky-session routing, which is the prerequisite for
  same-model replicas (§8).
- Whether to rework the router rule taxonomy once the tier premise is gone (§7).
