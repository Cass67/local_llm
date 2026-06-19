# local_llm

A self-hosted LLM management system for AMD and Nvidia GPU workstations. Models run in an isolated Docker container with full GPU access; a Svelte web UI handles search, install, configuration, model switching, benchmarking, chat, and observability.

## Screenshots

| Tab | Description |
|---|---|
| [![Models](screenshot-models.png)](screenshot-models.png) | **Models** — browse installed models, view details, edit config, audit orphaned registrations |
| [![Search](screenshot-search.png)](screenshot-search.png) | **Search** — discover and install GGUF models from HuggingFace |
| [![Architecture](screenshot-architecture.png)](screenshot-architecture.png) | **Architecture** — system diagram, cluster management, profile selection when loading a model |
| [![Profiles](screenshot-profiles.png)](screenshot-profiles.png) | **Profiles** — named load configs per model family: edit raw JSON, clone, set default, import from models |
| [![Status](screenshot-status.png)](screenshot-status.png) | **Status** — live TPS sparkline, runner health, active model, system stats, audit orphaned registrations |
| [![Benchmarks](screenshot-benchmarks.png)](screenshot-benchmarks.png) | **Benchmarks** — run configurable benchmarks, view latency/throughput trends across runs |
| [![Logs](screenshot-logs.png)](screenshot-logs.png) | **Logs** — real-time Docker container log streaming (runner, mgmt, router) |
| [![Chat](screenshot-chat.png)](screenshot-chat.png) | **Chat** — Open WebUI full chat interface with model selection and conversation history |
| [![Traces](screenshot-traces.png)](screenshot-traces.png) | **Traces** — Langfuse LLM request tracing: TTFT, token throughput, per-request timelines |

### Feature summary

- **Search and install** GGUF models from HuggingFace, downloading directly into the local HF cache.
- **Switch models** on demand — the management container creates and replaces the runner container via the Docker socket.
- **Edit model configs** — context size, batch, ngl, tensor split, flash attention, Jinja templates, MTP speculative decoding — without touching JSON by hand.
- **Profiles** — named load configurations per model family, stored in `profiles.json`. Select a profile when starting a model on a cluster. Edit as raw JSON, clone, set a default, or auto-seed from existing model configs. Profile fields (tensor split, context, flash attention, etc.) are merged into the launch metadata at start time.
- **Audit** — scan registered models against the HF cache; remove stale registrations whose GGUF files have been deleted from disk. Available on the Models and Status tabs.
- **Benchmark** models with configurable llama.cpp parameters (temperature, seed, top-p, top-k, repeat penalty, system prompt) and track latency/throughput trends across runs.
- **Chat** via Open WebUI at `/chat/` — full conversation UI with web search (SearXNG), model selection, history, and streaming.
- **Router** — keyword-based request router with live config reload, routing rules editor in the Architecture tab, and per-request routing audit. Open WebUI defaults to the `router` model so all chats are automatically dispatched to the best cluster.
- **Idle unload** — clusters auto-stop after a configurable idle timeout (5 min–2 hr) to save GPU power. Models reload automatically on the next request. Toggle and timeout in the Architecture tab.
- **Web search** — SearXNG container on `:3005` wired to Open WebUI. Enable per-chat with the 🌐 icon.
- **Stream logs** from the runner, management, or router containers in real time.
- **Monitor** TPS sparkline and runner slot health in the Status panel.
- **Trace** LLM requests with Langfuse: TTFT, token throughput, prompt/completion tokens, per-request timeline.

All model serving goes through the `local-llm-runner` Docker container. There are no host-side launcher scripts or systemd services for inference.

---

## Architecture

```
Browser
  │
  │  :3001  (Caddy)
  ▼
local-llm-caddy  ──/ui/*, /api/local-llm/*, /v1/*──▶  local-llm-mgmt    :3100
                 ──/*, /chat/*──────────────────────▶  open-webui         :3101
                 ──/traces*─────────────────────────▶  local-llm-langfuse :3004
  │
  │  local-llm-mgmt creates/stops cluster runners via Docker socket
  ▼
local-llm-router  :3200  (keyword router — dispatches to per-cluster runners)
  │
  ├── local-llm-runner-cluster-7900s  :8081  (ROCm, AMD 7900s)
  └── local-llm-runner-cluster-p40    :8082  (CUDA, Nvidia P40)
        │
        ├── GPU devices (ROCm /dev/kfd,/dev/dri or Nvidia device requests)
        └── ~/.cache/huggingface/hub  (GGUF model files)

open-webui  :3101  ──web search──▶  searxng  :3005
local-llm-langfuse  :3004  (LLM request tracing)
local-llm-postgres  :5433  (Langfuse database)
```

