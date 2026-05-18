# Add Discovered Model — Jackrong Qwen3.5-27B Opus Reasoning Distill

**DO NOT create a new plan for adding a discovered model. Follow this plan exactly for ALL discovered model additions. The two-phase approach (benchmark first, create permanent scripts only if results are good) is the standard pattern.**

## How to Use

This is both a completed record AND a template. Steps are in checklist format. For a new model:
1. Before editing any files, fill in the metadata block at the top of this file
2. Check off steps as you go
3. When done, this file documents exactly what was done

## Completed Record: Jackrong Qwen3.5-27B Opus Reasoning Distill

### Model Metadata

```
FAMILY=qwen-opus
COMMAND_PREFIX=oc-qwen-opus
MODEL_ALIAS=qwen3.5-27b-opus-reasoning
OPENCODE_MODEL_ID=localllm/qwen3.5-27b-opus-reasoning
HF_REPO=Jackrong/Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled-GGUF
START_SCRIPT=scripts/start9.sh           # next unused number after highest start*.sh
REMOTE_SCRIPT=./start9.sh
PURPOSE=reasoning
BASE_PROFILE_SOURCE=qwen-27b             # closest existing family (27B dense)
```

### Rules (do not violate)

- Add as benchmark-first unless user explicitly says proven stable
- Do not replace existing defaults
- Do not claim fit/performance until verified from llama-server logs and a prompt/decode probe
- Use closest existing tuned profile as starting point
- Keep tool_call=false; do not enable local tool calling
- Use real aliases, not fake OpenAI model names
- Keep changes small and shellcheck-clean
- For reasoning models: set output_limit=16384, do NOT add --reasoning off

### Key Differences From Base Profile

This repo uses a non-standard GGUF filename scheme (no IQ4_XS/UD-Q3_K_XL presets). Available files:

```
Qwen3.5-27B.Q2_K.gguf
Qwen3.5-27B.Q3_K_M.gguf
Qwen3.5-27B.Q3_K_S.gguf
Qwen3.5-27B.Q4_K_M.gguf
Qwen3.5-27B.Q4_K_S.gguf
Qwen3.5-27B.Q8_0.gguf
mmproj-BF16.gguf
```

The `-hf repo:quant` preset syntax does not work for this repo. Must use `-hf REPO --hf-file FILENAME` instead. This affects both the remote launcher and the oc-local info command display.

**Quant mapping (27B model, 20 GiB VRAM):**
- `speed/fastlong/balanced` → `Qwen3.5-27B.Q4_K_S.gguf` (~13.5 GB, fits at 49K ctx)
- `reliable` → `Qwen3.5-27B.Q3_K_M.gguf` (~11 GB, fits at 65K ctx)
- `tiny` → `Qwen3.5-27B.Q3_K_S.gguf` (~9.5 GB, fits at 98K ctx)

---

## Phase 1: Benchmark

- [x] **Create standalone benchmark launcher** `scripts/bench-qwen-opus.sh` (not integrated into oc-local yet)
- [x] **Deploy to ubt26** — `scp` and `chmod +x`
- [x] **Download model** — first `llama-server` run downloads the GGUF via HF cache
- [x] **Test each profile** — start server, check offload stats, probe prompt/decode speed, stop server

Download pattern (model not cached initially):
```bash
ssh ubt26 'cd /home/cass/llama.cpp && nohup ./build/bin/llama-server \
  -hf "Jackrong/Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled-GGUF" \
  --hf-file "Qwen3.5-27B.Q4_K_S.gguf" \
  --no-mmproj --host 0.0.0.0 --port 8080 -ngl 999 -c 49152 \
  --flash-attn on -ub 128 -b 128 --threads "$(nproc)" --prio 2 \
  --no-warmup --temp 0.6 --top-p 0.95 --top-k 20 --min-p 0.0 \
  --presence-penalty 0.0 --alias qwen3.5-27b-opus-reasoning \
  &>/tmp/bench-speed.log &'
# wait ~2-5 min for download (13 GB Q4_K_S, 11 GB Q3_K_M, 9.5 GB Q3_K_S)
# check progress: du -sh ~/.cache/huggingface/hub/models--Jackrong--*/
# check ready: curl -s http://localhost:8080/v1/models
```

- [x] **Record benchmark results**

### Benchmark Results

| Profile | Quant File | Ctx | Batch/ubatch | Model VRAM | KV VRAM | Total VRAM% | Prompt tok/s | Decode tok/s |
|---|---|---|---|---|---|---|---|---|
| speed | Q4_K_S | 49K | 128/128 | 14155 MiB | 3072 MiB | 85% | 112.2 | 24.7 |
| fastlong | Q4_K_S | 49K | 128/128 | same as speed | | | | |
| balanced | Q4_K_S | 49K | 64/64 | same as speed | | | | |
| reliable | Q3_K_M | 65K | 64/64 | 12143 MiB | 4096 MiB | 80% | 117.5 | 27.6 |
| tiny | Q3_K_S | 98K | 64/64 | 10983 MiB | 6144 MiB | 84% | 94.4 | 28.5 |

