# Live changes on ubt26

What runs on the GPU host, and every change made to it. Add an entry for each change to a live service, image,
profile, host setting or fan/power setting, newest first. Use the template at the bottom. The "Live now" section
always describes the current state, so update it in the same commit.

Speed figures are the bench of their day (old box, the 8-prompt set, then `pair.py` warm rounds). Read each entry's
before -> after as that change's gain. The figures do not chain into one number.

## Live now

**Model:** `maya-dsv41-q4xl-huihui` (DeepSeek-V4.1-Flash UD-Q4_K_XL, huihui abliteration) on cluster `0663b08f`, port
8088, 4x RX 7900 XT, Dell T7910 (2x E5-2699 v4, 1 TB RAM).

**Image:** `local-llm-runner-maya:latest` = `:v1.1.56-ra906` (`1c46e0191843`): Maya v1.1.56 (22fc101) + patches in
`runner/maya/patches`:
- 0012: full GLM-5.3 and Mistral Large 4 on the GLM engine.
- 0013: DS4 CPU-lane read-ahead (engine branch `ds4-decode-graph` a08d45e on Cass67/project-maya).
- 0014: upstream PR #906, keeps the kept shared start after a STOP. Drop once #906 is in a release.

**Args:** `--pack /mnt/models/unsloth-dsv41/UD-Q4_K_XL/maya-ds4 --tp 4 --reserve-mib 512 --vision on --dspark on
--mmap-experts off --experts 6 --prefill-chunk 16384`

**Env** (profile `default`, live state `~/.local/share/local_llm/profiles.json` on ubt26):

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

**Host:** runner containers get `CAP_SYS_NICE` (`container/backend/runtime.py`). GPU fans: `scripts/gpu-fan-floor`
(target 85 C, min pwm 35, zero-rpm on), re-applied every 10 min by `gpu-fan-floor.timer`.

**Speed now:** warm decode 65.5 tok/s (`pair.py`, temp 0, 1024 tokens). Prefill ~650 tok/s at 32K, ~900 at 64K.

**Rollback tags:** `before-906-20261107` (read-ahead without 0014), `before-v1.1.56-20261107` (v1.1.55).

## Log

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
