# DS4 decode critical path

Tools for maya-ds4 at `--tp 4` (`maya-dsv41-q4xl-huihui`) on ubt26. Run them on the host.

- `arm.py TAG [KEY=VAL ...]`: A/B one `maya_env` change. The first arm backs up `profiles.json`.
  Each arm restarts the runner, runs `~/scratch/ds4-ab/pair.py TAG` (4 prompts x 2 rounds, 1024
  tokens, temp 0) and, when `ROCP_TOOL_ATTACH=1` is in the env, takes a 3 s kernel trace during a
  story decode. `arm.py --restore` puts the backup back and deletes it.
- `trace.py DIR`: critical-path report for one trace. It shows wall split by how many cards do
  real work, allreduce wait per card, the lead's idle gaps, and kernels only the lead runs.
- `clk.sh SECONDS`: busy %, core clock and memory clock per card every 0.25 s.

rocprofv3 traps: `--hip-runtime-trace` fails argument parsing in this image's rocprofv3. The
engine writes the CSV after detach, so wait for it before `docker cp`.

## Findings, 2026-11-07

Kernel 7.4.0-rc1, Maya v1.1.55, 1 TB box. Bench is 51-80 tok/s depending on prompt, with no SSD
reads.

- The GPUs are now the critical path, not the CPU lane. At least three cards do real work 74% of
  the time, and `mx_wait` is only 78 ms in 3 s.
- Real compute is even and low: 0.8-0.9 s per card per 3 s, about 28%.
- `ar_rs16_kernel` (the TP allreduce) is about 41% of all card time. The lead card's median
  wait is 22 us, while the other three wait 257-323 us. They are waiting for the lead.
- The lead is late because of launch gaps, not compute. It has 1.34 s idle in 3 s, 1.0 s of it in
  gaps under 50 us between ordinary kernels, against a median gap of 5.0 us vs 3.0-3.4 us on the
  others. Only the lead runs the CPU-lane coordination (`publish_kernel` 2310x,
  `wait_seq_kernel` 1797x, `mx_wait`, sampler). The DSpark drafter kernels are spread evenly over
  members 0-2.
- There is no CUDA/HIP graph capture in DS4. GLM's DSA FFN got graphs in a recent release
  (+8-9%), and MM3 decodes whole tokens as graphs.

Ruled out:
- `HSA_ENABLE_INTERRUPT=0`: warm 61.2 vs 61.2 tok/s. The handoff that matters is the in-kernel
  allreduce, not host waits.
- GPU power tuning: during decode every card holds its top memory clock (1249 MHz) and about
  2.9 GHz core clock.
- CPU governor: the busy engine threads already run at 2.1-2.4 GHz (2.4 max) and spin, so
  C-states do not apply.

The levers left are in the engine: take lane coordination off the lead's launch thread, fuse
`q8_quant` into its consumers, or capture DS4 decode layers as graphs.

## Gap breakdown, 2026-11-07

- `att.sh OUTDIR FLAGS...`: attach for 2 s during a story decode (needs `ROCP_TOOL_ATTACH=1`).
  `./att.sh C-trace --kernel-trace --memory-copy-trace --hip-runtime-trace` works when the flags are
  given in that form.
- `gapcause.py DIR "Agent 2"`: matches each kernel to its `hipLaunchKernel` by correlation ID, then
  sorts every idle gap into one of three causes:
  - the launch was submitted after the previous kernel ended, so the queue ran dry;
  - a copy ran on that card during the gap;
  - the kernel was already queued, so the GPU waited on its own.

Tracing adds overhead, so read these as shares, not absolute times. Card 0's queue runs dry for 37%
of wall (746 ms of 2 s), with the launcher inside `hipLaunchKernel` (429 ms) or in engine code
(295 ms). Copies take 5% and GPU-side waits another 5%. Card 3 runs dry for 13%. Card 0's
launcher cannot keep up with kernels that take 2.5-6 us. `../gpu-micro/launch-cost.cpp` shows why:
lock contention between the four launcher threads plus 256 B+ by-value args make each launch cost
5-9 us. `hipGraphLaunch` costs 0.05-0.09 us per node, so capturing DS4 decode as graphs is the
fix to try. This replaces "Ruled out" above on graphs.

