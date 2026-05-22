# local_llm

Local OpenCode profiles backed by `llama.cpp` on the ROCm box.

This repo keeps the client wrapper and remote launch scripts in sync. The Mac runs OpenCode. `ubt26` / `cass.lan` runs `llama-server` on the RX 7900 XT.

## Quick Start

Use Qwen3.6 for general local OpenCode work:

```bash
oc-qwen-reliable --lean
```

Use Qwen Coder when code-specialized behavior matters:

```bash
oc-qwen-coder-reliable --lean
```

Use Gemma text-only for comparison:

```bash
oc-gemma-reliable --lean
```

Use Gemma vision when image input matters:

```bash
oc-gemma-vision-reliable --lean
```

Remote usage (SSH):

- By default, `--remote` means: SSH to the given host and run llama-server there.
- Use `--user` to set the SSH username.
- Use `-k` to allow password prompt when key auth is not configured.

```bash
oc-local qwen reliable --remote 192.166.2.1 --user cass -k
```

Inspect exact settings without starting anything:

```bash
oc-qwen-coder-reliable --lean --info
oc-gemma-vision-reliable --lean --info
```

## Helper Tools

These scripts are installed locally by the manual install commands below. They inspect or maintain this wrapper setup; they do not replace live `llama-server` benchmarking.

### Hardware Analyzer

hardware-analyzer reports the machine it runs on. On the Mac, it reports Mac CPU/RAM and usually cannot see the remote RX 7900 XT. To inspect the ROCm server, run it on `ubt26` or use ROCm tools there.

```bash
# Local client hardware summary
hardware-analyzer

# Remote model-server hardware summary
hardware-analyzer --remote ubt26

# Remote GPU view for the actual model server
ssh ubt26 'rocminfo | grep -E "Name:|Marketing Name" | head -20'
ssh ubt26 'rocm-smi --showmeminfo vram --showuse'
```

Use this when deciding whether a model candidate is worth testing before pulling a large GGUF. Treat the output as a starting point; final fit still comes from `llama-server` logs and `oc-*-* --info`.

### Model Discovery

`model-discovery` queries Hugging Face live for GGUF candidates by default, detects the target model-server hardware, and prints already tuned local_llm profiles separately. Use the Hugging Face list as a starting point; final fit still comes from `llama-server` logs and `oc-*-* --info`.

Default results are ranked for the RX 7900 XT: 14B-40B candidates first, unusual sizes next, tiny 1B-9B models demoted as small/test, and 70B+ models demoted as unlikely.

```bash
# Search Hugging Face and show tuned profiles
model-discovery

# Search for a specific model family
model-discovery --query "qwen coder gguf" --limit 10

# Show only profiles already tuned in this repo
model-discovery --installed-only

# Force local-client hardware instead of the remote model host
model-discovery --local

# More detailed tuned-profile output
model-discovery --detailed
```

After discovery suggests a model, verify the actual wrapper profile before running it:

```bash
oc-qwen-coder-reliable --lean --info
oc-gpt-oss-speed --lean --info
oc-qwen-27b-long --lean --info
```

### Model Manager

`model-manager` is the planned workflow helper for model discovery, selection, benchmarking, and acceptance.

```bash
# Discover remote GGUF candidates
model-manager discover --target remote:ubt26 --query "qwen coder gguf"

# Show current model-manager state
model-manager status
```

### Update Manager

update-manager is a compatibility helper. It does not mutate files; use `model-manager` for model workflow lifecycle commands.

```bash
# Show model-manager workflow guidance
update-manager

# Compatibility alias for older local helper workflows
update-manager --config

# Compatibility alias for older model update workflows
update-manager --models

# Inspect model workflow state
model-manager status

# Discover remote GGUF candidates
model-manager discover --target remote:ubt26 --query "qwen coder gguf"

# Inspect a benchmark plan before running lifecycle work
model-manager benchmark --repo <repo> --family <family> --alias <alias> --target remote:ubt26 --dry-run
```

Use the explicit install commands below when you change `scripts/oc-local` or any `scripts/start*.sh` launcher.

## Server Service

`ubt26` runs `llama-server` through a user systemd service. The service has a stable `ExecStart` that calls `run-current-model.sh`; `oc-local` updates `current-model.env` and then runs:

```bash
systemctl --user restart llama-server.service
```

The current model selection is mutable and stored on the server in `current-model.env`. For example, the restored Qwen vision service uses:

```bash
REMOTE_SCRIPT=./start11.sh
REMOTE_PROFILE=reliable
```

This avoids rewriting unit files and avoids fighting a root-owned `Restart=always` process.

## Web Switcher

