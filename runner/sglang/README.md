# SGLang on gfx1100 (4× RX 7900 XT)

SGLang serves on this box: dense, MoE and hybrid-GDN models, TP=4 across all four
cards, CUDA graphs, and speculative decoding. None of that works on stock
upstream — it took seven patches, a rebuilt RCCL, and finding one hardware
property of the machine that explains most of the failures.

Status as of 2026-09-17:

| model | config | decode |
|---|---|---|
| `Qwen3-Coder-30B-A3B-Instruct` bf16 (MoE) | TP=4, NGRAM | 39 tok/s, ~114 on edit-shaped prompts |
| `Qwen3.8-27B` bf16 (hybrid GDN) | TP=4, EAGLE/MTP | ~41 tok/s (19.2 unspeculated) |

Prefill is ~1050 tok/s, better than the llama.cpp Flash-Next ceiling of ~700.

---

## 1. The thing that explains everything: PCIe atomics

The single most important fact about this machine:

```
00:01.0  CPU root port -> PLX PEX 8747 -> cards 0,1,2   AtomicOpsCap: 32bit+ 64bit+ 128bitCAS+
00:1d.0  PCH root port                 -> card 3        AtomicOpsCap: 32bit- 64bit- 128bitCAS-
```

Card 3's **slot** cannot complete PCIe atomic operations. ROCm needs PCIe atomics
for **hostcall**, and hostcall is required by any kernel containing a device-side
`assert()` **or `printf()`**. Such a kernel cannot be dispatched on that card at
all:

```
rocvirtual.cpp:3685  Pcie atomics not enabled, hostcall not supported
rocvirtual.cpp:4025  AQL dispatch failed!
                     hipLaunchKernel -> hipErrorIllegalState
```

which reaches Python as the uninformative:

```
HIP error: the operation cannot be performed in the present state
```

It is **slot-determined, not card-determined** — the card itself is fine, and runs
llama.cpp, torch and unguarded sglang kernels without complaint.

Three separate failures this session were all this one cause:

| symptom | kernel at fault | fix |
|---|---|---|
| server won't start at all | sglang JIT `store_kvcache` (device `assert`) | patch 0005, `-DNDEBUG` on the **device** compile |
| TP>1 including card 3 dies | `ncclDevKernel_*` (RCCL's device asserts) | rebuild RCCL with `-DNDEBUG` |
| EAGLE/MTP dies on first request | `build_tree_efficient` (device **`printf`**) | patch 0007 |

**`-DNDEBUG` removes `assert()` but NOT `printf()`.** That distinction cost an
extra debugging round: MTP still failed after 0005 and the RCCL rebuild.

### Diagnosing `hipErrorIllegalState`

Do this first, always:

```bash
AMD_SERIALIZE_KERNEL=3 AMD_LOG_LEVEL=3 <the failing command> > log 2>&1
grep -B2 "AQL dispatch failed" log     # the ShaderName line above it names the kernel
```

Two traps that wasted time here:

1. **The Python traceback is not the fault site.** HIP reports kernel errors
   asynchronously at a later API call. MTP's stack pointed at an ordinary torch
   gather in `set_mamba_track_indices_from_reqs`, which led to the wrong
   conclusion that torch's index kernels need hostcall — they don't, the
   non-speculative path gathers on that card constantly.
2. **`AMD_SERIALIZE_KERNEL=3` alone is not enough.** It still reported the same
   Python line, which looked like confirmation. `AMD_LOG_LEVEL=3` and the
   `ShaderName :` line is what actually names the kernel.

### Falsified hypotheses

Do not re-run these. All were tested and all are irrelevant:

P2P across root ports (`can_device_access_peer` is 0 for *every* pair, including
working ones) · DMA-BUF / GDR · every transport (`NCCL_P2P_DISABLE=1` +
`NCCL_SHM_DISABLE=1` together) · shm size (16 GB) · ROCm/RCCL version (7.2.4 with
RCCL 2.27.7 and 7.14.1 with 2.30.4 fail identically) · cooperative launch ·
warp-size skew · SKU/geometry (all four: 42 CU, 1024 maxThreads, identical KFD
props) · SDMA / HW queues · container namespaces (`--privileged --ipc=host
--pid=host`) · IOMMU (booted `intel_iommu=off`, 0 groups — no change) ·
`amdgpu.ppfeaturemask` · JIT cache provenance · launch geometry · VBIOS/firmware
(byte-identical across all four).

Note `--split-mode layer` llama.cpp is **not** a counterexample for any of this:
`libggml-hip.so` references zero nccl symbols and never dispatches an RCCL
kernel. A mapped `.so` proves linkage, not dispatch — check
`nm -D --undefined-only`.

---

## 2. The patches

Applied in order by the Dockerfile. 0001–0004 are upstream PRs re-pathed or
ported; 0005–0007 have no upstream equivalent and are worth contributing.

| # | what | origin |
|---|---|---|
| 0001 | gfx1100 in `RDNA_TARGETS`, wave32 `WARP_SIZE`, 48 KB TopK LDS cap, CDNA-only all-reduce guarded out | sgl-project/sglang#31137, re-pathed |
| 0002 | optional aiter imports — **hard blocker**, server won't start for any model without it | #31421 |
| 0003 | `no_grad` around the MoE sum-reduce — **hard blocker for MoE** cuda-graph capture | #31246 |
| 0004 | gate `triton_symm_mem_ag` off on RDNA | ours |
| 0005 | `-DNDEBUG` on the **device** compile (`base_cuda_flags`) | ours |
| 0006 | build + register the ngram speculative kernels on ROCm | ours |
| 0007 | drop the device `printf` in `build_tree_efficient` | ours |

Notes:

- **0002 and 0003 are filed upstream as gfx1151 fixes but are not gfx1151
  specific** — they reproduce identically on gfx1100. Worth saying so on those PRs.
- **0004**: any single-node TP>1 unconditionally builds the multimem all-gatherer
  at `logits_processor.py:445`, and
  `torch.distributed._symmetric_memory.rendezvous()` hard-aborts the scheduler on
  RDNA. No env var disables it. RCCL says so itself: `Symmetric memory is not
  supported. cuMemEnable 0`. Nobody upstream hit this because Strix Halo is a
  single APU — it needs ≥2 discrete RDNA cards.
- **0005 trap**: host and device compiles use *separate* flag lists. Adding
  `NDEBUG` to `DEFAULT_CFLAGS` in `paths.py` only reaches `cxxflags` and changes
  nothing. It must go on `base_cuda_flags()`, which feeds `cudaflags`. Check the
  generated `.ninja` under `/root/.cache/sglang/jit` to see which list got it, and
  clear that cache after changing flags.
- **0006**: `csrc/speculative/ngram_utils.cu` is in the CUDA and MUSA builds but
  not ROCm, and `reconstruct_indices_from_tree_mask` is registered in
  `common_extension.cc` / `_musa.cc` but not `_rocm.cc`. Without it NGRAM loads,
  captures both target and target-verify graphs, then dies on first decode. The
  kernel compiles clean under hipcc unchanged — purely a missing build entry.

---

## 3. RCCL must be rebuilt

Stock `librccl` carries two live device asserts:

```
src/device/prims_simple.h:789      assert(2*(nrecv+nsend) <= nthreads);
src/device/msccl_kernel_impl.h:31  assert(nthreads == MSCCL_MAX_NTHREADS);
```

and **RCCL's Release build never defines `NDEBUG` at all** — `grep -c NDEBUG
build.ninja` returns 0 on a stock `CMAKE_BUILD_TYPE=Release` configure. That is
why every shipped librccl needs hostcall, and why nobody on datacenter cards ever
notices.

The Dockerfile builds it with:

```bash
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_PREFIX_PATH=/opt/rocm -DCMAKE_CXX_COMPILER=/opt/rocm/bin/hipcc \
  -DGPU_TARGETS=gfx1100 -DBUILD_TESTS=OFF \
  -DCMAKE_CXX_FLAGS=-DNDEBUG          # <- the whole fix
```

`COLLTRACE=OFF` / `TRACE=OFF` are **not** the fix — tried first, no effect.

Cost: ~25 min, most of it a single-threaded `lld` device link (7.3 GB RSS, needs
host memory headroom). Result is 11 MB single-arch vs the multi-arch shipped `.so`.

When testing an RCCL override, **verify which library actually loaded** —
torch's RPATH can beat `LD_LIBRARY_PATH`:

```python
print([l.split()[-1] for l in open("/proc/self/maps") if "rccl" in l][:2])
```

---

## 4. Build and run

```bash
docker build --network host -t local-llm-runner-sglang:rocm724 runner/sglang
```

~35 min (RCCL dominates). The Dockerfile supports two base layouts via one
conditional:

- **classic `/opt/rocm`** (`rocm7.2.4`, the default) — real ROCm tree, hipcc and
  headers present.
- **pip-ROCm** (`rocm7.14.1`) — no `/opt/rocm` at all; ROCm is wheels under
  `site-packages/_rocm_sdk_*`. Needs `rocm-sdk-devel` from AMD's nightly index,
  and **`--no-deps` is mandatory**: its dependency closure downgrades
  `rocm-sdk-core` and torch then dies with `Could not find rocm library
  'hipblas'`. Recovering means recreating the container.

7.2.4 is the default because sglang itself targets it (`srt_hip_rocm724` extras).
Both serve; the RCCL fix is what makes TP=4 work, not the ROCm version.

Other build notes:

- `SGLANG_BUILD_RUST_EXTS=none` — the Rust router wants cargo and we don't serve
  with it.
- constraints file pinning torch/triton, or pip pulls a CUDA torch over the ROCm one.
- plain `srt_hip`, not `srt_hip_rocm724` — the latter pins `torch==2.11.0` exactly,
  which no 7.2.4 image ships.
- **There is no env var for the attention backend.** Every launch must pass
  `--attention-backend triton`; the HIP default is AITER, which is CDNA-only and
  hard-asserts on RDNA. Upstream #31259 would fix this.

---

## 5. What runs, and what doesn't

| format | works on gfx1100 |
|---|---|
| bf16/fp16 safetensors, dense **and** MoE | yes |
| AWQ (`quant_method: awq`) | yes — real ROCm path in `awq.py` |
| GGUF | only `qwen2 / qwen2_moe / qwen3 / qwen3_moe` archs (transformers' map) |
| compressed-tensors / GPTQ / auto-round W4A16 | **no** — routes to Marlin, which is NVIDIA PTX (`mma.sync`, `ldmatrix`, `cp.async`) |
| FP8 / MXFP4 | no — no hardware |

Gotcha: `compressed_tensors_wNa16.py` guards the `gptq_marlin_repack` import
behind `if _is_cuda:` but calls it unconditionally, so ROCm gets a bare
`NameError` instead of "unsupported on this platform". Worth an upstream issue.
Fixing the repack doesn't help — the Marlin GEMM itself is PTX.

VRAM budget is ~80 GB across four cards. TP=1, 2 and 4 all work; **TP=3 is
usually impossible** — it needs vocab and kv_heads divisible by 3 (Qwen3 vocab
151936 and Qwen3.8-27B's 248320/kv_heads 4 are not).

Hybrid Mamba/GDN checkpoints (the whole Qwen 3.5/3.6/3.8 line) **do** run —
an earlier "unsupported" verdict here was wrong. They need:

```
--mamba-ssm-dtype bfloat16        # halves the state slot: 78.4 MB vs 153.9 at fp32
--mamba-radix-cache-strategy extra_buffer
```

which is the pairing the sglang cookbook uses on its other non-CUDA backend
(Ascend), the closest published analogue to RDNA.

---

## 6. Speculative decoding

| algorithm | status |
|---|---|
| **EAGLE / MTP** | works after patch 0007. Uses a checkpoint's in-file MTP head, no extra weights |
| **NGRAM** | works after patch 0006. No draft weights at all |
| DSPARK | untried — needs a separate drafter checkpoint |

EAGLE recipe for Qwen3.8-27B (NEXTN is an alias of EAGLE):

```
--speculative-algorithm EAGLE --speculative-num-steps 3 \
--speculative-eagle-topk 1 --speculative-num-draft-tokens 4
```

Measured: accept len 2.4–3.7 of 4, **35–54 tok/s vs 19.2** unspeculated, ~2.1×.
Check for an MTP head with `grep -c mtp model.safetensors.index.json` — the
Coder-30B has none, so NGRAM is its only option.

NGRAM measured on the Coder: **~114 tok/s on edit/echo prompts vs ~39**, and
neutral on fresh generation — the same shape as ngram-mod in llama.cpp.

Two operational notes:

- Speculation needs VRAM headroom. `mem_fraction_static 0.90` segfaults the
  scheduler at init once the spec buffers are allocated; 0.82–0.86 is fine.
- **Measure with a fresh prompt.** Re-sending an identical one hits the radix
  cache and returns in 0.7 s, which is not a decode measurement.

---

## 7. Integration with the local_llm stack

Registered as a normal backend. Cluster `7900s-sglang`, port 8086.

The dispatch is one line — `runtime.py` sends `command=` to `build_sglang_args()`
when `backend == "sglang"`. Readiness needed no change: sglang answers
`/v1/models` like llama-server.

Registries touched: `config.py` `RUNNER_IMAGES`, `clusters.py` `_VALID_BACKENDS`
and `_SINGLE_VENDOR_BACKENDS`, `model_variants.py`.

Differences from the llama.cpp backends:

- **A model directory, not a `.gguf` file.** Lives at `/mnt/spare/sglang-models`
  (`SGLANG_MODELS_DIR`), bound read-only as `/sglang-models`. Not the HF cache —
  that volume had 79 GB free and these models are 52–57 GB. The GGUF-cache lookup
  in `build_runner_container_spec` is skipped for sglang or it raises.
- **`LD_LIBRARY_PATH=/opt/rccl/build`** — our RCCL, baked into the image.
- **Persistent `/root/.cache`** (`/mnt/spare/sglang-cache`). Without it every
  start has a cold Triton cache, the runner pays serving-time kernel compilation,
  and mgmt reports *"failed to launch runner"* while the runner is in fact still
  compiling and does come up.
- **Registering a family needs two files**: `/state/profiles.json` *and* an
  accepted entry at `/state/runs/accepted/<family>.json`, or start returns
  `model family ... not found`.
- `--enable-metrics` is default-on: llama-server exposes `/metrics`
  unconditionally, sglang does not, and the Status tok/s card, `prom_export` and
  `lltop` all poll it. `/slots` has no sglang equivalent; `lltop` now probes once
  per port and then reads `sglang:gen_throughput` / `sglang:num_running_reqs`
  instead.

### Parsers are per-checkpoint and invert

| model | `--reasoning-parser qwen3` |
|---|---|
| Qwen3.8-27B (thinking) | **yes** — without it a raw `</think>` lands in `content` |
| Qwen3-Coder-30B-A3B | **no** — with it the whole answer goes to `reasoning_content` and `content` is empty |

Symptom map: empty `content` + populated `reasoning_content` = parser on a
non-thinking model. Stray `</think>` in `content` = parser missing on a thinking
one. `--tool-call-parser qwen3_coder` applies to both; without it a harness
receives tool calls as raw text instead of structured `tool_calls`.

### sglang 400s where llama.cpp clamped

A client sending 26k of context with `max_tokens: 16384` needs 43k. Over the
window, sglang returns a hard **400 BadRequestError**; llama-server silently
clamped. The client retried at ~250/min. **Set `context_length` for prompt +
max_tokens, not just the prompt.** The 27B runs at 131072 (`max_total_num_tokens`
154786, 22 concurrent, 18.7 GB/card).

Because `model-switch.py` pushes `advertised_context - 2048` into every agent
config, a too-small server context becomes a too-small client budget everywhere,
and agents then compact on the first message. Check the server profile before
touching any client.

---

## 8. Worth contributing upstream

Nothing here exists as a PR yet:

1. **`-DNDEBUG` on device compiles** (0005) and the **device `printf`** (0007) —
   both are the same class, and the RCCL equivalent affects every consumer GPU on
   an atomics-less slot. This is a real portability bug, not a local quirk.
2. **ngram kernels missing from the ROCm build** (0006) — a one-line build entry
   plus a registration; the kernel is already portable.
3. **`triton_symm_mem_ag` needs an RDNA gate** (0004) — unreachable on a
   single-GPU APU, so the gfx1151 work could not have found it.
4. **`gptq_marlin_repack` NameError** — CUDA-only import, unconditional call.
5. #31421 and #31246 are filed as gfx1151 fixes but are **not gfx1151-specific**.