## v1.1.56 and DS4_AR_P2P, 2026-11-07

Warm `pair.py` means (temp 0, round 2): v1.1.55 61.2 tok/s, v1.1.56 63.9, and v1.1.56 with
`DS4_AR_P2P=1` plus a local override of #809's AMD guard (`DS4_AR_P2P_AMD=1`) 62.1. One run each,
so the v1.1.56 difference is not established. P2P never engaged: the engine logged "stays
host-mapped" because `hipDeviceCanAccessPeer` allows only HIP 0 <-> 1. HIP 2 and 3 have no peer
access, even to each other. A 4-card peer all-reduce is not possible on this board.

Why: no PCIe switch, one card per CPU root port. The kernel's p2pdma check allowlists the host
bridge by the root bus's device 00.0. Socket 0's bus 00 has Intel 8086:6f00 there; socket 1's bus a0
has no 00.0, so 2 <-> 3 is refused. Cross-socket pairs are refused by policy.

Sol's kernel `7.4.0-rc1-t7910-p2p` (`/mnt/scratch/t7910-p2p/t7910-p2p.patch`, boot arg
`t7910_p2p_cross=1`) allows every pair. Results:
- Cross-socket device-to-device transfers run at 0.25-0.29 GB/s; see `../gpu-micro/qpi-p2p.cpp`.
  This is the CPU, not the patch.
- Cached peer buffers hang the 4-card hub test and the engine.
- Uncached buffers (`DS4_AR_P2P_UNCACHED=1`, Sol's `:v1.1.56-p2p-uncached-test`) work but are
  slower. Same image, launched by Sol's `launch-test.py`, warm round:

  | | tok/s |
  |---|---|
  | P2P off | 62.3 |
  | Uncached P2P | 39.2 (-37%) |

  Every prompt got slower. Rejected.

A gain would need P2P within each socket (0-1, 2-3), then the existing host path between sockets.
Scoped and dropped. In B-trace the lead's `ar_rs16` takes a median of 21.8 us (p10 16.0) at ~1,500 per second.
The lead usually arrives last, so this is the all-reduce's own cost: 2.4-3.3% of wall time, about 2 tok/s even if
free. The other cards' 257-323 us is waiting for the lead. The hybrid keeps the cross-socket host round trips,
writes then flags then polls then reads, and adds a peer stage and a broadcast, so the realistic gain is 0-1%. The `arm.py` image comes from the cluster, not the profile, so
image A/Bs need `launch-test.py`.

## Segment graphs (DS4_SEG_GRAPH), 2026-11-07

Branch `ds4-decode-graph` in `~/git/maya-ds4graph` (local commit ba1eed4, on v1.1.56). Each layer's
four fixed-argument runs (attention in, attention out, FFN mix, shared expert) are recorded through
`pdl_launch` and `plain_launch`, hashed over every argument byte, and replayed as captured graphs.
Built with `devbuild.sh v1.1.56-seg`.

- Hits: about 99.9% once `Q8Round`'s and `gg::mv`'s job arrays were zeroed. Before that, their
  unused slots changed the hash every token.
- Speed: warm 61.6 tok/s with graphs vs 61.3 without, so no gain.
- Why: card 0's idle time fell from 1342 to 619 ms per 3 s, so the launch starvation is fixed. HIP 2
  (Agent 4) then became the late card, with 1492 ms idle per 3 s. Its gaps fall at graph starts
  and even between nodes inside one graph (`hc_post -> hc_mix`). Untested guess: ROCm submits a
  graph's nodes lazily.
- Greedy output at temp 0 differs between two graphs-off runs, from the first character, so text
  comparison cannot test correctness on DS4.
