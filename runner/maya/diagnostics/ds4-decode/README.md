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