The public Open WebUI path is fronted by `local-llm-switcher` on `ubt26`:

- Open WebUI listens on http://127.0.0.1:3002.
- local-llm-switcher listens on http://127.0.0.1:3001.
- Cloudflare stays pointed at port 3001, so the public tunnel does not need to change.
- The switcher proxies normal Open WebUI traffic to `127.0.0.1:3002` and injects a compact model selector.

Switcher endpoints:

| Endpoint | Purpose |
| --- | --- |
| `GET /api/local-llm/models` | List allowed launcher/profile choices. |
| `GET /api/local-llm/current` | Show the selected `current-model.env` entry and live llama.cpp model aliases. |
| `POST /api/local-llm/switch` | Write `current-model.env`, restart `llama-server.service`, and wait for the requested alias. |
| `GET /_switcher` | Fallback page using the same APIs when the injected Open WebUI widget is unavailable. |

Inspect or restart the remote services:

```bash
ssh ubt26 'systemctl --user status local-llm-switcher.service llama-server.service'
ssh ubt26 'journalctl --user -u local-llm-switcher.service -n 160 --no-pager'
ssh ubt26 'journalctl --user -u llama-server.service -n 160 --no-pager'
ssh ubt26 'docker ps --filter name=open-webui'
ssh ubt26 'docker logs --tail 120 open-webui'
ssh ubt26 'docker restart open-webui'
ssh ubt26 'systemctl --user restart local-llm-switcher.service llama-server.service'
```

Probe the switcher, fallback page, and proxied Open WebUI directly on `ubt26`:

```bash
ssh ubt26 'curl -fsS http://127.0.0.1:3001/api/local-llm/current; curl -fsS http://127.0.0.1:3001/_switcher >/dev/null; curl -fsS http://127.0.0.1:3001/ >/dev/null; curl -fsS http://127.0.0.1:3002/ >/dev/null'
```

Rollback if the proxy fails:

```bash
ssh ubt26 'systemctl --user disable --now local-llm-switcher.service'
ssh ubt26 'docker rm -f open-webui && docker run -d --name open-webui --restart unless-stopped --network host -e PORT=3001 -v open-webui:/app/backend/data ghcr.io/open-webui/open-webui:main'
```

## What This Does

`scripts/oc-local`:

- Resolves model family and profile from command name or arguments.
- Starts the matching `llama-server` profile locally or over SSH.
- Waits for the OpenAI-compatible API to become reachable.
- Generates `OPENCODE_CONFIG_CONTENT` with matching context limits.
- Launches OpenCode with the resolved local model id.

llama.cpp launchers:

- `scripts/start2.sh`: Qwen3-Coder 30B A3B Instruct.
- `scripts/start3.sh`: Qwen3.6 35B A3B, vision-enabled with `--mmproj-auto`.
- `scripts/start4.sh`: Gemma 4 31B text-only.
- `scripts/start5.sh`: Gemma 4 31B vision.
- `scripts/start6.sh`: gpt-oss 20B.
- `scripts/start7.sh`: DeepSeek R1 Distill Qwen 32B.
- `scripts/start8.sh`: Qwen3.6 27B dense.
- `scripts/start9.sh`: Qwen3.5 27B Opus reasoning distill benchmark candidate.
- `scripts/start10.sh`: DavidAU Qwen3.6 27B Heretic uncensored code finetune candidate.
- `scripts/start11.sh`: Hauhau Qwen3.6 35B A3B uncensored candidate, vision-enabled with `--mmproj-auto`.

## Command Shape

Symlink style:

```bash
oc-<family>-<profile> --lean
```

Explicit style:

```bash
oc-local <family> <profile> --lean
```

Remote style (SSH):

```bash
oc-local qwen-heretic reliable --remote 192.166.2.1 --user cass -k
```

`--remote` SSH-targets the model server. Use `--user` to specify the SSH username and `-k` to allow password prompt when key auth is not configured.

Families:

| Family | Purpose | Model id |
| --- | --- | --- |
| `qwen` | Default coding/chat profile with vision projector enabled | `localllm/qwen3.6-35b-a3b-mtp` |
| `qwen-hauhau` | Hauhau Qwen3.6 35B vision-enabled candidate | `localllm/qwen3.6-35b-a3b-hauhau` |
| `qwen-27b` | Qwen3.6 27B dense-thinking comparison; not the responsive daily driver | `localllm/qwen3.6-27b` |
| `qwen-coder` | Code-specialized Qwen Coder | `localllm/qwen3-coder-30b-a3b-instruct` |
| `gemma` | Gemma text-only | `localllm/gemma-4-31b-it` |
| `gemma-vision` | Gemma with vision projector | `localllm/gemma-4-31b-it-vision` |
| `gpt-oss` | OpenAI gpt-oss 20B reasoning model | `localllm/gpt-oss-20b` |
| `deepseek-r1` | DeepSeek R1 Distill Qwen 32B reasoning model | `localllm/deepseek-r1-distill-qwen-32b` |
| `qwen-opus` | Qwen3.5 27B Opus reasoning distill; benchmark candidate, not yet promoted | `localllm/qwen3.5-27b-opus-reasoning` |
| `qwen-heretic` | DavidAU Qwen3.6 27B Heretic uncensored code finetune candidate | `localllm/qwen3.6-27b-heretic-code` |

