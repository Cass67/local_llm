# Live changes on ubt26

What runs on the GPU host, and every change made to it. Add an entry for each change to a live service, image,
profile, host setting or fan/power setting, newest first. Use the template at the bottom. The "Live now" section
always describes the current state, so update it in the same commit.

Speed figures are the bench of their day (old box, the 8-prompt set, then `pair.py` warm rounds). Read each entry's
before -> after as that change's gain. The figures do not chain into one number.

## Live now

**Model:** `maya-glm53-xs` (full GLM-5.3 744B, Maya-XS, upstream glm-dsa on engine `maya`, args/env below) on
cluster `0663b08f`, port 8088, ctx 65536, 4x RX 7900 XT, Dell T7910 (2x E5-2699 v4, 1 TB RAM). DS4
(`maya-dsv41-q4xl-huihui`, the usual default) and Hy4 (`maya-hy4-flash-q4km`) are configured but stopped.

**GLM-5.3 args:** `--glm-pack /mnt/models/maya-glm53/Maya-XS/pack --expert-cache auto --prefill auto --kv-streaming off`;
env `MAYA_GLM_RESERVE_MB=512`, `MAYA_GLM_RAM_HEADROOM_GB=16`, `MAYA_GLM_PREFILL_SUB=1024`, `MAYA_GLM_PREFILL_MB=4096`,
`MAYA_GLM_SPLIT_CARDS=19.89:800,19.89:800,19.89:800,19.89:800` (real bandwidth for the split search; HIP reads 100 GB/s),
`MAYA_GLM_SPLIT_LOG=1`, `MAYA_GLM_SAME_ANSWERS=0` (v1.1.75's fixed draft length / no lane re-plan off); temp 1.0 / top_p 0.95, effort high. Split auto -> 22/16/20/20.

**Image:** `local-llm-runner-maya:latest` = `:v1.1.75-ra` (`a957a466`): Maya v1.1.75 (8621f7a7) + patches in
`runner/maya/patches` (ML4 families need image `:v1.1.56-ra906`):
- 0013: DS4 CPU-lane read-ahead (engine branch `ds4-decode-graph` a08d45e on Cass67/project-maya).
- 0016: glm-dsa layers set `Ly.ff/ffd/f0` (v1.1.75 left them 0 -> every full GLM-5.3 launch failed).
- 0015 dropped: maya-hy4 on HIP is upstream since v1.1.68. 0014 dropped: #906 is upstream (c89ebef).

**Hy4 args:** `--pack /mnt/models/angelslim-hy4-flash/maya-hy4 --max-context 524288 --tp 0 --mtp --chunk 2048
--profile-out <pack>/expert-profile.bin` (layer split - TP needs every expert in VRAM; 50% of routed experts in VRAM,
rest on the CPU lane), sampling temp 0.9 / top_p 1.0, effort high. No `HY4_*` env; DS4's switches do not apply.

**DS4 args:** `--pack /mnt/models/unsloth-dsv41/UD-Q4_K_XL/maya-ds4 --tp 4 --reserve-mib 512 --vision on --dspark on
--mmap-experts off --experts 6 --prefill-chunk 16384`

**DS4 env** (profile `default`, live state `~/.local/share/local_llm/profiles.json` on ubt26):

| Group | Settings |
|---|---|
| Memory | `DS4_REQUIRE_ALL_RAM=1`, `DS4_ENGRAM_RAM=1` |
| Prompt path | `DS4_FLOW_TP=1`, `DS4_INDEX_TC=1`, `MAYA_DS4_TP_BORROW=1`, `MAYA_DS4_YOCO_TP=1` |
| Tensor-parallel layout | `DS4_TP_SHARES=off`, `MAYA_DS4_TP_GGUF_UNEVEN=1` |
| Fusion and trimming | `MAYA_DS4_HC_FUSE=2`, `MAYA_DS4_ROUTE_FUSE=2`, `MAYA_DS4_DECODE_TRIM=15`, `MAYA_DS4_Q8_BATCH=1`, `MAYA_DS4_EXPERT_MMQ=1` |
| All-reduce | `MAYA_DS4_AR2_DECODE=1`, `MAYA_DS4_FLOW_AR_DMA=1` |
| Router | `MAYA_DS4_ROUTER_BF16=1`, `MAYA_DS4_ROUTER_CHECK=1` |
| Drafter (DSpark) | `MAYA_DS4_DRAFT_DEV=0,1,2`, `MAYA_DS4_DRAFT_VRAM=32,32,32` |
| Slots | `MAYA_DS4_SLOT_KEEP=1` |
| CPU lane | `MAYA_DS4_RAM_SKIP_W=0.16` (lossy), `MAYA_DS4_AHEAD_RAM=1`, `MAYA_DS4_LANE_PF=2` |

**Host:** runner containers get `CAP_SYS_NICE` and the seccomp profile `container/backend/seccomp-runner.json`
(Docker's default + `move_pages`) (`container/backend/runtime.py`). GPU fans: `scripts/gpu-fan-floor`
(target 85 C, min pwm 35, zero-rpm on), re-applied every 10 min by `gpu-fan-floor.timer`. GPU board power: `scripts/gpu-power-cap` at boot,
04/a3 253 W, 09/a6 238 W (BIOS floors); `amdgpu-powercap.service` (raise to 333 W) disabled.
GPU 04:00.0 sits in Slot1 (root port 00:01.1, capped x4 Gen3); Slot2 (05:00.0, x16) is empty since the 11-10 rack move.

**Speed now:** GLM-5.3 Maya-XS at 18.9K: prefill 292 tok/s, decode 11.3 cold / 12.7 cached (CPU-lane bound, 75% VRAM
hit). DS4 (stopped) prefill ~375 tok/s at 40K warm, ~525 -> ~440 tok/s per chunk across a 456K read (x4 CUDA0 link,
3.2 GB/s vs 13.6). Warm decode 55.6 tok/s on v1.1.65 with the 238/253 W caps. Hy4 (stopped): decode 25-30 tok/s.

**Rollback tags:** `before-v1.1.75-20261123` (v1.1.72 + 0013), `before-v1.1.70-20261120` (v1.1.67 + #1040 + 0013/0015), `before-hy4b-20261118` (first 0015), `before-v1.1.67-20261118` (v1.1.65 + 0013/0014), `before-v1.1.65-20261117` (v1.1.58 + 0013/0014), `before-v1.1.58-20261111` (v1.1.56 + 0012-0014), `before-906-20261107` (read-ahead without 0014), `before-v1.1.56-20261107` (v1.1.55).

## Log

### 2026-11-23 Maya v1.1.75 + 0016 (glm-dsa fix)
- What: `local-llm-runner-maya:v1.1.75-ra` a957a466 = v1.1.75 (8621f7a7) + 0013 + new 0016, built in ubt26
  /mnt/scratch/maya-v1.1.75 (buildx zstd), retagged `:latest`. Dockerfile CMake options renamed `STRATA_*` ->
  `MAYA_*` (upstream rename; old names still accepted). `maya-glm53-xs` maya_env + `MAYA_GLM_SAME_ANSWERS=0`.
- Why: user asked to move to the latest Maya and look for speedups. v1.1.73-75 is mostly Inkling 2 Mini / NVIDIA;
  for us: #1026 reserve held for the whole run, GLM same-answers default (fixed MTP draft length 2 unless maya.py setup
  calibrates it - our runner skips that; upstream measured decode -6% / prompt -2.5%), so turned off.
- Bug: stock v1.1.75 fails every full GLM-5.3 request (`glm_fast mv` / `moe_gate_up: invalid configuration argument`,
  with and without SAME_ANSWERS). GLM-TP rework (2e6d9410) made the shared MoE code size launches from `Ly.ff`, which
  only the Flash loader sets; `fast_bind_dsa` (glm_dsa_fast.cu) leaves it 0. 0016 sets ff/ffd/f0 there. Hits CUDA too.
- Effect (~/scratch/glm53-xs/depth.py, bench-v1175.log; prompts a bit longer than the v1.1.72 run): 3.1K 109 prefill /
  11.9 decode (first request after restart); 18.9K prefill 292, decode 11.33 cold / 12.72 cached (v1.1.72 at 16.7K:
  276, 11.39 / 13.21). Flat - no speedup for this model. VRAM hit 72-75%, CPU lane 41-50 ms/tok. Reserve held (510-618
  MiB free/card), split 22/16/20/20, 0 restarts. ~15 min outage from the stock-image attempt (rolled back meanwhile).
- Rollback: `docker tag local-llm-runner-maya:before-v1.1.75-20261123 local-llm-runner-maya:latest`, drop
  `MAYA_GLM_SAME_ANSWERS` (harmless either way), restart 0663b08f (profile PUT). Profiles backup
  ~/.local/share/local_llm/profiles.json.bak-20261123-pre-v1175.
- Commit: this entry's commit ("runner/maya: v1.1.75 + 0013 + 0016 ...").

### 2026-11-21 Maya v1.1.72 + full GLM-5.3 744B Maya-XS (upstream's glm-dsa port)
- What: `local-llm-runner-maya:v1.1.72-ra` 886084fe = v1.1.72 (cce2de0e) + 0013, built in ubt26
  /mnt/scratch/maya-v1.1.72 (buildx zstd), retagged `:latest`. New family `maya-glm53-xs`: peasantsmith
  GLM-5.3-Maya-GGUF Maya-XS (rev 2fb34fe0, 4 shards sha256 OK) in /mnt/models/maya-glm53/Maya-XS, pack built in the
  image (`tools/iq_pack.py --compat-bf16` + stamp/template). Started on 0663b08f in place of DS4.
- Why: user asked to measure upstream's own full GLM-5.3 port against ours (Cass67/project-maya `glm53-port`, closed
  10-29 at 8.9-9.0 decode / ~227-258 prefill at 16.7K, CPU-lane bound).
- Split fix: HIP reports no memory clock/bus width, so the split search priced every card at 100 GB/s (= host RAM)
  and put 1/1/52/24 layers on the cards, 0 expert slots on CUDA0/1, CUDA2 token-by-token prefill (~7 tok/s), 219 ms
  predicted. `MAYA_GLM_SPLIT_CARDS=19.89:800,...` (glm-dsa only; stands in for the readings) -> auto picks 22/16/20/20,
  ~58 GB of expert pools, batched prefill on all cards.
- Effect (~/scratch/glm53-xs/depth.py = old port's harness, 400 tokens, no thinking): warm 2.5K 12.83 decode; 16.7K
  prefill 276 tok/s, decode 11.39 cold / 13.21 prompt-cached. glm stat 75.5 ms/tok, VRAM hit 75%, CPU lane 48.7 ms/tok.
  vs our port's base 8.9 at 16.7K: +28-48% decode. Context 65536 (KV in VRAM, no KV streaming upstream). 0 restarts.
  Clients synced to ctx 63488 / output 32768 (model-switch sync on Mac, ubt26, fed).
- Rollback: `docker tag local-llm-runner-maya:before-v1.1.72-20261121 local-llm-runner-maya:latest`, then
  POST /api/clusters/0663b08f/start {"family":"maya-dsv41-q4xl-huihui","profile":"default"}; model-switch sync.

### 2026-11-20 Maya v1.1.70: compactions in picture conversations stop re-reading from token 0
- What: `local-llm-runner-maya:v1.1.70-ra` b90b1bc8 = v1.1.70 (b6632a0b) + 0013; 0015 dropped (upstream). Built in
  ubt26 /mnt/scratch/maya-v1.1.70 (buildx zstd), retagged `:latest`, DS4 restarted on 0663b08f.
- Why: opencode v2 compaction branches one response back; the old server gave prompts with pictures no restore points,
  so every compaction in a 7-picture session read 407-456K tokens from 0 (6 in 46 h, 14-16 min each). Upstream #1007
  fixes it; #1070 (vision tower no longer takes ROCm HW queues at load) comes along.
- Effect: picture conversation branched one response back: 22060 reused + 12 read (0.3 s). Warm 40.5K read 375 tok/s
  (old image 350-400 at 50-60K: flat). Health 1.1.70, /v1/models 524288, 0 restarts, idle GPUs 0% busy.
- Rollback: `docker tag local-llm-runner-maya:before-v1.1.70-20261120 local-llm-runner-maya:latest`, then
  POST /api/clusters/0663b08f/start {"family":"maya-dsv41-q4xl-huihui","profile":"default"}.

### 2026-11-18 Runner seccomp profile: move_pages for maya-hy4's NUMA placer
- What: new `container/backend/seccomp-runner.json` (Docker 29.1.3's default profile + `move_pages`, gated on
  CAP_SYS_NICE); `runtime.py` passes it as `HostConfig.SecurityOpt` on every runner. mgmt HOT-PATCHED (docker cp of
  both files into /app/backend, mgmt restarted; backup `~/.local/share/local_llm/runtime.py.bak-20261118-seccomp`),
  Hy4 restarted on 0663b08f. Test in `container/tests/test_runtime_docker.py`.
- Why: Docker's default profile has no rule for `move_pages` (EPERM even with SYS_NICE), so maya-hy4's placer silently
  left ~96% of the model's pages on node 0 and both sockets' CPU-lane threads read socket 0's memory.
- Effect: CPU-lane experts now split by expert number (node 1: 7.9 -> 27 GB). Lane 56 -> 70 GB/s, verify round
  135 -> 121-126 ms; decode 27.2 -> 28.8/29.6 tok/s (`--gen` 512, code/prose), live 29.5-30.3 tok/s on 700-token
  code answers. 0 restarts.
- Rollback: `docker cp ~/.local/share/local_llm/runtime.py.bak-20261118-seccomp local-llm-mgmt:/app/backend/runtime.py`,
  restart mgmt, restart the cluster (the pages already moved stay put until evicted).

### 2026-11-18 Hy4 image with the upstream-candidate 0015
- What: `local-llm-runner-maya:v1.1.67-hy4b` a9c5bc6c = same base, 0015 replaced by the version sent upstream
  (Cass67 hy4-hip e73129a, PR needmorevram/project-maya#1): shared `include/strata/kernels/fresh_load.hpp`, clock
  guarded to gfx11/12, setup takes HIP on Linux, docs. build-runner.sh (zstd), retagged `:latest`, Hy4 restarted.
- Why: run what was submitted upstream.
- Effect: same device code on gfx1100. Load 22.4 s, 512K, 79.4 GB VRAM; answers, 4.4K prompt (172 tok/s prefill),
  tool call ok; 0 restarts.
- Rollback: `docker tag local-llm-runner-maya:before-hy4b-20261118 local-llm-runner-maya:latest`, restart the family.

### 2026-11-18 Hy4-flash: 512K context, chunk 2048, expert profile collection
- What: `maya-hy4-flash-q4km` args `--max-context 524288 --chunk 2048 --profile-out <pack>/expert-profile.bin` (was
  131072, default chunk 1024). Live `profiles.json` + `runs/accepted/` (backups `*.bak-20261118-hy4-512k`,
  `maya-hy4-flash-q4km.json.bak-20261118`) and repo seeds.
- Why: user needs 512K. Chunk 2048 is the PR's measured setting; the profile file feeds a later `--profile`.
- Effect: experts in VRAM 61% -> 50%, 79.4 GB VRAM. Decode 24.6/29.6 tok/s short (was 28.4/33.3), 18.4 after 4.4K
  (was 20.3); prefill 171 tok/s at 4.4K (was 158). Answers + tool call ok, 0 restarts, /v1/models 524288.
  Upstream only tested to 128K.
- Rollback: restore `profiles.json.bak-20261118-hy4-512k` + the accepted backup, then restart the family on 0663b08f.

### 2026-11-18 Hy4-flash on maya-hy4 (Maya v1.1.67 + PR #1040)
- What: image `local-llm-runner-maya:v1.1.67-hy4` 5aea13d9 = PR #1040 head 444855d (v1.1.67 + Hy4-flash engine) +
  0013 + new 0015 (HIP port), 0014 dropped (upstream). build-runner.sh (zstd), retagged `:latest`. New family
  `maya-hy4-flash-q4km` (repo `configs/profiles.json` + `configs/accepted/`, live `profiles.json` + `runs/accepted/`;
  backup `profiles.json.bak-20261118-hy4`). `maya-runner.py` picks `maya-hy4` for a pack with `hy4.txt`. Model
  `/mnt/models/angelslim-hy4-flash` (pinned ecd803c8, sha256 match), pack via `tools/hy4/pack_gguf.py`.
  Cluster 0663b08f switched to Hy4; DS4 left stopped at the user's request.
- Why: user wanted Hy4-flash on AMD; upstream engine was NVIDIA-only.
- Effect: hy4_kernels_test + hy4_experts_test pass on gfx1100. Load 22.8 s, 77.5 GB VRAM, 12751/20992 experts in
  VRAM. Decode 28-33 tok/s (MTP), 20 tok/s after 4.4K prompt; prefill 158 tok/s. Thinking, tool calls ok; 0 restarts;
  /v1/models advertises 131072. DS4 started once on the new image (ready, 512K ctx) but was not benched.
- Rollback: `docker tag local-llm-runner-maya:before-v1.1.67-20261118 local-llm-runner-maya:latest`, then
  POST /api/clusters/0663b08f/start {"family":"maya-dsv41-q4xl-huihui","profile":"default"}.

### 2026-11-17 Maya v1.1.65
- What: image `local-llm-runner-maya:v1.1.65-ra906` d71f3f70 = v1.1.65 c81fab6 + 0013 + 0014 (0014 regenerated;
  #906 still not upstream), built 11-16 via build-runner.sh (zstd), retagged `:latest`; DS4 restarted on 0663b08f.
- Why: latest release. For this box: #956 (v1.1.64) turns the PCIe expert lane off again on `--tp` unless it measures
  faster (cost ~4-5% decode since v1.1.58); v1.1.61 RDNA3 prompt path (+14-17% prefill measured on Halo APUs).
- Effect: health 1.1.65, 0 restarts, idle GPUs 0% busy / 8-15 W, all 12607 CPU experts + 202.8 GB Engram in RAM,
  0 GB SSD in bench. Warm pair.py 55.6 tok/s (code6k 58.4, pipeline 52.9, math 70.9, story 40.3) vs 58.5 on
  v1.1.58 - but that bench ran uncapped (333 W boot race, fixed 11-15), so not comparable. Prefill not re-measured.
- Rollback: `docker tag local-llm-runner-maya:before-v1.1.65-20261117 local-llm-runner-maya:latest`, then
  POST /api/clusters/0663b08f/start {"family":"maya-dsv41-q4xl-huihui","profile":"default"}.

### 2026-11-15 GPU power caps re-applied (boot race)
- What: `scripts/gpu-power-cap` retries each card up to 60 s until the cap reads back; unit gets
  `TimeoutStartSec=300`. Old `amdgpu-powercap.service` (raises every cap to 333 W) disabled. Caps now 253/238/253/238 W
  (04/09/a3/a6). Live backups `/usr/local/bin/gpu-power-cap.bak-20261115`, `gpu-power-cap.service.bak-20261115`.
- Why: both units ran at boot together; gpu-power-cap hit EBUSY on `power1_cap_min` and failed, the raise-to-max unit
  retried and won. Cards ran uncapped at 333 W since the 11-10 boot.
- Effect: caps hold; model not restarted. Not reboot-tested yet.
- Rollback: restore the .bak files, `systemctl enable --now amdgpu-powercap` for 333 W.

### 2026-11-11 Maya v1.1.58
- What: image `local-llm-runner-maya:v1.1.58-ra906` bffe1532 = v1.1.58 + 0013 + 0014 (0014 regenerated for context
  drift), retagged `:latest`; DS4 restarted on 0663b08f. 0012 (full GLM-5.3 + ML4) dropped: upstream's own glm-dsa
  port (v1.1.57) conflicts in 19 files. `container/build.sh` now builds runners through `scripts/build-runner.sh` (zstd).
- Why: latest release (loop guard #921, SIGTERM hang fix, think:false, Responses image detail #914, GLM-5.3 upstream).
- Effect: health 1.1.58, 0 restarts, idle GPU busy 0%. Warm pair.py 58.5 tok/s vs 65.5 on 11-07; v1.1.58's DS4 diff
  (per-request ablate, NVIDIA one-GPU path #920, stream tie rule #697) does not run here, so likely the rack move. Not A/B'd.
- Rollback: `docker tag local-llm-runner-maya:before-v1.1.58-20261111 local-llm-runner-maya:latest`, then
  POST /api/clusters/0663b08f/start {"family":"maya-dsv41-q4xl-huihui","profile":"default"}.

### 2026-11-10 Cluster PCI addresses after GPU rack move
- What: all 9 mgmt cluster defs (`~/.local/share/local_llm/runs/clusters/*.json` = mgmt `/state/runs/clusters`)
  rewritten `0000:05:00.0 -> 0000:04:00.0`, `0000:08:00.0 -> 0000:09:00.0` (a3/a6 unchanged). Backup
  `runs/clusters.bak-20261110-pci/`.
- Why: host moved and GPUs remounted in the rack; socket-0 cards re-enumerated. Start failed with "references GPUs
  not present in the inventory".
- Effect: maya-dsv41-q4xl-huihui back up on 0663b08f :8088, 0 restarts. HIP/rocm-smi order notes may be stale.
- Rollback: copy the backup files back (only valid if cards return to old slots).

### 2026-11-08 OpenCode prune off (cache misses)
- What: `compaction.prune: false` in Mac `~/.config/opencode/opencode.json`, ubt26
  `~/.config/local_llm/agents/opencode{,2}/opencode.json`, repo seeds `agents/opencode{,2}.json`;
  `scripts/model-switch.py sync` now enforces it. Backups `*.bak-20261108-pre-prune`.
- Why: prune clears old tool outputs in place, so the prompt stops continuing Maya's kept conversation and the
  whole history is read again. Seen 03:04: a 470,562-token turn read from 0 in 572 s (the turn before: 10 s). Proof:
  the 470,188 slot was not superseded by the next save, so its tokens were no longer a prefix.
- Effect: pending restart of the OpenCode instances (Mac `opencode serve`, `local-llm-opencode`, `-opencode2`).
  Chats fill faster without pruning, so compaction comes sooner.
- Rollback: restore the `.bak-20261108-pre-prune` files, restart the agents.

### 2026-11-08 Model router started again
- What: `docker start local-llm-router` (:3200).
- Why: it was stopped by hand at 2026-11-07 12:46 UTC, before the reboot. With `restart: unless-stopped`, an explicit stop
  keeps it down across reboots, so OpenCode (Mac, phone) and anything using `auto` could not reach a model.
- Effect: `/v1/models` 200; an `auto` prompt answers from maya-dsv41-q4xl-huihui.
- Note: the running router image predates commit b008a60 (`GET /v1` answer for base-URL probes); its log shows clients
  probing `/` and getting 404. Rebuild the router image to pick that up.

### 2026-11-07 Maya v1.1.56 + PR #906 (0014)
- What: added upstream PR #906 (its own commit 7dd91aa only) as patch 0014. Image `:v1.1.56-ra906` 1c46e0191843.
- Why: after a STOP, a kept shared start left in the model was taken for a conversation.
- Effect: STOP mid-answer, then follow-up and fresh requests correct. Warm 65.5 tok/s (noise vs 64.3).
- Rollback: `docker tag local-llm-runner-maya:before-906-20261107 local-llm-runner-maya:latest`, restart the cluster.
- Commit: 119de90.

### 2026-11-07 Maya v1.1.56 + CPU-lane read-ahead (0013)
- What: v1.1.55 -> v1.1.56 plus patch 0013. Profile adds `MAYA_DS4_AHEAD_RAM=1`, `MAYA_DS4_LANE_PF=2`.
- Why: the lane reads RAM at ~78 GB/s in bursts and idles 60% of the time. The engine's next-layer guesses were off
  for all-RAM layers; the top 2 guesses cover 64% of what the lane computes, so the lane reads them into cache while
  the GPUs run.
- Effect: warm decode 61.2-62.1 -> 64.3 tok/s (+3.5-5%). Lane compute 481 -> 371 us a call.
- Rollback: tag `before-v1.1.56-20261107` as latest, restore `profiles.json.bak-20261107-pre-ra`, restart.
- Commit: 4f91e1f. Analysis: `runner/maya/diagnostics/ds4-decode/README.md`.

### 2026-11-07 GPU fans: zero-rpm on
- What: `scripts/gpu-fan-floor` sets `fan_zero_rpm_enable=1` (`ZERO_RPM=1`). Live copy backup
  `/usr/local/bin/gpu-fan-floor.bak-20261107`.
- Why: the 35% floor kept the fans at ~1400-1550 rpm while the cards were cold.
- Effect: silent at idle. Target 85 C and min pwm 35 under load unchanged.
- Rollback: `ZERO_RPM=0` in the script; the timer re-applies it.
- Commit: 9860fd0.

### 2026-11-07 Docker image cleanup
- What: removed all strata runner images, Maya images v1.1.43-v1.1.53 and their old `before-*` tags, old GitLab CE
  versions (18.2.1-19.2.9), ROCm runner `new`/`prev`/`hostpin`/`vendored` tags, `rocm/dev-ubuntu-24.04:7.2`.
- Why: root disk at 97%.
- Effect: root 97% -> 72% (250 GB free). Kept every backend's `:latest`, `gitlab-ce:19.5.1`, ML4 images,
  `rocmunslothsrc:b12017` and `:adaptive`.
- Rollback: none (rebuild from the repo's runner Dockerfiles).

### 2026-11-06 RAM_SKIP_W 0.16 (lossy)
- What: `MAYA_DS4_RAM_SKIP_W=0.16`: a token skips CPU-lane experts with route weight under 16% of its total.
- Effect: decode 37.5 -> 56.0 tok/s (+49%), draft acceptance 82 -> 79%. Perplexity: code flat, prose +5-7% (small sample).
- Rollback: remove the key; backup `profiles.json.bak-20261106-pre-ramskip`. Try removing it first if answers look off.

### 2026-11-06 YOCO_TP
- What: `MAYA_DS4_YOCO_TP=1`: layers 20-39 skip all but the last ~2,700 tokens of long prompts on a TP group.
- Effect: prefill 32K 548 -> 834, 64K 521 -> 914 tok/s; decode unchanged; first-token KL within noise.
- Rollback: backup `profiles.json.bak-20261106-pre-yoco`.

### 2026-11-05 Maya v1.1.55
- What: image a2430cbf (v1.1.55 + 0012). Reason: DS4 GPU-fault recovery (#688). No decode change.
- Rollback tag: `before-v1.1.55-20261105`.

### 2026-11-04 DS4_TP_SHARES=off
- What: works around upstream #841: from v1.1.52 the cards sat at 100% busy, ~92 W each, while idle.
- Effect: idle 0% busy, 7-14 W a card.

### 2026-11-03 Maya v1.1.52 + tensor-parallel lending
- What: `MAYA_DS4_TP_BORROW=1`, `--prefill-chunk 16384` (needs `DS4_FLOW_TP=1`).
- Effect: prefill 461 -> 648 tok/s (+29-45%), 130K prompt 279-299 -> 211 s; decode +2-9%.
- Rollback: `/mnt/scratch/maya-v1.1.52/profile-before-tpb.json`.

### ~2026-10-30 UD-Q4_K_XL huihui across 4 cards
- What: family `maya-dsv41-q4xl-huihui`, `--tp 4`, `TP_GGUF_UNEVEN`, plus the engine's fuse/trim settings (see Live now).
- Effect: the current model and layout. (Date approximate.)

### 2026-10-27 NUMA binding (CAP_SYS_NICE + patch 0008 MPOL_LOCAL)
- What: runner containers get `CAP_SYS_NICE` so the expert copies really bind per socket; Maya patch 0008 takes the
  engine out of kernel NUMA balancing. (0008 later landed upstream.)
- Effect: lane call 1.55 -> 1.00 ms; full-quality decode 21.9 -> 30.5 tok/s.

### 2026-10-26 GPUs moved to the T7910
- What: 4x 7900 XT into the dual-Xeon 1 TB box; every CPU expert held in RAM (`DS4_REQUIRE_ALL_RAM=1`,
  `DS4_ENGRAM_RAM=1`, `--mmap-experts off`). Same day: huihui abliteration (official patch bytes).
- Effect: no disk reads in decode.

### 2026-10-22 DS4 first live
- What: DeepSeek-V4.1-Flash Maya-XS on the old box (60 GB RAM), image `v1.1.23-ds4`, `--tp 1`, DSpark on.
- Effect: decode 26-28 tok/s, 31-33 with DSpark. Starting point.

## Tried and rejected

Details in `runner/maya/diagnostics/ds4-decode/README.md`. Do not re-test without a new reason.
- Cross-socket P2P all-reduce: cross-socket transfers 0.25-0.29 GB/s, uncached P2P -37%.
- Hyperthreading off, the SMT lane, lane thread counts other than one per core, pinning the launch threads.
- PR 784 (Engram NUMA balance), PR 821 (expert cache substitution: 55.5 vs 61-62).
- Segment graphs and whole-layer graphs: launch cost is not on the critical path (+3 us a launch changed nothing).
- HIP runtime settings (`AMD_DIRECT_DISPATCH`, `GPU_MAX_HW_QUEUES`, `HIP_FORCE_DEV_KERNARG`).
- Wider read-ahead (`LANE_PF=3`): flat.

## Template

```
### YYYY-MM-DD Short title
- What: the change, where it lives (image tag, profile key, file).
- Why:
- Effect: measured before -> after, and how measured.
- Rollback: backup file or tag, and the command.
- Commit:
```
