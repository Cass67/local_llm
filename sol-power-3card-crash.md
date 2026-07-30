# Three-card ROCm/RCCL crash investigation on `ubt26`

Date: 2026-07-30

This document records the exact three-card setup, commands, failures, successful
tests, and current state. It exists so another operator can reproduce the setup
without assuming that PCIe x4, RCCL, or the PSU has already been proven guilty.

## Current conclusion

All three RX 7900 XT cards work together with llama.cpp ROCm/RCCL tensor
parallelism. RCCL communication is functional across every card pair and across
all three cards.

The machine hard-reset during several llama workloads at ubatch 384, 448, and
512. No amdgpu, MCE, AER, thermal, panic, or pstore error survived those resets.
However, after explicitly reapplying `/usr/local/sbin/ubt26-fan-tune`, the exact
same ubatch-448 profile survived workloads heavier and longer than the workloads
that previously reset the host.

**There is no saved profile difference between the failed ubatch-448 run and the
current stable ubatch-448 run.** A sorted JSON diff is empty. The confirmed
intervening action was reapplying the GPU tuning script. PSU transient handling
remains a plausible hypothesis, but current evidence does not prove that a PSU
upgrade is required.

Do not describe this as a solved PSU fault. First determine why the nominal
1900 MHz tuning was not reliably effective before it was reapplied.

## Hardware and topology

| RCCL index | PCI address | Connection | Power cap | OD SCLK max | Offset |
|---|---|---|---:|---:|---:|
| 0 | `0000:03:00.0` | internal, separate root port | 253 W | 1900 MHz | -75 mV |
| 1 | `0000:06:00.0` | internal, separate root port | 238 W | 1900 MHz | -75 mV |
| 2 | `0000:09:00.0` | PCH/OCuLink Gen3 x4 | 238 W | 1900 MHz | -75 mV |

The third card uses a separate 800 W eGPU PSU. The two internal cards use the
main Seasonic SSR-850FX 850 W PSU and separate PSU-to-GPU PCIe cables.

AMD topology reports no peer DMA/access/atomics between these cards. RCCL uses
its non-P2P shared-memory transport:

```text
Channel 00 : 0[3000] -> 1[6000] via SHM/direct/direct
Channel 00 : 1[6000] -> 2[9000] via SHM/direct/direct
Channel 00 : 2[9000] -> 0[3000] via SHM/direct/direct
```

The x4 link is not an inherent blocker. Three-rank RCCL collectives passed over
this topology.

Kernel command line includes `iommu=pt`. Verification:

```bash
cat /proc/cmdline
journalctl -k -b | grep 'Default domain type: Passthrough'
```

## Exact software

- llama.cpp commit: `9ebfc3a8cf4c1c6983258c4d603274b2b3d3dd65`
- ROCm: 7.2
- RCCL: 2.27.7
- Runner image: `local-llm-runner-rocm:latest`
- Exact image ID:
  `sha256:219f8855592d401ae7864b5fe2daec7a8ef1dc234db153a6d5f816522689f9ff`
- Build defaults force hipBLAS with `GGML_CUDA_FORCE_CUBLAS=ON`
- llama.cpp was built with `-DGGML_HIP_RCCL=ON`
- Docker runner `/dev/shm`: 1 GiB

Relevant source files:

- `runner/rocm/Dockerfile`
- `container/backend/runtime.py`
- `container/tests/test_runtime_docker.py`
- `scripts/ubt26-fan-tune`

The 1 GiB shared-memory setting is required. Docker's default 64 MiB caused:

```text
failed to extend /dev/shm/...: No space left on device
NCCL init failed
internal AllReduce init failed ... falling back to meta-backend butterfly
```

With 1 GiB, RCCL initialization uses about 216 MiB and does not fall back.

Verify live container image and shared memory:

```bash
c=local-llm-runner-cluster-7900sr-8b4bdf95
docker inspect "$c" --format \
  'image={{.Image}} status={{.State.Status}} restarts={{.RestartCount}} shm={{.HostConfig.ShmSize}}'
docker exec "$c" df -h /dev/shm
docker logs "$c" 2>&1 | \
  grep -Ei 'NCCL init failed|AllReduce init failed|butterfly'
```