| Container | Port | Purpose |
|---|---|---|
| `local-llm-mgmt` | `3100` | FastAPI backend + Svelte UI. Manages models, launches runner. |
| `local-llm-runner` | `8080` | llama.cpp `llama-server`. Created on demand for the active model. |
| `local-llm-router` | `3200` | Keyword-based request router. OpenWebUI points here by default. |
| `local-llm-caddy` | `3001` | Reverse proxy. Single public entrypoint. |
| `open-webui` | `3101` | Full chat interface. Defaults to `router` model for automatic routing. |
| `searxng` | `3005` | Self-hosted web search for OpenWebUI. |
| `local-llm-langfuse` | `3004` | Langfuse v2 — LLM request tracing UI. |
| `local-llm-postgres` | `5433` | PostgreSQL for Langfuse (isolated from any other Postgres on the host). |

**State** lives outside the containers:

| Path | Purpose |
|---|---|
| `~/.local/share/local_llm/runs/accepted/` | Per-model JSON metadata (config, hf_repo, hf_file, etc.). |
| `~/.local/share/local_llm/profiles.json` | Named load profiles per model family. |
| `~/.local/share/local_llm/` | Runner state, benchmark and chat metrics databases. |
| `~/.cache/huggingface/hub/` | Downloaded GGUF files (shared between mgmt download and runner mount). |

---

## Setup

### Prerequisites

