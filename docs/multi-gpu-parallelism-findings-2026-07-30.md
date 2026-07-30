# Multi-GPU parallelism on the 7900s: measurements and decisions (2026-07-30)

Record of the investigation that produced lltop's **Split / parallelism** panel
(commits `803f5d3`, `0445691`). Companion doc:
[tinygrad-rdna3-plan-2026-07-30.md](tinygrad-rdna3-plan-2026-07-30.md).

Hardware at time of measurement: 2× RX 7900 XT (`03:00.0`, `06:00.0`) + Tesla P40
(`07:00.0`), Vulkan runner `7900sv` serving Qwen3.6-27B Fable-Fusion Q8_0,
`--split-mode layer --tensor-split 1,0.92`, 92k ctx, q8 KV, MTP + ngram-mod.

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

**Decision: independent lanes.** `7900sv` keeps the two x16 cards and the 27B Q8
with the tuned MTP config; card 3 runs its own single-card lane on `07:00.0`.
Aggregate ceiling goes 1.00 → 2.00 GPU-equiv, but **only with ≥2 concurrent
requests** — one interactive stream still lights one lane.

Do not grow `7900sv` into a 3-card lane. Not for PCIe reasons (see §6) but
because layer split can't exceed 1.00 GPU-equiv regardless of wiring.

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

Two mechanisms break 1.00: tensor parallel (needs interconnect on the order of
VRAM bandwidth — NVLink ~1.8 TB/s) or pipeline parallel **with multiple
microbatches in flight** (stage 1 on request B while stage 2 works on request A).
llama.cpp has neither. It's not a hardware or interconnect ceiling — it's a
scheduler that doesn't pipeline.

vLLM's ROCm path targets CDNA (MI200/MI300); gfx1100 is community-grade. No
production TP stack exists for RDNA3 — MLC wants RCCL, ExLlama's TP is
NVIDIA-first. On this box "max 3 cards" realistically means three independent
lanes, not one fast model.

## 10. tinygrad's actual position

What customers use it for, none of it LLM serving:

1. **comma.ai / openpilot** — tinygrad replaced the model runtime so the driving
   model runs on the comma three's Snapdragon 845 GPU. Value is compiling a small
   vision model onto oddball silicon with almost no dependencies.
2. **tinybox as training iron** — local FLOPS instead of rented tokens, MLPerf
   *Training* results competitive with systems ~10× the price.
3. **Backend portability / driver sovereignty** — CUDA, AMD, Metal, QCOM, WebGPU
   from one ~12k-line stack, own RDNA3 userspace driver (AM) underneath.

This box has the opposite profile on both axes: a mature-kernel target (Vulkan
beats ROCm here, measured) and an interactive serving workload wanting continuous
batching, prefix cache reuse, and MTP — none of which tinygrad provides.

**tinygrad becomes interesting here the day a fine-tune is on the roadmap**, not
the day we want faster inference. Training is batched by nature, so the pipeline
ceiling doesn't apply, and sharding across three cards is exactly what tinybox red
exists to run. Evaluation plan with kill criteria:
[tinygrad-rdna3-plan-2026-07-30.md](tinygrad-rdna3-plan-2026-07-30.md).

---

## Open decisions

- Whether `07:00.0` stays permanently excluded from TP experiments (recommend yes,
  §6).
- Whether to add least-busy + sticky-session routing, which is the prerequisite for
  same-model replicas (§8).
- Whether to rework the router rule taxonomy once the tier premise is gone (§7).
