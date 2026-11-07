# Maya #841: HIP idle power investigation

Kernel follow-up: [QEMU and physical boot results](kernel-test.md).

Tests run on `ubt26`, 2026-11-06. GLM was stopped for exclusive GPU access.

The workaround and test summary were posted to [GitHub issue #841](https://github.com/mw00/project-maya/issues/841#issuecomment-6674087494).
The [standalone HIP reproducer](https://github.com/mw00/project-maya/issues/841#issuecomment-6674183227) is also in the thread, with the queue-count follow-up.

## Follow-up: actual queue counts and the likely underlying defect

A subsequent single-GPU test counted KFD compute queues through sysfs every
0.5 seconds while creating streams one at a time. GLM and other GPU workloads
were stopped. These tests issue no GPU allocations, copies, kernels, events,
or synchronization. HIP device 0 mapped to DRM card1 in this container.

| Case | Maximum KFD compute queues | Result on target GPU |
| --- | --- | --- |
| Two high + four normal streams, complete first-pass teardown, repeated | 9 | 100% busy, about 96.5 W during idle |
| Six normal streams, default queue limit, repeated | 5 | Normal idle, about 13 W |
| Two high + four normal streams, `GPU_MAX_HW_QUEUES=1`, repeated | 3 | Normal idle, about 10 W |
| Eight normal streams, `GPU_MAX_HW_QUEUES=8` | 9 | 100% busy on the first pass, about 95 W initially |

The failing mixed-priority run had six 1 MiB compute queues plus one 4 KiB
auxiliary compute queue after the first pass. Destroying every HIP stream did
not remove those underlying queues. Creating two high-priority streams on the
second pass added two more large queues. The last eight-queue idle sample was
at 30.37 s; the first 100%-busy sample at 30.87 s had nine compute queues.
All nine queues remained after the final stream destroys.

The normal-priority/high-limit control is decisive for interpreting priorities:
its last eight-queue idle sample was at 24.28 s, and its first 100%-busy sample
at 24.78 s had nine queues. It failed during the first pass. The negative test
was terminated early after establishing the failure and queue retention.
Thus neither priority mixing nor model reload is necessary. They are how the
default DS4 automatic-reload path grows the queue pool past the observed limit.

This agrees with HIP's per-priority queue pools: the default four-queue limit
allows four normal and four high-priority queues, in addition to an auxiliary
queue. Hardware queue retention explains why fixing the Maya stream leak alone
does not prevent the issue. The source reviewed for this mechanism is
[ROCm/clr's acquire/release queue implementation](https://github.com/ROCm/clr/blob/develop/rocclr/device/rocm/rocdevice.cpp);
that source is not pinned to the installed TheRock build, but the queue counts
and retention above were measured directly on the installed runtime.

AMD has already identified a closely matching gfx11 defect. Linux commit
[`590e26626106`](https://github.com/torvalds/linux/commit/590e26626106533d15fed808ac92f7135b2c909b)
describes idle 100% GPU usage under oversubscription, identifies the MES
oversubscription timer as its cause, and replaces it with a KFD-side notification
timer. Follow-up commit
[`a6ea3f9ec21e`](https://github.com/torvalds/linux/commit/a6ea3f9ec21eafcbdcd3534e79f3c93ca4e89038)
corrects that software timer's interval units. The associated series also has
MES API and SR-IOV changes; a kernel comparison should use the complete fixes.

The original `7.2.13-ubt26` amdgpu module has no `notify_unmap` symbols and its
`mes_v11_0_set_hw_resources` disassembly retains the packed constant containing
the old value 50. This is consistent with the old timer setup, not a readback
of live firmware state. The loaded amdgpu module's `srcversion` matches the
inspected on-disk module. No kernel, module, scheduler policy, or firmware was
changed during the original tests.

**Evidence boundary:** the queue-count threshold and queue retention are measured.
Identification with AMD's MES timer defect is supported by those measurements,
the upstream fix description, and a subsequent kernel A/B. On 7.4-rc1, both
the mixed-priority and eight-normal-stream controls retained nine queues but
settled at about 15 W and 16–17% activity on the target GPU, instead of 100%
and roughly 97 W. The new module contains the notification handlers. This is
a substantial power improvement, with residual reported activity; it is not
a complete return to zero activity. Userspace and the HIP runtime were unchanged.
The application workaround `DS4_STREAM_PRIO=0` remains the zero-activity option
verified in full DS4 on the original kernel. See the kernel follow-up for the
full DS4 comparison and runtime state.

Full DS4 on 7.4-rc1 also completed its automatic reload and generated four
tokens with default priorities. Settled per-card medians were 14 / 15 / 14 /
16 W before the request (59 W total) and 14 / 15 / 16 / 16 W afterward
(61 W total), with 14–18% activity. The original default-priority run drew
380 W at 100% activity. See `kernel74-results.json` and the raw telemetry.

Artifacts for this follow-up: `queue-steps.cpp`, `steps.py`, `steps-*.jsonl`,
`steps-*.out`, `queue-count-results.json`, `module-mes-symbols.txt`, and
`module-mes-resources.txt`. The sysfs sampler records queue counts, types, and
sizes, not GPU memory contents. The posted source and instructions are also
saved in `thread-reproducer.md`.

**Validated DS4 workaround:** `DS4_STREAM_PRIO=0`, with automatic shares still
enabled. The installed v1.1.55 binary completed its reload, reached ready, and
generated four tokens. After the initial settling sample, all eight pre-request
idle samples and all five post-request idle samples were 0% on every card.
Median powers were 11 / 5 / 10 / 18 W before the request and 14 / 14 / 9 / 12 W
after it. This was a short functional check, not a throughput or long-prompt
benchmark. No production profile or launcher setting was changed.

## Workaround for the problem report

For DS4 on this four-card gfx1100 setup, explicitly set:

```text
DS4_STREAM_PRIO=0
```

Pass this setting to the DS4 engine through its profile/launcher and start a fresh
engine process. Leave automatic `DS4_TP_SHARES` enabled to retain its placement
benefit. An unset `DS4_STREAM_PRIO`, or a value of `1`, selects high-priority
layer streams on these RDNA3 cards; removing the variable re-enables that default.

The setting gives DS4's layer streams normal priority. Tensor parallelism,
parallel streams, automatic shares, context size, and model calculations remain
available. The possible cost is throughput or latency when compute competes with
other work; that performance tradeoff has not been benchmarked. The validated
result is normal idle before and after a short generation request on v1.1.55.

Without the workaround, the four cards idled at 100% busy and approximately
380 W combined. With it, settled idle was 0% on every card, approximately 44 W
combined before the request and 49 W afterward (sums of per-card medians).
The engine completed the automatic reload in both cases.

`DS4_TP_SHARES=off` remains the original workaround in issue #841; the priority
setting offers a tested way to keep automatic shares enabled. `GPU_MAX_HW_QUEUES=1`
was tested only in the standalone reproducer, not as a full DS4 workaround.

A related RDNA2 prompt-stall report was also resolved by `DS4_STREAM_PRIO=0`.
Since v1.1.39 Maya applies normal priority automatically on gfx103x, while CUDA
and other AMD architectures retain the previous default. That report's stalls
and this report's idle power problem have different symptoms; a common underlying
defect has not been established. See [issue #621's maintainer confirmation](https://github.com/mw00/project-maya/issues/621#issuecomment-6509727694).

## Why automatic shares and stream priorities interact

These settings affect different parts of the engine, but automatic shares causes
the stream setup to run twice in one process:

1. With automatic shares enabled, DS4 loads an initial allocation to measure each
   GPU's room for experts. It calculates the per-layer FFN shares from those
   measurements.
2. If the new shares are worth using, `Model::load()` destroys the first `Impl`
   and constructs another one. The second load uses the measured shares.
3. Each load creates two layer streams per GPU (`d.st` and `d.st2`). With
   `DS4_STREAM_PRIO` unset or `1`, these request the device's greatest priority.
   Four chunk/copy/all-reduce streams per GPU request normal priority.
4. HIP maps these logical streams onto underlying hardware queues. Priority
   affects that mapping: AMD's ROCR documentation describes queue reuse within
   a priority and a `GPU_MAX_HW_QUEUES` limit counted separately per priority.
   The second load therefore repeats a mixed-priority queue-creation sequence.
5. On this gfx1100/HIP/driver combination, repeating that sequence can leave the
   GPUs in a persistent non-idle state. The busy counters read 100%, shader
   clocks stay high, and power rises even while the host process is sleeping.

The connection is the reload's queue lifecycle, rather than any arithmetic in
the expert shares. In the standalone reproducer, the second round of stream
creation triggers the same persistent state without allocating GPU buffers,
copying data, launching user kernels, or calling device synchronization. This
also means ordinary starvation of a low-priority compute task does not explain
the reproduced idle failure: the stream-only case has no such task running.

Mixed-priority streams are a supported API configuration. This investigation
establishes a trigger on the tested AMD stack, not an inherent incompatibility
between the two Maya features. We have not captured the live MES
scheduler or firmware state. The follow-up above subsequently measured the queue
counts and established the eight-to-nine queue threshold. AMD's MES timer defect
is now the leading underlying explanation; its fix still needs a kernel A/B here.

The experiments separate the relevant factors:

| Change | What it changes | Observed result |
| --- | --- | --- |
| `DS4_TP_SHARES=off` | Avoids the automatic measurement/reload cycle | Original issue reports normal idle |
| `DS4_STREAM_PRIO=0` | Keeps the reload but gives both layer and chunk streams normal priority | Full DS4 test returns to normal idle |
| `GPU_MAX_HW_QUEUES=1` | Limits underlying queue allocation within each priority | Standalone reproducer returns to normal idle; full DS4 not tested |
| Complete first-pass stream teardown | Removes the known Maya stream leaks but still recreates mixed-priority streams | Standalone and diagnostic DS4 tests still fail |

Consequently, the stream leak should be fixed separately, but it is insufficient
as a fix for this idle-power problem. The priority workaround keeps automatic
shares and concurrency between streams; it removes the scheduler preference for
the layer streams. Its throughput/latency effect still needs benchmarking.

## Setup

- Four RX 7900 XT / gfx1100 cards, kernel `7.2.13-ubt26`, AMD scheduler policy 0.
- Installed Maya v1.1.55, commit `c4effee67cb9`, image `local-llm-runner-maya:v1.1.55`.
- The installed image has the GLM patch; it does not modify DS4 source files.
- HIP `libamdhip64.so.7.15.26302-0000000` from TheRock.
- Existing UD-Q4_K_XL huihui DS4 pack, context 524288, DSpark and vision on,
  mmap-experts off, experts 6, reserve 512 MiB.
- Direct `maya-ds4 --serve` processes in an isolated container; no HTTP server
  or production launcher changes. No existing environment/config files were read.

## Findings established so far

1. Without uneven GGUF splitting, `--tp 4` falls back to two-member groups.
   This control did not reload and idled at 0% on all four cards, median
   powers 10 / 7 / 13 / 18 W across nine idle samples. A four-token request passed.
2. With `MAYA_DS4_TP_GGUF_UNEVEN=1`, automatic shares triggered a reload at
   14.6 s. At 20 s the cards were 98–100% busy. After ready, all nine idle
   samples were 100% on every card, median powers 88 / 104 / 84 / 104 W.
   A four-token request still passed; process exit cleared the condition.
3. `~Impl()` omits destruction of `Dev::st2` and four chunk streams per GPU,
   plus associated events. However, a diagnostic build completing that teardown
   still reproduced the problem during the second load. This patch is **not a fix**.
   That negative test was terminated during loading after reproducing the spike.
4. The standalone HIP reproducer triggers the same problem without a model.
   Both incomplete and complete first-pass stream teardown reproduce it.
   Destroying all streams after the spike does not clear it; exiting does.
5. A variant containing only stream creation/destruction reproduces it, without
   allocations, memset, user kernels, or device synchronization (mode 6).
6. `GPU_MAX_HW_QUEUES=1` prevents the spike in the standalone reproducer.
7. Keeping all streams at default priority also prevents the standalone spike
   (mode 4, independently rerun after the diagnostic process exited).

Maya creates its two layer streams at greatest priority and its chunk streams at
default priority. This makes `DS4_STREAM_PRIO=0` a targeted diagnostic. AMD's
[ROCR queue API documentation](https://rocm.docs.amd.com/projects/ROCR-Runtime/en/develop/api-reference/api.html)
describes hardware queue reuse by priority and a queue limit counted separately
for each priority. This explains why mixed priorities can change queue allocation;
the initial tests did not trace hardware queue counts. The follow-up above
subsequently measured KFD queue counts and retention directly.
No CUDA hardware was tested here. The issue's NVIDIA EXL3 comparison does not
exercise this GGUF-only automatic room-based reload.

## CUDA path review

In v1.1.55 both backends execute the same `tp_auto_plan`, `Model::load` reload,
and destructor. Both create `d.st` and `d.st2` with greatest priority by default
and the four chunk streams at default priority. Both have the same cleanup
omissions. The architecture exception for gfx103x is HIP-only; gfx1100 and CUDA
both retain high-priority layer streams when the setting is unset.

The HIP compatibility header maps `cudaStreamCreateWithPriority` directly to
`hipStreamCreateWithPriority`, and similarly maps destruction. There is no
Maya-specific HIP priority adapter to explain the difference. CUDA links its
own CUDA runtime instead. NVIDIA documents priorities as scheduling hints,
without guaranteed preemption of running work. Mixed-priority streams are a
supported configuration, not inherently an invalid Maya operation.

`ubt26` has no accessible NVIDIA device or CUDA compiler, so this is a CUDA
source/API review, not a CUDA execution result. `queues-cuda.cu` is the matching
CUDA reproducer prepared for a machine with NVIDIA hardware; it has not been
compiled or run here. Build with `nvcc -O2 queues-cuda.cu -o queues-cuda`, then
run modes 6, 1, and 4 in separate processes, sampling utilization and power.
For a full-model comparison, use GGUF and verify that the log actually says
“loading again”; an EXL3 run does not exercise the automatic room-based reload.

References:
- [Maya stream setup](https://github.com/mw00/project-maya/blob/v1.1.55/src/ds4/ds4_model.cu#L3538)
- [Maya reload](https://github.com/mw00/project-maya/blob/v1.1.55/src/ds4/ds4_model.cu#L22261)
- [NVIDIA stream priority API](https://docs.nvidia.com/cuda/cuda-driver-api/cuda_driver_api/group__CUDA__STREAM.html)

The initial stream tests isolated a queue-lifecycle/scheduling problem exposed by
repeated mixed-priority stream creation. The later KFD-count follow-up above
narrows this to oversubscription and the likely gfx11 MES timer defect. The Maya
stream leak is real but is not necessary for the power problem.

Standalone second-pass idle measurements (nine samples from 20–38 s):

| Test | Busy on all GPUs | Median watts, GPUs 0 / 1 / 2 / 3 |
| --- | --- | --- |
| Mixed priorities, incomplete teardown | 100% | 92 / 101 / 83 / 105 |
| Mixed priorities, complete teardown | 100% | 93 / 104 / 86 / 108 |
| Mixed priorities, no memset | 100% | 93 / 102 / 84 / 103 |
| Mixed priorities, stream operations only | 100% | 90 / 102 / 84 / 105 |
| Mixed priorities, `GPU_MAX_HW_QUEUES=1` | 0% | 9 / 7 / 14 / 19 |
| Default priority only, clean rerun | 0% | 13 / 8 / 10 / 16 |

The initial default-priority attempt overlapped the end of the DS4 diagnostic
shutdown and was discarded. Its clean rerun overwrote that attempt's artifacts.
For the cleanup DS4 negative test, use the first 30 seconds to localize the
failure: 0% before reset at 20 s, then 100% during the second load at 30 s.
The process was terminated at approximately 60 s; later samples include shutdown
and the discarded overlapping attempt and are not evidence about cleanup.

## Artifacts

- `queues.cpp`: standalone test with selectable teardown, priority, and
  stream-only variants. See its opening comments for mode numbers.
- `micro.py`: host sampler for the standalone test (busy percentage and power).
- `test.py`: host sampler and direct DS4 protocol harness.
- `diagnostic.patch`: temporary cleanup toggle and load markers, for diagnosis
  only. Do not deploy this as a fix.
- `*.jsonl`: timestamped telemetry. Power values are microwatts.
- `results.json`: DS4 idle summaries; the first settling sample is excluded
  from the workaround's settled statistics.

The host harnesses currently name the isolated container `maya-841-debug` and
write under `/mnt/scratch/maya-841`. The diagnostic binary and builds are also
under that scratch directory. They do not replace the installed binary.

## Runtime state after the original 7.2.13 tests

The diagnostic container is stopped. The original GLM container
`local-llm-runner-cluster-7900s-maya-0663b08f` was restarted with its original
image and settings. Its `/health` endpoint on port 8088 returned `status: ok`,
model `maya-glm53-flash-q4xl-huihui`, context 524288; Docker restart count was 0.
This restoration and health check were repeated after the queue-count tests.
The production image, local launchers, and model profiles were not modified.
At that stage, changed remote files were confined to `/mnt/scratch/maya-841`;
changed local files are confined to this diagnostics directory. The subsequent
kernel installation and boot changes are recorded in `kernel-test.md`.

The test stop/start was intentionally temporary and runtime-only. To repeat
tests, stop GLM first; rollback is starting that same original container after
the diagnostic processes exit. Diagnostic source and binaries remain in scratch
for reproducibility, and the stopped test container retains the compiler.

Compile the standalone reproducer inside the existing TheRock image:

```sh
/opt/rocm/llvm/bin/clang++ -x hip --offload-arch=gfx1100 \
  --rocm-path=/opt/rocm queues.cpp -o queues \
  -L/opt/rocm/lib -lamdhip64 -Wl,-rpath,/opt/rocm/lib
./queues 6
./queues 1
GPU_MAX_HW_QUEUES=1 ./queues 0
./queues 4
```

Use exclusive GPU access and a separate process for each case. The existing
`micro-*.jsonl` results used the same mode definitions; older console messages
say “synchronized” even in mode 6, which does not call synchronization.

The scripts that built and installed the test kernels, edited the boot config and drove QEMU are not kept in the repo:
archive `ubt26:/mnt/scratch/t7910-p2p/dropped-scripts-20261107.tgz`.
