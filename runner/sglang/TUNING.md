# SGLang tuning on gfx1100 — where the tok/s actually is

Companion to `README.md`, which covers *getting it to run*. This is about
*making it fast*. Model under test is the live one: `Qwen3.8-27B-bf16`
(hybrid GDN), TP=4, triton attention, ctx 131072.

Measured 2026-09-17 with `scripts/bench-sglang.py`.

---

## 0. How to measure, or you will measure nothing

Three traps, each of which produced a wrong answer here before it was fixed:

1. **Random-word prompts are not a benchmark.** A junk prompt makes the model
   emit degenerate output, speculation then rejects every draft, and the same
   server measures **9.1 tok/s instead of 34.7**. `bench-sglang.py` slices a real
   corpus (repo sources) at a random offset instead.
2. **A repeated prompt hits the radix cache** and returns in under a second.
   Every request must be a fresh slice.
3. **Decode rate depends on prompt depth, hard** (see §1). A single shallow
   prompt — which is what `container/backend/measure.py` and therefore the
   `sweep.py` autotuner use — cannot see the largest effect on this box.

```bash
python3 ~/bench-sglang.py --kind fresh --depth 16384 --out 256 --reps 1
python3 ~/bench-sglang.py --kind echo  --depth 16384 --out 256 --reps 1
```

`fresh` = write new prose from a source excerpt (generation-shaped).
`echo` = repeat the excerpt verbatim (edit-shaped, what an agent actually does).
The two differ by 1.5–2.3× under speculation and must never be averaged.

---

## 1. The main finding: speculation is a *loss* past ~16k context

Unspeculated decode on this model is **flat with context** — GDN linear
attention does what it says:

| depth | nospec | EAGLE 3/1/4 | verdict |
|---|---|---|---|
| 2k fresh | 19.1 | **36.2** | spec wins 1.9× |
| 16k fresh | 18.6 | 20.4 | spec ~neutral |
| 64k fresh | **17.1** | 9.9 | **spec loses 42%** |
| 16k echo | 18.6 | 31.6 | spec wins 1.7× |
| 64k echo | 17.1 | 13.7 | **spec loses 20%** |

So the shipped `mtp` profile — which is what the cluster runs — is the fastest
config at short context and roughly **half speed** at 64k. Prefill is flat
~880–1020 tok/s everywhere and is not the problem.

`--speculative-adaptive` helps but does not fix this, because it adapts on
*acceptance*, not on wall-time: acceptance stays decent at depth while each
draft step gets more expensive, so it keeps drafting.

| config | 16k fresh | 16k echo | 64k fresh | 64k echo |
|---|---|---|---|---|
| EAGLE fixed 3/1/4 | 20.4 | 31.6 | 9.9 | 13.7 |
| + `--speculative-adaptive` | 20.8 | **47.4** | 8.7 | 20.1 |
| + adaptive, kv-splits 32, 0-step tier | 20.7 | 46.1 | 8.9 | **21.0** |

Adaptive is a large win on edit-shaped work (**+50% at 16k echo**) and a
partial rescue at 64k echo, at no real cost at 16k. It does not help fresh
generation at depth.

The adaptive candidate set is keyed by **batch size**, not context depth
(`adaptive_spec_params.py: DEFAULT_ADAPTIVE_CONFIG`), and the bs=1 tier is
`[1,3,5,7]` — it is structurally unable to switch speculation off for a single
user. Adding `0` to that tier via `--speculative-adaptive-config` is legal (the
zero-step path is implemented) but did not change the outcome, for the
wall-time-vs-acceptance reason above.

**A context-depth gate is the missing feature**, either as a local patch to the
tier selection or as two profiles with length-based routing.

---

## 2. Dials tested, with numbers

### Wins

| dial | effect |
|---|---|
| `--speculative-adaptive` | +50% at 16k echo, +47% at 64k echo |
| `--triton-attention-num-kv-splits 32` (default 16) | +7% at 16k fresh, neutral elsewhere |
| dropping speculation past ~32k | up to +73% (17.1 vs 9.9 at 64k fresh) |

### Exactly neutral — do not spend time here again

| dial | result |
|---|---|
| `--stream-interval 8` + `--scheduler-recv-interval 4` | 19.08 / 18.62 / 17.22 — identical to default |
| `--page-size 64` | 19.05 / 18.59 / 17.19 — identical |
| `--chunked-prefill-size 8192` (default 2048) | prefill unchanged (~950 vs ~984) |
| `--speculative-attention-mode decode` | within noise of `prefill` |
| `--mamba-radix-cache-strategy no_buffer` | same shape as `extra_buffer` (31.6 / 20.2 / 9.2). Needs `--disable-overlap-schedule` or the server asserts at startup |

