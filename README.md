# local_llm

A self-hosted LLM management system for AMD GPU workstations. Models run in an isolated Docker container with full GPU access; a Svelte web UI handles search, install, configuration, model switching, benchmarking, and chat.

![local_llm architecture](docs/assets/local-llm-architecture.svg)

## What it does

- **Search and install** GGUF models from HuggingFace, downloading directly into the local HF cache.
- **Switch models** on demand — the management container creates and replaces the runner container via the Docker socket.
- **Benchmark** models with configurable llama.cpp parameters (temperature, seed, top-p, top-k, repeat penalty, system prompt) and track latency/throughput trends across runs.
- **Chat** directly in the browser through an OpenAI-compatible proxy.
- **Stream logs** from the runner or management container in real time.
- **Edit model configs** — context size, batch, ngl, tensor split, MTP speculative decoding — without touching JSON by hand.
- **Open WebUI** is optionally available through Caddy as a full chat interface.

All model serving goes through the `local-llm-runner` Docker container. There are no host-side launcher scripts or systemd services for inference.

---

## Architecture

```
Browser
  │
  │  :3001  (Caddy)
  ▼
local-llm-caddy  ──/ui/*, /api/local-llm/*, /v1/*──▶  local-llm-mgmt  :3100
                 ──/*, /chat/*──────────────────────▶  open-webui       :3101
  │
  │  local-llm-mgmt creates/stops runner via Docker socket
  ▼
local-llm-runner  :8080  (llama-server, GPU access)
  │
  ├── /dev/kfd, /dev/dri  (ROCm or Vulkan)
  └── ~/.cache/huggingface/hub  (GGUF model files)
```

| Container | Port | Purpose |
|---|---|---|
| `local-llm-mgmt` | `3100` | FastAPI backend + Svelte UI. Manages models, launches runner. |
| `local-llm-runner` | `8080` | llama.cpp `llama-server`. Created on demand for the active model. |
| `local-llm-caddy` | `3001` | Reverse proxy. Routes `/ui/`, `/api/`, `/v1/` to mgmt; root to Open WebUI. |
| `open-webui` | `3101` | Optional full chat interface backed by the mgmt `/v1` proxy. |

**State** lives outside the containers:

| Path | Purpose |
|---|---|
| `~/.local/share/local_llm/` | Accepted model metadata, current runner state, benchmark database. |
| `~/.cache/huggingface/hub/` | Downloaded GGUF files (shared between mgmt download and runner mount). |

---

## Setup

### Prerequisites

- Linux host with an AMD GPU (ROCm or Vulkan).
- Docker with Compose plugin.
- `/dev/kfd`, `/dev/dri` accessible to your user (render group).
- Python 3.11+ available on the host for `huggingface_hub` downloads inside the mgmt container.

### 1. Build the runner image

```bash
cd runner
./build.sh
```

This builds `local-llm-runner:latest` — a minimal Ubuntu image with llama.cpp compiled for ROCm and Vulkan. The build stage compiles from source; the runtime stage is stripped down with only the binary and GPU libs.

### 2. Build and start the management container

```bash
cd container
docker compose build local-llm
docker compose up -d local-llm
```

The management UI is now at **http://localhost:3100/ui/**.

### 3. Start Caddy (optional, for unified port access)

```bash
docker run -d --name local-llm-caddy --network host \
  -v "$PWD/scripts/Caddyfile.local-llm:/etc/caddy/Caddyfile:ro" \
  caddy:2
```

All services are then available through **http://localhost:3001/**.

### 4. Start Open WebUI (optional)

```bash
docker compose up -d open-webui
```

Accessible at **http://localhost:3001/** (root) or **/chat/** via Caddy. Backed by the management container's `/v1` proxy, so it uses whatever model the runner is serving.

---

## Usage

### Installing a model

1. Open **http://localhost:3100/ui/** → **Search** tab.
2. Enter a search query (e.g. `qwen 30b gguf`).
3. Click **Install** on a candidate. The model downloads into `~/.cache/huggingface/hub/`.

### Switching the active model

Go to **Models** tab. Click **Load** on any installed model. The management container:
1. Stops the current `local-llm-runner` container.
2. Waits for port 8080 to clear.
3. Creates a new `local-llm-runner` container with the correct model path, GPU env vars, and llama-server flags.
4. Waits up to 120 seconds for `/v1/models` to respond.

The UI shows a green dot when the runner is live.

### Editing a model config

**Models** → card menu → **Edit**. Fields map directly to llama-server args:

| Field | llama-server flag |
|---|---|
| ctx | `-c` |
| ngl | `-ngl` |
| batch / ubatch | `-b` / `-ub` |
| tensor split | `--tensor-split` |
| flags | appended verbatim |
| MTP | `--spec-type draft-mtp` + `--spec-draft-n-*` |

Changes take effect on the next model switch.

### Benchmarking