Expected image ID and shm value:

```text
image=sha256:219f8855592d401ae7864b5fe2daec7a8ef1dc234db153a6d5f816522689f9ff
shm=1073741824
```

The warning below is unrelated to RCCL or model offload:

```text
common_specu: backend offload failed for seq_id=0; using CPU sampler
```

llama.cpp does not support backend token sampling with
`SPLIT_MODE_TENSOR`. Only top-k/top-p/temperature/penalty/final-token sampling
falls back to CPU. Model layers, KV, prefill, decode, and RCCL remain on GPUs.

## Exact model

Management family/alias:

```text
qwen3.6-27b-fable-fusion-711-uncensored-heretic-nm-dau-neo-max-mtp-gguf-rocm
```

Model file in the container:

```text
/models/models--DavidAU--Qwen3.6-27B-Fable-Fusion-711-Uncensored-Heretic-NM-DAU-NEO-MAX-MTP-GGUF/snapshots/b73a29e861a1922ca7b508790c254c91158ec4bb/Qwen3.6-27B-Fable-Fus-711-UnHeretic-NM-DAU-NEO-MAX-NEO-MTP-Q8_0.gguf
```

Multimodal projector:

```text
/models/models--DavidAU--Qwen3.6-27B-Fable-Fusion-711-Uncensored-Heretic-NM-DAU-NEO-MAX-MTP-GGUF/snapshots/b73a29e861a1922ca7b508790c254c91158ec4bb/mmproj-F16.gguf
```

## Exact cluster

```text
id:             8b4bdf95
name:           7900sr
backend:        rocm
port:           8080
container:      local-llm-runner-cluster-7900sr-8b4bdf95
GPU PCI IDs:    0000:03:00.0, 0000:06:00.0, 0000:09:00.0
```

Inspect it through management:

```bash
curl -fsS http://127.0.0.1:3100/api/clusters | jq \
  '.clusters[] | select(.id == "8b4bdf95")'
```

Start it through management, not with a competing manual server:

```bash
cid=8b4bdf95
family=qwen3.6-27b-fable-fusion-711-uncensored-heretic-nm-dau-neo-max-mtp-gguf-rocm

curl -fsS -X POST "http://127.0.0.1:3100/api/clusters/$cid/stop" | jq .
curl -fsS -X POST "http://127.0.0.1:3100/api/clusters/$cid/start" \
  -H 'Content-Type: application/json' \
  -d "{\"family\":\"$family\",\"profile\":\"rccl\"}" | jq .
```

Verify desired and active state after start:

```bash
curl -fsS http://127.0.0.1:3100/api/clusters | jq \
  '[.clusters[] | select(.id == "8b4bdf95") |
    {id, name, port, gpu_pci_ids, active, desired}]'
```

Expected `active.running` is `true`; expected desired profile is `rccl`.

## Exact current profile

Remote model-manager state is the runtime source of truth:

```text
$HOME/.local/share/local_llm/profiles.json
```

Do not manually edit it while management is running. Use the profile API.
Current `rccl` profile:

```json
{
  "batch": 4096,
  "ngl": 999,
  "split_mode": "tensor",
  "tensor_split": "1,1,1",
  "ubatch": 448,
  "visible_devices": "0,1,2",
  "context": 92160,
  "reasoning": false,
  "cache_ram": 16384,
  "ctx_checkpoints": 8,
  "checkpoint_min_step": 2048,
  "timeout": 600,
  "threads_http": 2,
  "parallel": 1,
  "prio": 2,
  "flash_attention": true,
  "jinja": true,
  "mtp_enabled": true,
  "mtp_draft_n_max": 2,
  "temperature": 0.7,
  "top_p": 0.95,
  "top_k": 20,
  "min_p": 0,
  "repetition_penalty": 1,
  "presence_penalty": 0,
  "mmproj": "/models/models--DavidAU--Qwen3.6-27B-Fable-Fusion-711-Uncensored-Heretic-NM-DAU-NEO-MAX-MTP-GGUF/snapshots/b73a29e861a1922ca7b508790c254c91158ec4bb/mmproj-F16.gguf",
  "flags": "--image-min-tokens 1024 -fit off",
  "cache_type_k": "f16",
  "cache_type_v": "f16",
  "spec_type": "draft-mtp,ngram-mod",
  "ngram_mod_n_match": 24,
  "ngram_mod_n_min": 24,
  "ngram_mod_n_max": 86
}
```

