# GPU microbenches

Small HIP programs that test one runtime behaviour each, with no model loaded. Same idea as
`../issue-841/queue-steps.cpp`.

- `vram-bw.cpp`: VRAM read bandwidth from one compute kernel. Args: `device max_gib`.
- `submit-cost.cpp`: empty-kernel launch cost, plus cross-card waits. `async` launches the
  whole step, then syncs. `chain` waits on the previous card before each launch, like the
  ggml split walk. Arg: `steps`.
- `run.py`: runs a command with 0.5 s busy/watts/KFD-queue sampling. Writes
  `results/<kernel>-<name>.jsonl`. Refuses to start while any KFD process exists.

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

**Idle burn:** `queue-steps 1 2 4` reaches 9 queues, and card1 sits at 16-17% busy / 15 W
until exit. `1 0 6` and `GPU_MAX_HW_QUEUES=1` stay at 0%. That matches the 7.4 partial fix in
`../issue-841/kernel-test.md`.