Profiles:

| Profile | Intent |
| --- | --- |
| `speed` | Smallest practical context for fast startup/use. |
| `fastlong` | Medium context for normal larger tasks. |
| `balanced` | Larger context with more conservative batches. |
| `reliable` | Long-session profile; preferred default for serious work. |
| `tiny` | Lower-quant fallback when VRAM is tight. |

Options:

| Option | Effect |
| --- | --- |
| `--lean` | Removes OpenCode plugins from generated config to reduce prompt overhead. |
| `--dry-run` | Prints machine-readable-ish wrapper actions and generated config. |
| `--info` | Prints full resolved model/server/OpenCode settings and exits. No SSH. No server start. |
| `--remote <host>` | SSH to the given host and run llama-server there instead of locally. |
| `-s <id>`, `--session <id>` | Restarts the selected model on the chosen target, then resumes the OpenCode session with that id. |

Resume an existing OpenCode session on a different local model:

```bash
oc-gpt-oss-speed --lean -s ses_abc123
oc-qwen-coder-reliable --lean --session ses_abc123
```

## Recommended Choices

Qwen 35B defaults are vision-enabled. The default `qwen` family and the `qwen-hauhau` candidate load their multimodal projector with `--mmproj-auto`; use `--info` to inspect the resolved `mmproj=enabled` setting before starting a long session.

Quant, KV Q4/Q5, and MMQ changes remain future benchmark/promotion work. The 2026-05-22 Qwen vision quant benchmark did not justify adding q8 KV launcher flags, changing quant files, or enabling `GGML_HIP_FORCE_MMQ` by default.

| Goal | Command | Why |
| --- | --- | --- |
| Best default local OpenCode | `oc-qwen-reliable --lean` | Fast decode, stable behavior, long context, and vision projector enabled. |
| Qwen dense-thinking comparison | `oc-qwen-27b-reliable --lean` | Dense 27B thinking model; not the responsive daily driver. |
| Qwen dense fastest profile | `oc-qwen-27b-speed --lean` | IQ4, 49k context; fastest stable 27B profile, but still about 30 tok/s decode. |
| Qwen dense reliable | `oc-qwen-27b-reliable --lean` | IQ4, 65k context; more room, but slower prompt eval. |
| Qwen dense long context | `oc-qwen-27b-long --lean` | Q3 96k context; 100k loaded but crashed on generation, 128k OOMed. |
| Code-specialized model | `oc-qwen-coder-reliable --lean` | Full GPU offload at 65k after Q3 profile tuning. |
| Fast Coder test | `oc-qwen-coder-fastlong --lean` | Coder model with smaller 40k context. |
| Gemma text comparison | `oc-gemma-reliable --lean` | Text-only, disables vision projector for VRAM headroom. |
| Gemma vision | `oc-gemma-vision-reliable --lean` | Loads mmproj and uses smaller context/batch. |
| gpt-oss 131k reasoning | `oc-gpt-oss-speed --lean` | Full 131k context, Q8 quant, and high reasoning with the largest tested batch on RX 7900 XT. |
| DeepSeek small-context reasoning | `oc-deepseek-r1-reliable --lean` | Q3 32B reasoning model; fully offloads at 16k but uses almost all VRAM. |
| Benchmark Qwen Opus reasoning | `oc-qwen-opus-reliable --lean` | Candidate from model-discovery; verify fit/perf before trusting. |
| Qwen Heretic quality | `oc-qwen-heretic-reliable --lean` | Q4_K_M, 65k context; best quality profile that completed. |
| Qwen Heretic fastest | `oc-qwen-heretic-speed --lean` | IQ4_XS, 65k context; fastest measured 65k Heretic profile. |
| Qwen Heretic long | `oc-qwen-heretic-fastlong --lean` | IQ3_M, 96k context; benchmark-backed long-context profile. |
| Qwen Heretic 128k stretch | `oc-qwen-heretic-tiny --lean` | IQ2_M, 131k context; only tested profile that reached 128k. |
| Check exact launch settings | `oc-qwen-coder-reliable --lean --info` | Shows quant, context, batch, offload, command, config. |