Read live profile:

```bash
family=qwen3.6-27b-fable-fusion-711-uncensored-heretic-nm-dau-neo-max-mtp-gguf-rocm
curl -fsS "http://127.0.0.1:3100/api/profiles/$family" | jq '.profiles.rccl'
```

Save a profile body to `rccl.json`, then update it with:

```bash
curl -fsS -X PUT \
  "http://127.0.0.1:3100/api/profiles/$family/rccl" \
  -H 'Content-Type: application/json' \
  --data-binary @rccl.json | jq .
```

Profile updates restart active clusters that use the profile. Confirm final
container arguments after every update.

## Exact llama-server arguments

The managed container currently runs:

```text
llama-server
--port 8080
-m /models/models--DavidAU--Qwen3.6-27B-Fable-Fusion-711-Uncensored-Heretic-NM-DAU-NEO-MAX-MTP-GGUF/snapshots/b73a29e861a1922ca7b508790c254c91158ec4bb/Qwen3.6-27B-Fable-Fus-711-UnHeretic-NM-DAU-NEO-MAX-NEO-MTP-Q8_0.gguf
-ngl 999
--split-mode tensor
--tensor-split 1,1,1
-c 92160
-b 4096
-ub 448
--alias qwen3.6-27b-fable-fusion-711-uncensored-heretic-nm-dau-neo-max-mtp-gguf-rocm
--reasoning off
--cache-ram 16384
--ctx-checkpoints 8
--checkpoint-min-step 2048
--presence-penalty 0
--timeout 600
--threads-http 2
--parallel 1
--prio 2
--spec-type draft-mtp,ngram-mod
--spec-draft-n-max 2
--spec-ngram-mod-n-match 24
--spec-ngram-mod-n-min 24
--spec-ngram-mod-n-max 86
--temp 0.7
--top-p 0.95
--top-k 20
--min-p 0
--repeat-penalty 1
--cache-type-k f16
--cache-type-v f16
-fa on
--jinja
--mmproj /models/models--DavidAU--Qwen3.6-27B-Fable-Fusion-711-Uncensored-Heretic-NM-DAU-NEO-MAX-MTP-GGUF/snapshots/b73a29e861a1922ca7b508790c254c91158ec4bb/mmproj-F16.gguf
--image-min-tokens 1024
-fit off
```

Inspect exact arguments instead of reconstructing them from the profile:

```bash
c=local-llm-runner-cluster-7900sr-8b4bdf95
docker inspect "$c" --format '{{range .Args}}{{println .}}{{end}}'
```

Container environment includes:

```text
HIP_VISIBLE_DEVICES=0,1,2
```

## GPU tuning procedure

Repository source:

```text
scripts/ubt26-fan-tune
```

Installed runtime copy:

```text
/usr/local/sbin/ubt26-fan-tune
```

The script applies, to all three cards:

- `power_dpm_force_performance_level=manual`
- compute power profile `4`
- SCLK states `0 1`
- MCLK state `3`
- OD SCLK maximum 1900 MHz
- voltage offset -75 mV
- power caps 238/253/238 W according to DRM card index
- explicit fan curves with zero-RPM disabled

**Important:** DRM `cardN` numbering is not guaranteed to equal PCI ordering after
hardware or driver changes. On the tested boot, verify each card with PCI paths,
not only `card0/card1/card2` labels.

Reapply tuning explicitly before a high-ubatch test:

```bash
sudo /usr/local/sbin/ubt26-fan-tune
```

Verify by PCI address:

```bash
for b in 03 06 09; do
  d=/sys/bus/pci/devices/0000:$b:00.0
  h=$(echo "$d"/hwmon/hwmon*)
  echo "[$b:00.0] cap=$(cat "$h/power1_cap") perf=$(cat "$d/power_dpm_force_performance_level")"
  grep -A2 -E '^OD_SCLK:|^OD_VDDGFX_OFFSET:' "$d/pp_od_clk_voltage"
done
```

Expected live state:

```text
03:00.0 cap=253000000, manual, max 1900 MHz, -75 mV
06:00.0 cap=238000000, manual, max 1900 MHz, -75 mV
09:00.0 cap=238000000, manual, max 1900 MHz, -75 mV
```

Do not trust `hwmon/freq1_input` or `power1_average` transient samples from this
kernel as proof that caps were exceeded. During tests they reported impossible
values above firmware maximums while cap files remained correct. Use integrated
telemetry or AMD SMI and preserve raw samples.

## NVIDIA retirement cleanup

The removed Tesla P40 left an enabled P40-only airflow daemon, a boot-time
`nvidia-smi` call, NVIDIA driver/toolkit packages, and a Docker runtime entry.
`ubt26-airflowd` called `nvidia-smi` every five seconds and failed with an
unbound `NVIDIA` value. Each call loaded and unloaded the driver, flooding the
kernel log with:

```text
nvidia-nvlink: Nvlink Core is being initialized
NVRM: No NVIDIA GPU found.
nvidia-nvlink: Unregistered Nvlink Core
```

Cleanup performed on 2026-07-30:

- removed `apply_nvidia_eco` from `scripts/ubt26-fan-tune` and installed copy;
- disabled and removed `ubt26-airflowd.service` and
  `/usr/local/sbin/ubt26-airflowd` because its AMD path was commented out and it
  controlled only the retired P40 blower;
- purged 25 NVIDIA driver, kernel-module, userspace, and container-toolkit
  packages without running broad `apt autoremove`;
- removed unowned `/etc/nvidia-container-runtime` and
  `/lib/firmware/nvidia` leftovers;
- removed the `nvidia` runtime from `/etc/docker/daemon.json`;
- restarted Docker and verified automatic restoration of `7900sr`.

Backup and package logs:

```text
$HOME/bench-results/nvidia-removal-20260730-215911/
```

Rollback material there includes the old fan/airflow scripts, airflow unit,
pre-change Docker daemon configuration, package list, apt log, and compressed
residual NVIDIA configuration/firmware.

Expected post-cleanup checks:

```bash
command -v nvidia-smi || echo nvidia_smi_absent
lsmod | grep '^nvidia' || echo nvidia_modules_absent
systemctl list-unit-files --no-pager | grep -i nvidia || echo nvidia_units_absent
docker info --format '{{json .Runtimes}}' | jq 'keys'
journalctl -k --since '10 seconds ago' --no-pager | \
  grep -E 'No NVIDIA GPU found|nvidia-nvlink' || echo none
```

Docker should list only `io.containerd.runc.v2` and `runc`. The three-card ROCm
container must remain running with zero restarts after cleanup.

## RCCL isolation tests performed

A small C++ RCCL all-reduce probe was built against the exact ROCm 7.2/RCCL
2.27.7 image. Build files and image are on `ubt26`:

```text
$HOME/bench-results/rccl-probe-build/
local-llm-rccl-probe:7.2
```

Diagnostic artifact:

```text
$HOME/bench-results/rccl-probe-20260730-203334/
```

Representative invocation:

```bash
docker run --rm \
  --network host \
  --device /dev/kfd \
  --device /dev/dri \
  --group-add 992 \
  --shm-size 1g \
  -e NCCL_DEBUG=INFO \
  -e NCCL_DEBUG_SUBSYS=INIT,GRAPH,P2P,SHM,NET,COLL \
  local-llm-rccl-probe:7.2 0 1 2
```

Results:

| Test | Result |
|---|---|
| GPU 0 only | pass |
| pair 0+1 | 20 iterations pass |
| pair 0+2 | 20 iterations pass |
| pair 1+2 | 20 iterations pass |
| three ranks, one float | 20 iterations pass |
| three ranks, 4 MiB/rank | 10 iterations pass |
| three ranks, 64 MiB/rank | 3 iterations pass |

