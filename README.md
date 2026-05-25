# local_llm

`local_llm` is a bootstrap engine for building your own local GGUF model workflow. A fresh pull contains the installer, discovery, benchmark, acceptance, export/restore, OpenCode wrapper, and support files for planned Open WebUI switcher workflows; it does not define a public default model collection.

The normal setup is split across two machines. Replace the example hostnames with your own:

- The client machine runs OpenCode and the `oc-local` wrapper.
- A GPU host runs `llama-server`, generated launchers, Open WebUI, Caddy, and the local switcher.
- Cloudflare Access can protect the public Open WebUI hostname while local services stay bound to private interfaces.

![local_llm architecture](docs/assets/local-llm-architecture.svg)

## Fresh pull workflow

Run this from a new checkout on the client machine:

```bash
./install.sh
model-manager bootstrap --target remote:<host> --dry-run
model-manager bootstrap --target remote:<host> --yes
model-manager discover "coding gguf" --target remote:<host>
model-manager benchmark <source> --target remote:<host> --full
model-manager accept <benchmark.json>
model-manager deploy --target remote:<host> --dry-run
model-manager export > local-llm-backup.json
```

Use placeholders literally as placeholders: replace `<host>`, `<source>`, and `<benchmark.json>` with your server and benchmark result. `accept` stores accepted metadata and generated launchers under your local state directory, not as committed repo defaults.

## Features

- Fresh-pull bootstrap for local/remote targets.
- Hardware-aware GGUF discovery and readable inventory.
- Full benchmark flow before accepting a model.
- Generated launcher state under `$HOME/.local/share/local_llm` / `runs`.
- Export/restore for moving accepted model state between machines.
- OpenCode wrapper support through `oc-local <family> <profile> --info` and `--remote`.
- User-systemd `llama-server.service` support through `run-current-model.sh`.
- Planned Open WebUI switcher API and injected bottom-right `LLM` pill support.
- Caddy routing for Open WebUI, WebSockets, switcher APIs, and HTML injection.
- Guardrails for shell syntax, shellcheck, and smoke tests.

Use this repo when you want an operator workflow for finding, benchmarking, accepting, backing up, and restoring models that are specific to your hardware.

## Test A Fresh Checkout

Run the smoke test first:

```bash
./test_oc_local.sh
```

Test install and empty-state behavior without touching your real state:

```bash
tmp="$(mktemp -d)"
LOCAL_LLM_BIN_DIR="$tmp/bin" LOCAL_LLM_SHARE_DIR="$tmp/share" ./install.sh
PATH="$tmp/bin:$PATH" LOCAL_LLM_RUNS_DIR="$tmp/share/runs" model-manager list
PATH="$tmp/bin:$PATH" LOCAL_LLM_RUNS_DIR="$tmp/share/runs" model-manager bootstrap --target remote:example-host --dry-run
PATH="$tmp/bin:$PATH" LOCAL_LLM_RUNS_DIR="$tmp/share/runs" model-manager deploy --target remote:example-host --dry-run
```

Expected: `model-manager list` shows no accepted profiles or launchers, `bootstrap --dry-run` prints a plan, and `deploy --dry-run` says there is nothing to deploy.

Verify the repo has no committed model launchers:

```bash
git ls-files 'scripts/start*.sh'
```

Expected: no output.

After a real install, `oc-local` should fail closed until you accept a model:

```bash
./install.sh
model-manager list
oc-local qwen reliable --info
```

Expected: fails with guidance until you accept a model.

## Architecture

Runtime services on the GPU host:

| Component | Type | Address | Purpose |
| --- | --- | --- | --- |
| `llama-server.service` | user systemd | `127.0.0.1:8080` | Runs the accepted generated launcher selected by `current-model.env`. |
| `local-llm-switcher.service` | user systemd | `127.0.0.1:3003` | Serves switcher APIs and injects the Open WebUI pill. |
| `open-webui` | Docker container | `127.0.0.1:3002` | Open WebUI application and SQLite data volume. |
| `local-llm-caddy` | Docker container | `127.0.0.1:3001` | Front proxy for Open WebUI, WebSockets, and switcher routes. |
| Cloudflare tunnel | external service | `llm.example.com -> http://localhost:3001` | Public entrypoint protected by Cloudflare Access. |