## Install

Client-side install on the machine running OpenCode:

```bash
# Install using the enhanced installer
./installer.sh

# Or manually install the enhanced components:
install -m 0755 scripts/oc-local ~/.local/bin/oc-local

for profile in speed fastlong balanced reliable tiny; do
  ln -sf ~/.local/bin/oc-local ~/.local/bin/oc-${profile}
done

for family in qwen qwen-27b qwen-coder gemma gemma-vision gpt-oss deepseek-r1 qwen-opus qwen-heretic; do
  for profile in speed fastlong balanced reliable tiny; do
    ln -sf ~/.local/bin/oc-local ~/.local/bin/oc-${family}-${profile}
  done
done

for profile in speed fastlong balanced reliable tiny; do
  ln -sf ~/.local/bin/oc-local ~/.local/bin/oc-coder-${profile}
done

ln -sf ~/.local/bin/oc-local ~/.local/bin/oc-qwen-coder
ln -sf ~/.local/bin/oc-local ~/.local/bin/oc-qwen-27b-long
ln -sf ~/.local/bin/oc-local ~/.local/bin/oc-qwen-27b-96k
ln -sf ~/.local/bin/oc-local ~/.local/bin/oc-qwen36-27b-long
ln -sf ~/.local/bin/oc-local ~/.local/bin/oc-qwen36-27b-96k
ln -sf ~/.local/bin/oc-local ~/.local/bin/oc-coder
ln -sf ~/.local/bin/oc-local ~/.local/bin/oc-code

# Install enhanced components
install -m 0755 scripts/hardware-analyzer.sh ~/.local/bin/hardware-analyzer
install -m 0755 scripts/model-discovery.sh ~/.local/bin/model-discovery
install -m 0755 scripts/model-manager.sh ~/.local/bin/model-manager
install -m 0755 scripts/update-manager.sh ~/.local/bin/update-manager
```

Server-side install on `ubt26`:

```bash
scp scripts/start2.sh ubt26:/home/cass/llama.cpp/start2.sh
scp scripts/start3.sh ubt26:/home/cass/llama.cpp/start3.sh
scp scripts/start4.sh ubt26:/home/cass/llama.cpp/start4.sh
scp scripts/start5.sh ubt26:/home/cass/llama.cpp/start5.sh
scp scripts/start6.sh ubt26:/home/cass/llama.cpp/start6.sh
scp scripts/start7.sh ubt26:/home/cass/llama.cpp/start7.sh
scp scripts/start8.sh ubt26:/home/cass/llama.cpp/start8.sh
scp scripts/start9.sh ubt26:/home/cass/llama.cpp/start9.sh
scp scripts/start10.sh ubt26:/home/cass/llama.cpp/start10.sh
scp scripts/start11.sh ubt26:/home/cass/llama.cpp/start11.sh
scp scripts/start12.sh ubt26:/home/cass/llama.cpp/start12.sh
scp scripts/start14.sh ubt26:/home/cass/llama.cpp/start14.sh
scp scripts/run-current-model.sh ubt26:/home/cass/llama.cpp/run-current-model.sh
scp scripts/local-llm-switcher.py ubt26:/home/cass/llama.cpp/local-llm-switcher.py
scp scripts/local-llm-switcher.service ubt26:/home/cass/.config/systemd/user/local-llm-switcher.service

ssh ubt26 'chmod +x /home/cass/llama.cpp/start2.sh /home/cass/llama.cpp/start3.sh /home/cass/llama.cpp/start4.sh /home/cass/llama.cpp/start5.sh /home/cass/llama.cpp/start6.sh /home/cass/llama.cpp/start7.sh /home/cass/llama.cpp/start8.sh /home/cass/llama.cpp/start9.sh /home/cass/llama.cpp/start10.sh /home/cass/llama.cpp/start11.sh /home/cass/llama.cpp/start12.sh /home/cass/llama.cpp/start14.sh /home/cass/llama.cpp/run-current-model.sh'
ssh ubt26 'systemctl --user daemon-reload && systemctl --user enable --now local-llm-switcher.service'
```

## Environment Overrides