All profiles: full 65/65 layers offloaded, no OOM, no errors.
Reasoning model: produces `reasoning_content` in responses → `output_limit=16384` needed.

---

## Phase 2: Create Permanent Scripts

Proceed only if benchmark is good (all criteria met for this model).

- [x] **Create** `scripts/start9.sh` — launcher with `--hf-file` approach, same profile values as benchmark
- [x] **Deploy** to ubt26
- [x] **Add qwen-opus family to** `scripts/oc-local`:
  - Usage line: `qwen-opus` in family list
  - Symlink dispatch: `oc-qwen-opus-speed`, `oc-qwen-opus-fastlong`, `oc-qwen-opus-balanced`, `oc-qwen-opus-reliable`, `oc-qwen-opus-tiny`
  - Positional parser: add `qwen-opus`
  - Config block: same params as benchmark, `remote_script=./start9.sh`, `mmproj_mode=disabled`
  - Output limit: add `qwen-opus` to reasoning families (output_limit=16384)
  - Reasoning off: add `qwen-opus` to exceptions (do NOT add `--reasoning off`)
  - Command format: override for `qwen-opus` family to use `--hf-file` instead of `:quant`
- [x] **Update** `installer.sh` — add `qwen-opus` to family loop
- [x] **Update** `README.md`:
  - Remote launchers: add `scripts/start9.sh` row
  - Families table: add `qwen-opus` row with "benchmark candidate, not yet promoted"
  - Recommended choices: add benchmark-only row
  - Server install: add `start9.sh` to scp/chmod commands
  - Verification: add `start9.sh` to bash -n and shellcheck commands
- [x] **Add tests** in `test_oc_local.sh`:
  - Assert start9.sh contains correct HF repo and alias
  - Assert dry-run output for qwen-opus reliable (family, profile, context, remote_start, model)
  - Assert info output for qwen-opus reliable (family, remote_start, hf_repo, quant, ctx, batch, ubatch, ngl, output_limit, alias, command with --hf-file, --no-mmproj, no --reasoning off)
- [x] **Verify** locally:
  - `bash -n` all changed files
  - `shellcheck` all changed files
  - `./test_oc_local.sh` passes ("oc-local dry-run tests passed")
  - `oc-qwen-opus-reliable --lean --info` shows correct values
- [x] **Install symlinks** for `oc-qwen-opus-{speed,fastlong,balanced,reliable,tiny}`
- [x] **Install updated oc-local** to `~/.local/bin/oc-local`

### Files Changed

| File | Change |
|---|---|
| `scripts/start9.sh` | Created |
| `scripts/oc-local` | Added qwen-opus family block, dispatch, parser, command override, reasoning exclusion |
| `installer.sh` | Added qwen-opus to family loop |
| `test_oc_local.sh` | Added start9 contents, dry-run, and info assertions |
| `README.md` | Added launcher row, family row, benchmark row, server install, verification |

### Cleanup

- [ ] (optional) Remove `scripts/bench-qwen-opus.sh` and remote `bench-qwen-opus.sh` — no longer needed now that `start9.sh` exists

---

## Template: For a New Model

To use this plan for a new discovered model:

1. Fill in the metadata block at the top of this file with the new model's values
2. Replace `Jackrong/...GGUF` repo ID everywhere
3. Check what GGUF filenames are available in the repo (run `llama-server -hf REPO` and check the "Available GGUF files" output)
4. Map profile quants to actual filenames if the repo lacks IQ4_XS/UD-Q3_K_XL presets
5. If the repo uses standard presets, use `-hf "REPO:${quant}"` syntax instead of `--hf-file`
6. If the repo has presets, revert the oc-local command override to the standard `-hf ${hf_repo}:${quant}` format
7. Choose the NEXT available start script number (check `scripts/start*.sh` for the highest)
8. Work through Phase 1 (benchmark), then Phase 2 (create permanent scripts) if results justify it

### Common Pitfalls

- **Repo has no GGUF presets**: The `-hf REPO:quant` syntax fails with "no GGUF files found". Use `--hf-file` instead.
- **Repo has standard presets**: Use `-hf REPO:quant` like `start8.sh`. Only use `--hf-file` when the repo uses non-standard filenames.
- **Reasoning model**: Always set `output_limit=16384` and exclude from `--reasoning off`.
- **Vision model**: Set `mmproj_mode=enabled` and do NOT add `--no-mmproj`.
- **First llama-server run**: Will download the GGUF via HF cache. May take 2-10 minutes depending on file size. Check `~/.cache/huggingface/hub/models--REPO--NAME/blobs/*.downloadInProgress` for progress.