Cloudflare is the public security boundary. The tunnel publishes only Caddy on `localhost:3001`; Open WebUI, the switcher, and `llama-server` stay bound to local/private addresses. Cloudflare Access should enforce identity before a browser reaches Open WebUI.

![Open WebUI switcher pill](docs/assets/open-webui-switcher-pill.svg)

Request flow:

1. Browser opens the Cloudflare hostname.
2. Cloudflare Access login and policy check complete.
3. Cloudflare forwards to Caddy on `:3001`.
4. Caddy sends API/assets/WebSockets to Open WebUI on `:3002`.
5. Caddy sends page HTML and `/api/local-llm/*` to the switcher on `:3003`.
6. `llama-server` serves the active accepted model on `:8080`.

## Install Guide

### 1. Prerequisites

Client machine:

- OpenCode installed.
- SSH access to the model-server host.
- `~/.local/bin` on `PATH`.
- Bash, Python 3, `ssh`, and `scp` available.

The client tools are tested from a macOS client and expected to work from Linux clients with the same prerequisites.

Server machine:

- Linux host with user systemd.
- `llama.cpp` built under the chosen `$REMOTE_DIR`.
- GPU runtime configured for your hardware.
- Docker installed for Open WebUI and Caddy.
- Cloudflare tunnel routing the public hostname to `http://localhost:3001` if public browser access is wanted.

Set these shell variables while following the examples:

```bash
MODEL_HOST=gpu-box.example.lan
MODEL_USER=llmuser
REMOTE_DIR=/home/llmuser/llama.cpp
MODEL_API_BASE=http://gpu-box.example.lan:8080/v1
PUBLIC_LLM_HOST=llm.example.com
```

### 2. Install Client Commands

Run from this repo on the client machine:

```bash
./install.sh
```

This installs `oc-local`, `hardware-analyzer`, `model-discovery`, `model-manager`, and `update-manager` into `~/.local/bin`.

Check wrapper resolution without starting a model:

```bash
oc-local <family> <profile> --info
```

### 3. Bootstrap And Accept A Model

```bash
model-manager bootstrap --target remote:<host> --dry-run
model-manager bootstrap --target remote:<host> --yes
model-manager discover "coding gguf" --target remote:<host>
model-manager benchmark <source> --target remote:<host> --full
model-manager accept <benchmark.json>
model-manager deploy --target remote:<host> --dry-run
model-manager export > local-llm-backup.json
model-manager restore local-llm-backup.json
```

`model-manager` owns the GGUF lifecycle: Readable inventory, discovery, benchmark runs, accepted state, updates, replacements, deletes, export, and restore.

Names in human output use this convention:

- source: Hugging Face repo or local profile source.
- file: selected GGUF file or quant.
- launcher: generated runnable entry used by OpenCode and Open WebUI.

Accepting a benchmark records accepted metadata and generated launchers under `$HOME/.local/share/local_llm` / `runs`. `model-manager deploy --target remote:<host> --dry-run` previews the generated launchers and switcher/service files that would need to be copied to the GPU host; it does not copy files yet.

### 4. Server Wiring Status

At this stage, the fresh checkout has installed client tools and recorded accepted launcher state locally. It has not deployed that generated state to the GPU host.

Server service and Open WebUI wiring are still a later/manual setup step. Do not enable `llama-server.service` from a fresh checkout until generated launcher state has been manually copied from the deploy preview plan.

The repo-managed support files are templates/helpers for that later step:

```bash
scp docker-compose.yml "$MODEL_HOST:$REMOTE_DIR/docker-compose.yml"
scp scripts/run-current-model.sh scripts/local-llm-switcher.py \
  scripts/Caddyfile.local-llm scripts/run-local-llm-caddy-container.sh \
  "$MODEL_HOST:$REMOTE_DIR/"
scp scripts/local-llm-switcher.service \
  "$MODEL_HOST:/home/$MODEL_USER/.config/systemd/user/local-llm-switcher.service"
ssh "$MODEL_HOST" "chmod +x '$REMOTE_DIR'/run-current-model.sh '$REMOTE_DIR'/run-local-llm-caddy-container.sh"
```

If you manually wire the server before deploy support exists, copy the generated launcher referenced by accepted state to the GPU host and create `$REMOTE_DIR/current-model.env` yourself. The `llama-server.service` unit should call `$REMOTE_DIR/run-current-model.sh`; that helper reads `$REMOTE_DIR/current-model.env`, for example:

```bash
REMOTE_SCRIPT=<generated-launcher>
REMOTE_PROFILE=reliable
```

Only restart after the service unit, helper scripts, `current-model.env`, and generated launcher target are all present on the GPU host:

```bash
ssh "$MODEL_HOST" 'systemctl --user restart llama-server.service'
```

Inspect logs when startup fails:

```bash
ssh "$MODEL_HOST" 'journalctl --user -u llama-server.service -n 160 --no-pager'
```

### 5. Manual WebUI Support Files

Open WebUI, Caddy, and the switcher also require manual template setup until deploy support exists. Start only the services whose unit files, containers, and config have been copied and reviewed on the GPU host.

```bash
ssh "$MODEL_HOST" 'systemctl --user daemon-reload'
ssh "$MODEL_HOST" 'systemctl --user enable --now local-llm-switcher.service'
ssh "$MODEL_HOST" "cd '$REMOTE_DIR' && LOCAL_LLM_CADDYFILE=./Caddyfile.local-llm docker compose up -d"
```

If Compose is unavailable, start Caddy with the helper:

```bash
ssh "$MODEL_HOST" "'$REMOTE_DIR'/run-local-llm-caddy-container.sh"
```

### 6. Configure Cloudflare Tunnel And Access

Do not commit Cloudflare credentials, tunnel tokens, certs, generated tunnel config, or adjacent credential files to this repo.

Install `cloudflared` on Ubuntu 26:

```bash
ssh "$MODEL_HOST" 'curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null'
ssh "$MODEL_HOST" 'echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main" | sudo tee /etc/apt/sources.list.d/cloudflared.list >/dev/null'
ssh "$MODEL_HOST" 'sudo apt update && sudo apt install -y cloudflared'
```

Authenticate and route the hostname from the GPU host:

```bash
ssh -t "$MODEL_HOST" 'cloudflared tunnel login'
ssh "$MODEL_HOST" 'cloudflared tunnel create local-llm'
ssh "$MODEL_HOST" "cloudflared tunnel route dns local-llm '$PUBLIC_LLM_HOST'"
```

Create or review the tunnel config before installing the system service so the service reads the intended user config. The public hostname should point at Caddy, not directly at Open WebUI. Use placeholders for Cloudflare values and keep this file off git-tracked paths:

```bash
ssh "$MODEL_HOST" 'mkdir -p ~/.cloudflared'
ssh "$MODEL_HOST" "cat >~/.cloudflared/config.yml" <<'EOF'
tunnel: <TUNNEL_ID_OR_NAME>
credentials-file: /home/<MODEL_USER>/.cloudflared/<TUNNEL_ID>.json
ingress:
  - hostname: <PUBLIC_LLM_HOST>
    service: http://localhost:3001
  - service: http_status:404
EOF
```

Install and start the system service with the explicit config path:

```bash
ssh "$MODEL_HOST" "sudo cloudflared --config /home/$MODEL_USER/.cloudflared/config.yml service install"
ssh "$MODEL_HOST" 'sudo systemctl enable --now cloudflared'
```

The effective mapping is `$PUBLIC_LLM_HOST -> service: http://localhost:3001`.

### 7. Verify Manual Wiring

```bash
ssh "$MODEL_HOST" 'systemctl --user status local-llm-switcher.service'
ssh "$MODEL_HOST" 'docker ps --filter name=open-webui'
ssh "$MODEL_HOST" 'docker ps --filter name=local-llm-caddy'
ssh "$MODEL_HOST" 'curl -fsS http://127.0.0.1:3001/api/local-llm/current'
```

Open WebUI listens on http://127.0.0.1:3002. Caddy listens on http://127.0.0.1:3001. local-llm-switcher listens on http://127.0.0.1:3003. Cloudflare stays pointed at port 3001.

## Helper Tools

### Hardware Analyzer

hardware-analyzer reports the machine it runs on. On a client machine, it reports local CPU/RAM and usually cannot see the remote GPU. To inspect the model server, run it on the GPU host or use remote hardware tooling there.

```bash
hardware-analyzer
hardware-analyzer --remote "$MODEL_HOST"
```

