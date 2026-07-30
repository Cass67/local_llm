# tinygrad on RDNA3: evaluation plan (2026-07-30)

## The question

llama.cpp's layer split is pipeline parallelism with depth 1. Measured on this box
today, aggregate GPU occupancy pins at **0.84–1.01 GPU-equiv** and does not move
with `--parallel` (1 → 4) or concurrency (2 → 8). Batching raised throughput 1.85×
out of the *same* GPU-seconds; it never bought more GPU-seconds.

tinygrad has real tensor parallelism (`Tensor.shard` + collectives) and its own
RDNA3 stack. **Does sharded decode on two 7900 XTs clear 1.00 GPU-equiv, and at
what tok/s cost?** Everything below exists to answer that cheaply and back out
safely.

## Kill criteria — decide before starting

Proceed past each stage only if:

- **Stage 2 gate:** sharded 2-GPU decode reaches **aggregate ≥ 1.3 GPU-equiv**.
  Below that, TP is not overcoming its own sync overhead on PCIe and the whole
  premise fails — stop, document the number, keep independent lanes.
- **Stage 3 gate:** tok/s within ~30% of the equivalent llama.cpp lane. tinygrad
  relies on BEAM autotuning against years of hand-tuned Vulkan/coopmat kernels;
  if decode is 3× slower, higher utilization is worthless.
- **Time box:** 4 h for Stage 1+2. Driver bring-up is a rabbit hole; cap it.

## Hardware constraints (measured)

| | |
|---|---|
| `03:00.0`, `06:00.0` | Gen4 x16 — the TP pair |
| `07:00.0` | OCuLink **Gen3 x4**, 3.94 GB/s theoretical. **Excluded from TP** — all-reduce runs 2 collectives/layer, ~128 round-trips/token; latency, not bandwidth, is the tax |

## Sequencing: wait for card 3

Do not start Stage 3 before the third 7900 XT is installed. Card 3 on its own
(Q4_K_M 27B, ~16.5 GiB) is a working production lane that keeps the box useful
while the two x16 cards are borrowed for the experiment. Doing this in the other
order means downtime on the only lane you have.

## Stage 1 — tinygrad on the existing stack (non-destructive, ~2 h)

No `amdgpu` unload. tinygrad's AMD backend can drive the cards through `/dev/kfd`
while the production stack keeps running.

1. Install tinygrad in a venv on ubt26 (or a container — see step 4).
2. Run a single-GPU LLaMA example on `03:00.0` only. Record cold-start,
   BEAM autotune time, and single-card decode tok/s.
3. Confirm kernel compilation works without ROCm's comgr in the path.
4. **lltop work item:** the fdinfo panel reads `/proc/1/fdinfo` via
   `docker exec`. A host-side tinygrad process needs either a sudo path or a
   container wrapper. Cheapest: run tinygrad in a container so the existing
   `docker exec` collector works unchanged.

Deliverable: single-card tok/s baseline, and lltop reporting on a tinygrad process.

## Stage 2 — sharding across the x16 pair (non-destructive, ~2–4 h)

Still on `amdgpu`. P2P may be unavailable on this path, so expect host-staged
copies — that is fine, it still answers the overlap question and gives a
pessimistic bound.

1. `Tensor.shard` the model across the two x16 cards.
2. Fire concurrent decode load; read `aggregate N.NN / 2.00 GPU-equiv` from lltop.
3. Compare against today's 0.84–1.01 baseline.

**Apply the Stage 2 gate here.** If aggregate stays ≈1.0, TP on PCIe without
P2P is not viable and Stage 3's only remaining lever is P2P — decide explicitly
whether that's worth the destructive step.

## Stage 3 — AM driver bring-up (destructive, half day + risk)

Only if Stage 2 cleared its gate. AM replaces `amdgpu` entirely.

**Prerequisites**
- IOMMU off (AM lists P2P/SDMA as contingent on a system without IOMMU)
- Resizable BAR enabled
- All runner containers stopped; `amdgpu` unloaded (module-wide, not per card)
- SSH-only access confirmed — unloading `amdgpu` drops `/dev/dri` and the console

**Two things break that are easy to forget**

1. **lltop goes blind.** No `amdgpu` means no `/sys/class/drm` and no DRM fdinfo.
   Everything built today stops reporting, exactly when measurement matters most.
   Fall back to tinygrad's own timings.
2. **Thermal and fan control go with it.** Power, temp, and fan sysfs all come
   from the amdgpu hwmon nodes, and cooling on this box is hand-managed. Before
   unloading, confirm the cards fall back to a firmware fan curve — do not run a
   sustained shard benchmark on unverified cooling.

**Rollback** — document and dry-run before the first unload:
- record which containers were running
- `modprobe amdgpu`, verify `/sys/class/drm/card*` and hwmon return
- restart runners, `curl /health`, confirm lltop panel is back

**Measure:** aggregate GPU-equiv with P2P on vs off, and decode tok/s.

## Stage 4 — serving layer (only if Stage 3 wins, days not hours)

tinygrad has no OpenAI-compatible endpoint, no continuous batching, no paged KV.
The router, Pi agent, and open-webui all speak OpenAI.

- MVP: single model, fixed slot count, `/v1/chat/completions` + `/health` shim.
- Register as a cluster with its own port; router needs no code change, only a
  rule target (`cluster_remap` handles renames).
- Explicitly out of scope for the MVP: continuous batching, prefix cache reuse,
  speculative decoding. Losing `--cache-reuse` and MTP is a real regression —
  weigh it against the utilization win before committing.

## Expected outcome

Most likely: Stage 2 shows partial overlap, Stage 3 shows real overlap with P2P,
and Stage 4's missing serving features cost more than the extra utilization is
worth for interactive use. That result is still worth having written down with
numbers — it converts "tinygrad might fix this" into a decision.

Production path is unaffected either way: independent lanes, one model per card
group, `--parallel` raised for concurrent agent traffic.