Large example:

```bash
docker run --rm \
  --network host \
  --device /dev/kfd \
  --device /dev/dri \
  --group-add 992 \
  --shm-size 1g \
  -e NCCL_DEBUG=WARN \
  -e PROBE_COUNT=16777216 \
  -e PROBE_ITERS=3 \
  local-llm-rccl-probe:7.2 0 1 2
```

This transfers 64 MiB per rank per iteration. It passed with no fresh kernel
faults. Therefore RCCL, SHM, and the Gen3 x4 path are functional in isolation.

## llama workload chronology

Representative request files:

```text
$HOME/bench-results/rocm-rccl-cublas-92k-stability-20260730-152918/request-1.json
$HOME/bench-results/rocm-rccl-cublas-92k-stability-20260730-152918/request-2.json
$HOME/bench-results/rocm-rccl-cublas-92k-stability-20260730-152918/request-3.json
```

Each is about 21,368 bytes and produces approximately 5,438 prompt tokens plus
400 generated tokens.

Request command:

```bash
curl -fsS --max-time 180 \
  http://127.0.0.1:8080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  --data-binary \
  "@$HOME/bench-results/rocm-rccl-cublas-92k-stability-20260730-152918/request-1.json" \
  > response.json
```

Observed chronology:

| State | Result |
|---|---|
| three GPUs, ubatch 256 | one request passed in 19.40 s |
| three GPUs, ubatch 384 | one request passed in 18.69 s |
| three GPUs, ubatch 512 | host hard-reset during request |
| three GPUs, ubatch 448 | host hard-reset during request |
| three GPUs, ubatch 384 | first sustained request passed; immediate second request reset host |
| explicit tuning-script reapplication, ubatch 256 | three back-to-back requests passed: 19.19, 17.71, 19.76 s |
| current exact ubatch-448 profile | multiple much larger workloads now pass |

The resets were abrupt. The host returned without persisted amdgpu faults,
GPU reset messages, MCE, AER, thermal events, kernel panic, or pstore record.
That behavior suggested electrical protection or a low-level ROCm/driver fault,
but neither was proven.

Backups and artifacts:

```text
$HOME/bench-results/3gpu-rccl-shm-fix-20260730-200950/
$HOME/bench-results/rccl-3gpu-profile-20260730-203817/
$HOME/bench-results/rccl-3gpu-staged-20260730-203726/
```

Saved failed ubatch-448 profile:

```text
$HOME/bench-results/rccl-3gpu-profile-20260730-203817/rccl-ub448.json
```

The saved failed profile and current live profile compare equal:

```bash
family=qwen3.6-27b-fable-fusion-711-uncensored-heretic-nm-dau-neo-max-mtp-gguf-rocm
tmp=$(mktemp)
curl -fsS "http://127.0.0.1:3100/api/profiles/$family" |
  jq -S '.profiles.rccl' > "$tmp"
diff -u \
  <(jq -S . "$HOME/bench-results/rccl-3gpu-profile-20260730-203817/rccl-ub448.json") \
  "$tmp"
rm -f "$tmp"
```

Expected output: none.

## Current stable workload evidence

After the tuning script was explicitly reapplied, current logs showed three
separate approximately 47.4k-token prefills at ubatch 448:

```text
prompt eval time = 92283.04 ms / 47486 tokens (514.57 tokens/s)
prompt eval time = 92172.96 ms / 47429 tokens (514.57 tokens/s)
prompt eval time = 92627.58 ms / 47698 tokens (514.94 tokens/s)
```

A later decode-heavy request also completed:

```text
prompt eval time =   667.69 ms /   73 tokens (109.33 tokens/s)
eval time        = 65993.42 ms / 3000 tokens (45.46 tokens/s)
total time       = 66661.11 ms / 3073 tokens
```

These runs are longer and more demanding than the request that previously reset
at ubatch 448. Workload shape alone no longer explains the difference.

View timing lines without printing request content:

```bash
c=local-llm-runner-cluster-7900sr-8b4bdf95
docker logs --since 30m "$c" 2>&1 | grep -E \
  'prompt eval time|eval time|prompt processing|total time' | tail -100
```

## VRAM state

At 92k context and ubatch 256, measured free VRAM was:

```text
03:00.0: 6.47 GiB free
06:00.0: 7.70 GiB free
09:00.0: 7.64 GiB free
aggregate: 21.80 GiB free
```

Measure per device; aggregate free memory is not sufficient proof that a larger
ubatch fits because each device must satisfy its largest local allocation:

```bash
for b in 03 06 09; do
  d=/sys/bus/pci/devices/0000:$b:00.0
  total=$(cat "$d/mem_info_vram_total")
  used=$(cat "$d/mem_info_vram_used")
  awk -v b="$b" -v t="$total" -v u="$used" \
    'BEGIN { printf "%s: used %.2f GiB, free %.2f GiB\n", b, u/2^30, (t-u)/2^30 }'
done
```

Ubatch 2048 is plausible with three cards but not yet validated. Test per-device
headroom rather than assuming that all 21.8 GiB can satisfy one allocation.

## What Claude should investigate next

1. Preserve the currently stable container and collect its complete state before
   changing anything:

   ```bash
   c=local-llm-runner-cluster-7900sr-8b4bdf95
   docker inspect "$c" > "$HOME/bench-results/current-stable-7900sr-inspect.json"
   docker logs "$c" > "$HOME/bench-results/current-stable-7900sr.log" 2>&1
   cat /proc/cmdline
   ```

2. Confirm tuning-script service ordering and success after boot. Compare tuning
   immediately after boot, after model load, and under load. The explicit script
   invocation is the only confirmed state-changing action between failed and
   currently stable ubatch-448 runs.

3. Replace `cardN`-based power-cap assignment in the script with PCI-address-based
   assignment. DRM enumeration can change and silently assign the 253 W cap to a
   different physical card.

4. Capture reset cause externally if failures return: PSU telemetry, BMC/IPMI,
   smart PDU, oscilloscope, or netconsole/pstore. Software logs did not survive.

5. Do not blame RCCL without a failing collective reproducer. Pairwise and
   three-rank 64 MiB collectives passed.

6. Do not call the 1200 W PSU a confirmed fix. It offers useful transient margin,
   but the unchanged profile is currently stable on the existing PSU.

7. If increasing ubatch, use a ladder and multiple immediate back-to-back runs:
   512, 768, 1024, 1536, 2048. A single successful request was insufficient at
   ubatch 384 during this investigation.

8. After every change verify:

   ```bash
   docker inspect local-llm-runner-cluster-7900sr-8b4bdf95 \
     --format 'status={{.State.Status}} restarts={{.RestartCount}} shm={{.HostConfig.ShmSize}}'
   curl -fsS http://127.0.0.1:8080/v1/models | jq '.data[0].id'
   journalctl -k --since '10 minutes ago' --no-pager | \
     grep -Ei 'amdgpu.*(fault|reset|error)|watchdog|lockup|mce|fatal'
   ```

## Rollback

Proven two-card production cluster:

```text
id:       5a6a678e
name:     7900srccl
GPUs:     0000:03:00.0, 0000:06:00.0
port:     8086
profile:  rccl
tensor:   1,1
context:  92160
ubatch:   512
```

Stop the three-card cluster before starting the two-card cluster so no two
servers compete for the internal cards:

```bash
curl -fsS -X POST http://127.0.0.1:3100/api/clusters/8b4bdf95/stop | jq .

family=qwen3.6-27b-fable-fusion-711-uncensored-heretic-nm-dau-neo-max-mtp-gguf
curl -fsS -X POST http://127.0.0.1:3100/api/clusters/5a6a678e/start \
  -H 'Content-Type: application/json' \
  -d "{\"family\":\"$family\",\"profile\":\"rccl\"}" | jq .
```

Before rollback, verify which family the two-card cluster expects. Earlier
production used the ROCm family without the `-rocm` suffix; model-family copy
work was still incomplete, so do not assume aliases are interchangeable.