The first two matter: they prove decode is **not** host-overhead bound. Per-token
scheduler and detokenizer cost is already invisible, so the remaining gap is
compute, memory bandwidth and TP communication.

### Losses

| dial | result |
|---|---|
| EAGLE steps 1 / draft 2 | worse everywhere (26.5 / 15.9 / 6.5) — per-step overhead dominates, fewer steps does not buy it back |
| `--speculative-algorithm NGRAM` | **14.9 / 10.3 / 9.8 — below unspeculated.** The shipped `ngram` profile for this family is a trap; NGRAM's win in the README is on the Coder-30B MoE, not here |
| `--kv-cache-dtype fp8_e4m3` | server died mid-benchmark; no numbers. Low priority regardless — decode is flat with depth, so KV traffic is not the constraint |
| `--enable-linear-replayssm-spec` | **rejected** — see §3 |

---

## 3. Where the remaining headroom is

Unspeculated bs=1 decode is **19 tok/s against a ~38 tok/s bandwidth roofline**
(54 GB of bf16 weights / 4 cards ≈ 13.5 GB per card per token, at the ~520 GB/s
this silicon actually achieves — see the `gfx1100 bandwidth ceiling` note). Host
overhead is ruled out (§2), so the missing ~50% is TP all-reduce over the PCIe
fabric plus kernel efficiency.

Untested, in rough order of expected value:

1. **A 4-bit AWQ of this checkpoint.** AWQ has a real ROCm path (README §5).
   Cutting weight traffic ~4× attacks the actual bottleneck, and a ~15 GB model
   would also fit on two cards, removing the 4-way all-reduce entirely. This is
   the single largest lever on the list and the only one that can plausibly
   double bs=1 decode.
2. **`--cuda-graph-max-bs-decode`.** Decode graphs are captured only to bs=8
   while `max_running_requests` is 48 — any batch above 8 decodes eager. Matters
   for concurrency, not for a single user.
3. **`--num-continuous-decode-steps`** (default 1) and `--enable-torch-compile`.

### Closed off — tested and dead

- **`--enable-linear-replayssm-spec`** (compact cached replay for linear-chain
  spec verify — exactly the cost that makes speculation collapse at depth).
  It does not run out of the box: the replay kernel passes
  `input_precision="tf32"` and RDNA triton accepts only
  `ieee / bf16x3 / bf16x6`. A one-line default change to `ieee` in
  `sglang/kernels/ops/attention/fla/gdn_replayssm_spec_decode.py` makes it
  start, but it is then **slower than its own `no_buffer` control at every
  depth** (29.2 / 19.2 / 27.5 / 8.7 / 12.9 vs 31.6 / 20.2 / 31.7 / 9.2 / 13.6) —
  `ieee` fp32 dots cost what the path was meant to save, and this hardware has
  no tf32 to fall back on. Not worth a patch 0008.
  Also note it is mutually exclusive with `--enable-linear-replayssm`.
- **`--enable-quant-communications`** — rejected at startup:
  *"Communications quantization is only supported for NPU device"*.
- **Prefill CUDA graphs** (`--cuda-graph-backend-prefill full`) — the scheduler
  child dies at launch. The decode graph does capture (`backend: full`, bs
  `[1,2,4,8]`); prefill graphs stay disabled. Worth one more look only if
  prefill becomes the target.

---

## 4. What is deployed

The live `mtp` profile on cluster `7900s-sglang` now carries:

```json
"flags": ["--speculative-adaptive", "--triton-attention-num-kv-splits", "32"]
```

Measured on the live runner after the change, against the same profile before it:

| case | before | after |
|---|---|---|
| 16k echo (edit-shaped) | 31.6 | **50.1** (+59%) |
| 16k fresh | 20.4 | 22.0 (+8%) |
| 2k fresh | 36.2 | 32.9 (−9%) |

The 2k regression is the adaptive tradeoff and is the right trade: agent traffic
lives at 10k+, not 2k. It went in as a `flags` passthrough because
`build_sglang_args` has no named knob for either — see below.

## 5. Stack integration gaps

- `build_sglang_args` (`container/backend/runtime.py`) maps none of the dials
  above. They can go through the `flags` passthrough, but `sweep.py` grids patch
  scalar profile keys, so anything worth autotuning needs a named knob.
- **`sweep.py` cannot find the effect in §1.** It measures one shallow prompt via
  `measure.py`, so it would rank the 64k-hostile config first. Depth needs to be
  a sweep axis before the autotuner is trusted on this backend.
- The `ngram` profile on `qwen3.8-27b-bf16-sglang` should be deleted or
  re-pointed; it is strictly slower than `balanced`.
