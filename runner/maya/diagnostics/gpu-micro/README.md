# GPU microbenches

Small HIP programs that test one runtime behaviour each, with no model loaded. Same idea as
`../issue-841/queue-steps.cpp`.

- `vram-bw.cpp`: VRAM read bandwidth from one compute kernel. Args: `device max_gib`.
- `submit-cost.cpp`: empty-kernel launch cost, plus cross-card waits. `async` launches the
  whole step, then syncs. `chain` waits on the previous card before each launch, like the
  ggml split walk. Arg: `steps`.
- `run.py`: runs a command with 0.5 s busy/watts/KFD-queue sampling. Writes
  `results/<kernel>-<name>.jsonl`. Refuses to start while any KFD process exists.

- `graph-cost.cpp`: the GPU-side gap per kernel in a dependent chain, stream launches vs one
  captured HIP graph, for empty kernels and for kernels doing 20 µs of work. Arg: `device`.
- `qpi-p2p.cpp`: 64 MB peer copy per `src:dst` pair: kernel write, kernel read, SDMA peer copy,
  and the same data staged through pinned host RAM. Args: `0:1 0:2 ...`.

## Run on ubt26

Stop the live runner first. Run inside `maya-841-debug` (live image, `/mnt/scratch` at
`/work`) so the HIP runtime matches production. That image has `/opt/rocm/bin/hipcc` but keeps
it off `PATH`.

```sh
docker exec maya-841-debug sh -c 'cd /work/gpu-micro && /opt/rocm/bin/hipcc -O2 vram-bw.cpp -o vram-bw && /opt/rocm/bin/hipcc -O2 submit-cost.cpp -o submit-cost'
L=LD_LIBRARY_PATH=/opt/rocm/lib
python3 run.py --container maya-841-debug bw-dev0 -- env $L /work/gpu-micro/vram-bw 0 16
python3 run.py --container maya-841-debug submit -- env $L /work/gpu-micro/submit-cost 2000
python3 run.py --container maya-841-debug idle-mixed -- env $L /work/maya-841/queue-steps 1 2 4
```

## Results, 2026-11-07

Kernel 7.4.0-rc1, Maya v1.1.55 image `a2430cbf`.

**VRAM:** 718-734 GB/s on 16 GiB, all four cards. That is 90-92% of the rated 800 GB/s, for
both full reads and one word per 64-byte line. The ~65% seen in llama.cpp decode is therefore
software or access pattern, not the memory system.

**Submit:** a launch costs ~1.9 µs and a single-kernel round trip ~20 µs. A chained handoff is
~20 µs on one card and ~29 µs across two. Across four cards it is ~145 µs with HIP's default wait
(auto, and yield too), but ~32 µs with `hipDeviceScheduleSpin`, `hipDeviceScheduleBlockingSync`
or `HSA_ENABLE_INTERRUPT=0`. `GPU_MAX_HW_QUEUES=1` and the CPU socket change nothing.
Try the scheduling flags with `SUBMIT_SCHED=spin|yield|block`.

The first version of this bench launched onto streams whose device was not current. HIP rejects
that with `invalid resource handle`, and the bench did not check, so its "0.3 µs" numbers were
failed launches. Always `hipSetDevice` to the stream's device and check `hipGetLastError`.

**Graphs, GPU side:** with 20 µs kernels the gap is 2.0-2.1 µs per kernel for both stream
launches and graph replay, on HIP 0 and 3. With empty kernels, graphs save only 0.3-0.5 µs.

**Launch, host side** (`launch-cost.cpp`): one `hipLaunchKernel` costs 2.1-2.4 µs with 8-byte
args and 3.4-3.9 µs with 256 B-2 KB, on one thread. With four threads launching to four cards at
once it costs 3.4-4.3 µs and 5.2-8.9 µs, which is runtime lock contention. `HIP_FORCE_DEV_KERNARG`
makes no difference. `hipGraphLaunch` costs 0.05-0.09 µs per node, with one thread or four. Capturing the kernels again each step, then `hipGraphExecUpdate` and launch, costs 26-34 µs per node (`LAUNCH_MODES=2`), so a graph only pays when it is captured once and replayed. Patching nodes before each replay with `hipGraphExecKernelNodeSetParams` (`LAUNCH_MODES=3`, `UPD_EVERY=k`) costs 25-30 µs per patched node, so it beats plain launches only when fewer than about 25% of nodes change.

So a graph does not make the GPU faster, but it keeps the GPU fed whenever kernels are shorter
than the launch cost. Maya DS4 is in that case: card 0's queue runs dry while its launcher is
inside `hipLaunchKernel` (see `../ds4-decode/`).

**Idle burn:** `queue-steps 1 2 4` reaches 9 queues, and card1 sits at 16-17% busy / 15 W
until exit. `1 0 6` and `GPU_MAX_HW_QUEUES=1` stay at 0%. That matches the 7.4 partial fix in
`../issue-841/kernel-test.md`.

**Cross-socket P2P (`qpi-p2p`, kernel `7.4.0-rc1-t7910-p2p` with all pairs allowed):** same socket
(0-1, 2-3) kernel write and SDMA 10.2 GB/s, read 2.2. Cross socket (0-2, 1-3) write and SDMA
0.24-0.29 GB/s, read 0.53-0.60. Staged through host RAM 6.7 GB/s serial (D2H 14.1, H2D 12.8) for
every pair, so QPI itself is fast; only device-to-device traffic forwarded over QPI is slow.
SDMA is as slow as a kernel, so it is the Broadwell-EP CPU, not the code or the kernel patch
(which only allows the mapping). BIOS has Home Snoop, MMIO above 4G / Large, no QPI or ACS
tokens; root-port ACS ReqRedir+ also applies to same-socket pairs, which run at full speed.