| Variable | Default | Purpose |
| --- | --- | --- |
| `OC_LOCAL_REMOTE_HOST` | `ubt26` | SSH target for model server. |
| `OC_LOCAL_REMOTE_DIR` | `/home/cass/llama.cpp` | Remote llama.cpp directory. |
| `OC_LOCAL_BASE_URL` | `http://cass.lan:8080/v1` | OpenAI-compatible llama.cpp API URL from client machine. |
| `OC_LOCAL_API_KEY` | `sk-dummy` | Dummy key for OpenAI-compatible provider. |
| `OC_LOCAL_MODEL` | family-specific | OpenCode model id override. |
| `OC_LOCAL_OUTPUT_LIMIT` | `4096` | OpenCode output token limit. |
| `OC_LOCAL_RESERVED` | `4096` | OpenCode compaction reserve. |
| `OC_LOCAL_WAIT_SECONDS` | `180` | Startup readiness timeout. |

## Operations

Show exactly what will run:

```bash
oc-qwen-reliable --lean --info
oc-qwen-27b-reliable --lean --info
oc-qwen-coder-reliable --lean --info
oc-gemma-reliable --lean --info
oc-gemma-vision-reliable --lean --info
oc-gpt-oss-reliable --lean --info
```

Run without OpenCode to inspect the server directly:

```bash
ssh ubt26 'cd /home/cass/llama.cpp && ./start3.sh reliable'
```

Inspect remote logs:

```bash
ssh ubt26 'journalctl --user -u llama-server.service -n 160 --no-pager'
ssh ubt26 'journalctl --user -u llama-server.service -n 300 --no-pager | grep -E "offloaded|KV buffer|eval time|prompt eval|mmproj"'
```

Check active server:

```bash
curl -fsS http://cass.lan:8080/v1/models
```

Run a tiny API probe:

```bash
curl -fsS http://cass.lan:8080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  --data '{"model":"qwen3.6-35b-a3b-hauhau","messages":[{"role":"user","content":"Reply with exactly: ok"}],"max_tokens":8,"temperature":0}'
```

## Verification

```bash
python3 -m py_compile scripts/local-llm-switcher.py
for script in scripts/oc-local scripts/model-manager.sh scripts/update-manager.sh scripts/model-discovery.sh scripts/hardware-analyzer.sh scripts/bench-mtp-remote.sh installer.sh scripts/start3.sh scripts/start8.sh scripts/start9.sh scripts/start10.sh scripts/start11.sh scripts/start12.sh scripts/start14.sh scripts/run-current-model.sh scripts/bench-installed-kv-remote.sh test_oc_local.sh; do bash -n "$script" || exit 1; done
./test_oc_local.sh
shellcheck scripts/oc-local scripts/bench-mtp-remote.sh installer.sh scripts/start3.sh scripts/start8.sh scripts/start9.sh scripts/start10.sh scripts/start11.sh scripts/start12.sh scripts/start14.sh scripts/run-current-model.sh scripts/bench-installed-kv-remote.sh test_oc_local.sh
ssh ubt26 'systemctl --user is-active local-llm-switcher.service llama-server.service; curl -fsS http://127.0.0.1:3001/api/local-llm/current; curl -fsS http://127.0.0.1:3001/ >/dev/null; curl -fsS http://127.0.0.1:3002/ >/dev/null'
oc-qwen-coder-reliable --lean --info
oc-gemma-vision-reliable --lean --info
oc-gpt-oss-reliable --lean --info
```

## Troubleshooting

### Slow Decode

Check for CPU-offloaded layers or CPU KV:

```bash
ssh ubt26 'journalctl --user -u llama-server.service -n 300 --no-pager | grep -E "offloaded|CPU KV|KV buffer|eval time"'
```

If decode drops hard, prefer a profile with full GPU offload over a higher quant. For Coder, `UD-Q3_K_XL` reliable is faster than old `IQ4_XS` reliable because it keeps all layers on GPU.

### OOM At Startup

Use `--info` to see quant/context/batch:

```bash
oc-gemma-reliable --lean --info
```

Then choose a smaller profile:

```bash
oc-gemma-balanced --lean
oc-gemma-tiny --lean
```

### Gemma Vision OOM

Vision loads mmproj and costs extra VRAM. Use the `gemma-vision` profiles for image tasks, and keep normal Gemma text on `gemma` because it passes `--no-mmproj`.

### Model Mismatch

Use `--info` and compare `model=`, `alias=`, and `/v1/models`:

```bash
oc-qwen-coder-reliable --lean --info
curl -fsS http://cass.lan:8080/v1/models
```

### Remote API Not Reachable

Check SSH and local URL separately:

```bash
ssh ubt26 'curl -fsS http://127.0.0.1:8080/v1/models'
curl -fsS http://cass.lan:8080/v1/models
```

### OpenCode Tool Calls

`tool_call` is disabled on purpose. If testing local tool calls, verify the model emits real OpenAI tool-call objects, not raw `<function=...>` text.