### Model Discovery

`model-discovery` queries candidate sources, detects target hardware, ranks GGUF candidates, and can print more detailed output.

```bash
model-discovery --detailed
model-manager discover "coding gguf" --target remote:<host>
```

### Model Manager

```bash
model-manager list --target "remote:$MODEL_HOST"
model-manager status
model-manager discover "coding gguf" --target "remote:$MODEL_HOST"
model-manager benchmark <source> --target "remote:$MODEL_HOST" --full
model-manager accept <benchmark.json>
model-manager deploy --target "remote:$MODEL_HOST" --dry-run
model-manager export > local-llm-backup.json
model-manager restore local-llm-backup.json
model-manager update --target "remote:$MODEL_HOST" --dry-run
model-manager replace <old-file> <new-repo> --target "remote:$MODEL_HOST" --dry-run
```

If the remote host lacks the preferred download CLI, update flows fall back to a Python stdlib downloader.

### Update Manager

update-manager is a compatibility helper. It does not mutate files; use `model-manager` for model workflow lifecycle commands.

```bash
update-manager --candidates
```

## Web Switcher

The public Open WebUI path uses three local services on the GPU host:

- Caddy listens on http://127.0.0.1:3001.
- Open WebUI listens on http://127.0.0.1:3002.
- local-llm-switcher listens on http://127.0.0.1:3003.
- Cloudflare stays pointed at port 3001, so the public tunnel does not need to change.
- Caddy routes `/api/local-llm/*` and `/_switcher` to the switcher.
- Caddy routes Open WebUI API, asset, and WebSocket traffic directly to Open WebUI.
- Caddy routes page HTML through the switcher so it can inject the bottom-right `LLM` pill.

Browser switch flow:

1. The model picker calls `POST /api/local-llm/switch`.
2. The switcher writes `$REMOTE_DIR/current-model.env`.
3. The switcher restarts `llama-server.service`.
4. The switcher waits until `/v1/models` reports the expected alias.
5. The switcher updates Open WebUI's stored selected model.
6. The switcher ensures an Open WebUI model row and read grants exist for that alias.
7. The browser navigates to a fresh chat pane without prompting.

Switcher endpoints:

| Endpoint | Purpose |
| --- | --- |
| `GET /api/local-llm/models` | List configured launcher/profile choices. |
| `GET /api/local-llm/current` | Show the selected `current-model.env` entry and live model aliases. |
| `POST /api/local-llm/switch` | Write `current-model.env`, restart `llama-server.service`, and wait for the requested alias. |
| `GET /_switcher` | Fallback page using the same APIs when the injected Open WebUI widget is unavailable. |

Operational checks:

```bash
ssh "$MODEL_HOST" 'docker restart open-webui'
ssh "$MODEL_HOST" "systemctl --user restart local-llm-switcher.service llama-server.service && '$REMOTE_DIR'/run-local-llm-caddy-container.sh"
ssh "$MODEL_HOST" 'docker rm -f local-llm-caddy && systemctl --user disable --now local-llm-switcher.service'
ssh "$MODEL_HOST" 'docker rm -f open-webui && docker run -d --name open-webui --restart unless-stopped --network host -e PORT=3001 -v open-webui:/app/backend/data ghcr.io/open-webui/open-webui:main'
```

## Model Workflow

Use this section for day-to-day model work. Scratch plans under `docs/plans/` and agent notes under `docs/superpowers/` are not operating docs. Keep benchmark reports in `docs/benchmarks/`.

Inventory and discovery:

```bash
model-manager list --target "remote:$MODEL_HOST"
model-manager discover "coding gguf" --target "remote:$MODEL_HOST"
```

Track a candidate explicitly when you want it to show as pending work:

```bash
model-manager select --repo <hf-repo> --family <family> --alias <alias> --target "remote:$MODEL_HOST"
```

Benchmark and accept only benchmark-backed models:

```bash
model-manager benchmark <source> --target "remote:$MODEL_HOST" --full
model-manager accept <benchmark.json>
model-manager export > local-llm-backup.json
```

## Verification

```bash
bash -n test_oc_local.sh
shellcheck test_oc_local.sh
./test_oc_local.sh
```

During the zero-model migration, the full smoke test may stop at the expected tracked-launcher check until launcher/profile state is removed in the next task.