**Benchmarks** tab. Select a model from the installed list, set parameters, enter or generate a prompt, and run. Results are stored in SQLite and trend graphs update across runs. The model auto-switches if the selected model is not currently loaded.

### Chat / Playground

**Playground** tab for a simple chat interface within the management UI.  
**http://localhost:3001/** for Open WebUI (if running).

### Logs

**Logs** tab streams Docker container logs in real time. Toggle between the runner (`local-llm-runner`) and management (`local-llm-mgmt`) containers.

---

## Configuration

### docker-compose.yml mounts

```yaml
volumes:
  - ${HOME}/.local/share/local_llm:/state      # accepted metadata, state files
  - ${HOME}/.cache/huggingface/hub:/models      # GGUF cache
  - /var/run/docker.sock:/var/run/docker.sock   # runner container management
  - ${HOME}/git/local_llm/scripts:/scripts:ro   # model discovery scripts
```

### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `RUNNER_IMAGE` | `local-llm-runner:latest` | Image used when launching the runner container. |
| `LOCAL_LLM_STATE_DIR` | `/state` | Where accepted metadata and state files live (container path). |
| `MODELS_CACHE_DIR` | `/models` | GGUF cache path inside the container. |
| `HOST_MODELS_CACHE_DIR` | same as above | Host-side path passed to the runner container bind mount. |
| `LLAMA_SERVER_PORT` | `8080` | Port the runner listens on. |

### Accepted model metadata

Each model is stored as a JSON file under `~/.local/share/local_llm/runs/accepted/<family>.json`. Example:

```json
{
  "family": "qwen3.6-27b-heretic-q6-1gpu",
  "alias": "qwen3.6-27b-heretic-q6-1gpu",
  "model_name": "Qwen3.6 27B Heretic Q6",
  "profile": "reliable",
  "context": 131072,
  "backend": "rocm",
  "reasoning": false,
  "hf_repo": "username/Qwen3.6-27B-Heretic-GGUF",
  "hf_file": "Qwen3.6-27B-Heretic-Q6_K.gguf",
  "config": {
    "ngl": 999,
    "batch": 4096,
    "ubatch": 256,
    "ctx": 131072,
    "visible_devices": "0",
    "split_mode": "layer"
  }
}
```

The management container resolves the GGUF path from `hf_repo`/`hf_file` at launch time. Edit via the UI or directly; the next switch picks up the changes.

---

## Development

### Backend

```bash
cd container
python -m pytest tests/ -q
ruff format . && ruff check --fix .
```

FastAPI app at `container/backend/`. Routes under `container/backend/routes/`. Tests in `container/tests/`.

### UI

```bash
cd ui
bun install
bun run dev        # dev server on :5173
bun run build      # output to container/ui-dist/
```

Svelte 5 app. Components in `ui/src/components/`. Routes (panels) in `ui/src/routes/`. The built output is embedded in the management container image.

### Rebuilding and deploying

After UI or backend changes:

```bash
cd ui && bun run build
cd ../container && docker compose build local-llm && docker compose up -d local-llm
```

To deploy to a remote host (replace `ubt26` with your host):

```bash
rsync -av container/ ubt26:~/git/local_llm/container/
rsync -av runner/ ubt26:~/git/local_llm/runner/
ssh ubt26 "cd ~/git/local_llm/container && docker compose build local-llm && docker compose up -d local-llm"
```

### Runner image

The runner is a multi-stage Docker build:

- **Build stage**: clones llama.cpp at a pinned ref and compiles with ROCm (`-DGGML_HIPBLAS=ON`) and Vulkan (`-DGGML_VULKAN=ON`) support.
- **Runtime stage**: copies only the `llama-server` binary and required `.so` files into a clean Ubuntu image with ROCm and Vulkan runtime libs.

AMD GPU requirements in the runner container spec:

```
devices: ["/dev/kfd", "/dev/dri"]
group_add: ["991"]   # render group
environment: HIP_VISIBLE_DEVICES, ROCR_VISIBLE_DEVICES, GGML_VK_VISIBLE_DEVICES
network_mode: host
```

---

## Caddy routing summary

`scripts/Caddyfile.local-llm` on port `3001`:

| Path | Upstream |
|---|---|
| `/ui/*`, `/api/local-llm/*`, `/v1/*` | `local-llm-mgmt :3100` |
| `/chat/*` | Inline HTML frame (links back to `/ui/`) |
| `/` (root), `/static/*`, `/api/*` | `open-webui :3101` |
| `/_switcher` | `local-llm-mgmt :3100` |

---

## Pre-commit hooks

The repo enforces:

- `ruff check` and `ruff format` on Python files.
- `bandit` security scan.
- `radon` complexity check.
- `vulture` dead code detection.
- `pip-audit` dependency audit.
- `shfmt` and `shellcheck` on shell scripts.
- `gitleaks` for credential leaks.