- Linux host with an AMD GPU (ROCm or Vulkan) and/or an Nvidia GPU (CUDA).
- Docker with Compose plugin.
- AMD: `/dev/kfd`, `/dev/dri` accessible to your user (render group).
- Nvidia: [nvidia-container-toolkit](https://github.com/NVIDIA/nvidia-container-toolkit) installed on the host so Docker can grant GPU device requests.

### 1. Configure

```bash
cp .env.example .env
# Verify RENDER_GROUP and DOCKER_GROUP match your system:
getent group render | cut -d: -f3
getent group docker | cut -d: -f3
```

### 2. Build the runner images

```bash
cd runner && ./build.sh vulkan && ./build.sh rocm && ./build.sh cuda && cd ..
```

Each backend gets its own image — `local-llm-runner-vulkan:latest`, `local-llm-runner-rocm:latest`,
`local-llm-runner-cuda:latest` — built from `runner/<backend>/Dockerfile`. Only build the backends
your hardware supports; the build stage compiles llama.cpp from source for that backend, and the
runtime stage is stripped down to the binary and the GPU libs it needs.

### 3. Start everything

```bash
docker compose up -d
```

| Service | URL | Purpose |
|---|---|---|
| Management UI | http://localhost:3001/ui/ | Main interface |
| Open WebUI | http://localhost:3001/ | Full chat (optional) |
| Langfuse | http://localhost:3004/ | Request tracing |

To start without Open WebUI:

```bash
docker compose up -d local-llm-mgmt local-llm-caddy local-llm-postgres local-llm-langfuse
```

### 4. Langfuse first-time setup

On first start, go to `http://<host>:3004/`, register an account, create an org and project, then generate API keys under **Settings → API Keys**. Add the keys to `docker-compose.yml` under `local-llm-mgmt`:

```yaml
LANGFUSE_PUBLIC_KEY: "pk-lf-..."
LANGFUSE_SECRET_KEY: "sk-lf-..."
LANGFUSE_HOST: "http://localhost:3004"
```

Restart mgmt to pick them up: `docker compose up -d local-llm-mgmt`

If `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` are absent, tracing is silently disabled — everything else works normally.

### 5. Update

After pulling changes or editing the UI:

```bash
cd ui && bun run build && cd ..
docker compose build local-llm-mgmt
docker compose up -d local-llm-mgmt
```

---

## Usage

### Installing a model

1. Open **http://localhost:3001/ui/** → **Search** tab.
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
| flash attention | `-fa on` |
| jinja templates | `--jinja` |
| MTP | `--spec-type draft-mtp` + `--spec-draft-n-*` |
| flags | extra raw args appended verbatim |

Changes take effect on the next model switch.

### Profiles

**Profiles** tab. Select a model family, then select or create a named profile. Each profile is a raw JSON object of llama-server config fields — the same fields as the Edit form but unstructured, suitable for complex configs like dual-GPU tensor splits. Profiles are stored in `~/.local/share/local_llm/profiles.json`.

- **Import from models** — seeds all families from their current accepted model configs. Always overwrites.
- **Clone** — duplicate an existing profile under a new name.
- **Set default** — mark a profile as the one pre-selected when loading a model on a cluster.

When you start a model on a cluster in the **Architecture** tab, select a profile from the dropdown. The profile config is merged into the launch metadata before any cluster-specific GPU settings (visible devices, tensor split) are applied.

**Profile is the complete source of truth.** Only fields present in the profile are passed to llama-server — there are no hidden runtime defaults. What you see in the editor is exactly what runs.

#### Single-GPU profile

```json
{
  "ngl": 999,
  "batch": 4096,
  "ubatch": 256,
  "context": 32768,
  "cache_prompt": true,
  "cache_ram": 16384,
  "context_shift": true,
  "ctx_checkpoints": 64,
  "checkpoint_min_step": 4096,
  "flash_attention": true,
  "reasoning": false,
  "repeat_penalty": 1.05,
  "presence_penalty": 0,
  "timeout": 600,
  "threads_http": 2,
  "parallel": 1,
  "no_cont_batching": true,
  "prio": 2,
  "no_warmup": true
}
```

#### Multi-GPU profile (two cards, layer split)

```json
{
  "ngl": 999,
  "split_mode": "layer",
  "tensor_split": "1,1",
  "visible_devices": "0,1",
  "batch": 4096,
  "ubatch": 256,
  "context": 65536,
  "cache_prompt": true,
  "cache_ram": 16384,
  "context_shift": true,
  "ctx_checkpoints": 64,
  "checkpoint_min_step": 4096,
  "flash_attention": true,
  "reasoning": false,
  "repeat_penalty": 1.05,
  "presence_penalty": 0,
  "timeout": 600,
  "threads_http": 2,
  "parallel": 1,
  "no_cont_batching": true,
  "prio": 2,
  "no_warmup": true
}
```

`tensor_split` is a comma-separated weight list — `"1,1"` distributes evenly across two GPUs. For unequal VRAM use ratios like `"2,1"`. `visible_devices` maps to `HIP_VISIBLE_DEVICES` / `CUDA_VISIBLE_DEVICES`. Use **Import from models** to seed profiles automatically from each model's current config.

### Audit

**Models** or **Status** → **Audit** button. Scans all registered model entries and checks whether their GGUF files still exist in the HF cache. Orphaned entries (file deleted from disk) are listed. Click **Remove N** to clean them up.

### Benchmarking

**Benchmarks** tab. Select a model from the installed list, set parameters, enter or generate a prompt, and run. Results are stored in SQLite and trend graphs update across runs. The model auto-switches if the selected model is not currently loaded.

### Chat

**Chat** link in the nav opens Open WebUI in the same tab with a back link.

### Traces

**Traces** link in the nav opens Langfuse in a new tab. Every chat completion (streaming and non-streaming) is traced with TTFT, duration, token counts, and TPS. Traces appear within seconds of a request completing.

### Router

The **Architecture** tab includes a router config editor for managing keyword-based request routing. Requests sent with `model=auto` or `model=router` are matched against routing rules — the first matching rule's target cluster handles the request. Rules are evaluated in order and support exact-prefix matching on the prompt text.

The router is a standalone container (`local-llm-router`) that reloads its config live when updated via the UI. Each routing decision is logged and visible in the **Logs** tab (router source) and in the Langfuse trace metadata.

Open WebUI defaults to the `router` model so all conversations are automatically dispatched to the appropriate cluster without manual model selection.

### Idle unload

In the **Architecture** tab, toggle **Auto-unload idle models** to automatically stop cluster runners after a period of inactivity. A dropdown lets you choose the timeout (5 min, 10 min, 15 min, 30 min, 1 hr, 2 hr). When a request arrives for an unloaded cluster, the model reloads automatically before the request is served. Desired state is preserved across unloads so the model comes back with the same configuration.

This is useful for reducing GPU idle power — a P40 with a model loaded draws ~50 W idle; unloaded it drops to ~10 W.

### Web search

Open WebUI has web search built in, powered by a local SearXNG container on `:3005`. Enable per-message with the 🌐 globe icon. SearXNG is configured to return JSON results with the bot limiter disabled so programmatic queries work. Web page fetching is bypassed in favour of search snippets to keep context small and response fast.

### Status

**Status** tab shows a live TPS sparkline (last 30 chat completions), runner slot health (idle/processing), and system stats from the Raspberry Pi agent if configured.

### Logs

**Logs** tab streams Docker container logs in real time. Toggle between the runner (`local-llm-runner`) and management (`local-llm-mgmt`) containers.

---

## Configuration

### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `RUNNER_IMAGE_VULKAN` | `local-llm-runner-vulkan:latest` | Image used when launching a model with `backend: vulkan`. |
| `RUNNER_IMAGE_ROCM` | `local-llm-runner-rocm:latest` | Image used when launching a model with `backend: rocm`. |
| `RUNNER_IMAGE_CUDA` | `local-llm-runner-cuda:latest` | Image used when launching a model with `backend: cuda`. |
| `LOCAL_LLM_STATE_DIR` | `/state` | Accepted metadata and state files (container path). |
| `MODELS_CACHE_DIR` | `/models` | GGUF cache path inside the container. |
| `HOST_MODELS_CACHE_DIR` | same as above | Host-side path passed to the runner container bind mount. |
| `LLAMA_SERVER_PORT` | `8080` | Port the runner listens on. |
| `RENDER_GROUP` | `991` | GID of the render group — needed for GPU access. |
| `DOCKER_GROUP` | `107` | GID of the docker group — needed for Docker socket access. |
| `LOCAL_LLM_DISABLE_THINKING_BY_DEFAULT` | `false` | Inject `enable_thinking: false` into requests that don't explicitly set it. Prevents reasoning-only models from returning empty `content`. |
| `LANGFUSE_PUBLIC_KEY` | — | Langfuse project public key. Tracing disabled if absent. |
| `LANGFUSE_SECRET_KEY` | — | Langfuse project secret key. |
| `LANGFUSE_HOST` | `http://localhost:3004` | Langfuse server URL reachable from the mgmt container. |

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
cd ui && bun run build && cd ..
docker compose build local-llm-mgmt
docker compose up -d local-llm-mgmt
```

To deploy to a remote host (replace `ubt26` with your host):

```bash
rsync -av container/ runner/ scripts/ docker-compose.yml ubt26:~/git/local_llm/
ssh ubt26 "cd ~/git/local_llm && docker compose build local-llm-mgmt && docker compose up -d"
```

### Runner images

Each backend is its own multi-stage Docker build under `runner/<backend>/Dockerfile`:

- **vulkan**: compiles llama.cpp with `-DGGML_VULKAN=ON`. Runtime stage is plain Ubuntu + Mesa Vulkan drivers.
- **rocm**: compiles llama.cpp with `-DGGML_HIP=ON -DAMDGPU_TARGETS=gfx1100` (override `AMDGPU_TARGETS`
  for other RDNA/CDNA chips) using the ROCm devel image. Runtime stage installs only the HIP runtime libs.
- **cuda**: compiles llama.cpp with `-DGGML_CUDA=ON` using Nvidia's `cuda:12.6.3-devel` image. Runtime
  stage uses the matching `cuda:12.6.3-runtime` image.

GPU passthrough differs by backend in the runner container spec:

```
# rocm / vulkan
devices: ["/dev/kfd", "/dev/dri"]
group_add: ["991"]   # render group
environment: HIP_VISIBLE_DEVICES, ROCR_VISIBLE_DEVICES, GGML_VK_VISIBLE_DEVICES

# cuda
device_requests: [{"Driver": "nvidia", "Count": -1, "Capabilities": [["gpu"]]}]
environment: CUDA_VISIBLE_DEVICES
```

`network_mode: host` applies to all three.

---

## Caddy routing summary

`scripts/Caddyfile.local-llm` on port `3001`:

| Path | Upstream |
|---|---|
| `/ui/*`, `/api/local-llm/*`, `/v1/*` | `local-llm-mgmt :3100` |
| `/chat/*` | Inline HTML frame with back link to `/ui/` |
| `/traces*` | Redirect to `local-llm-langfuse :3004` (preserves client hostname) |
| `/`, `/static/*`, `/api/*` | `open-webui :3101` |
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
