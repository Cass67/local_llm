# Web Model Switcher Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Run a web switcher on `ubt26:3001` that proxies Open WebUI on `3002` and injects a model dropdown for restarting `llama-server` with an allowed launcher/profile.

**Architecture:** A small Python ASGI app owns port `3001`, proxies Open WebUI traffic to `127.0.0.1:3002`, injects a dropdown into HTML responses, and exposes `/api/local-llm/*` endpoints that write `current-model.env` and restart the existing user `llama-server.service`. Open WebUI moves behind it to port `3002`; Cloudflare remains pointed at `3001`.

**Tech Stack:** Python 3 stdlib plus FastAPI/Starlette/httpx if available on `ubt26`, systemd user services, Open WebUI, llama.cpp OpenAI-compatible API.

---

### Task 1: Create Switcher App And Unit Files

**Files:**
- Create: `scripts/local-llm-switcher.py`
- Create: `scripts/local-llm-switcher.service`

**Step 1: Implement app**

Create `scripts/local-llm-switcher.py` with:

- allowlist for installed reliable families.
- `GET /api/local-llm/models`.
- `GET /api/local-llm/current`.
- `POST /api/local-llm/switch`.
- `GET /_switcher` fallback HTML.
- catch-all proxy to `OPENWEBUI_BASE_URL`, default `http://127.0.0.1:3002`.
- HTML injection for `text/html` responses.
- streaming proxy support for non-HTML responses.
- atomic writes to `/home/cass/llama.cpp/current-model.env`.
- `systemctl --user restart llama-server.service`.
- polling `http://127.0.0.1:8080/v1/models` until expected alias appears.

If FastAPI/httpx are unavailable locally, write code that will run with the packages present on `ubt26`; verify syntax locally with Python only.

**Step 2: Implement service template**

Create `scripts/local-llm-switcher.service`:

```ini
[Unit]
Description=Local LLM Open WebUI Switcher Proxy
After=network.target open-webui.service llama-server.service

[Service]
Type=simple
WorkingDirectory=%h/llama.cpp
Environment=OPENWEBUI_BASE_URL=http://127.0.0.1:3002
Environment=LLAMA_API_BASE=http://127.0.0.1:8080
ExecStart=/usr/bin/python3 %h/llama.cpp/local-llm-switcher.py
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
```

Adjust `ExecStart` later if `uvicorn` is required instead of direct Python.

**Step 3: Verify syntax**

Run:

```bash
python3 -m py_compile scripts/local-llm-switcher.py
```

Expected: exit code 0.

### Task 2: Local Static Review And API Shape Check

**Files:**
- Modify only if Task 1 app has issues: `scripts/local-llm-switcher.py`

**Step 1: Check allowlist against launcher metadata**

Compare app allowlist to `scripts/oc-local --info <family> reliable --lean` for all included families.

Expected: script/profile/alias match current launchers.

**Step 2: Check injection snippet**

Ensure the injected snippet:

- uses `/api/local-llm/models`, `/api/local-llm/current`, `/api/local-llm/switch`.
- does not depend on Open WebUI internals.
- uses fixed-position CSS with a high z-index.

### Task 3: Deploy To `ubt26`

**Files:**
- Remote: `/home/cass/llama.cpp/local-llm-switcher.py`
- Remote: `/home/cass/.config/systemd/user/local-llm-switcher.service`

**Step 1: Copy files**

Run:

```bash
scp scripts/local-llm-switcher.py ubt26:/home/cass/llama.cpp/local-llm-switcher.py
scp scripts/local-llm-switcher.service ubt26:/home/cass/.config/systemd/user/local-llm-switcher.service
```

**Step 2: Verify dependencies**

Run:

```bash
ssh ubt26 'python3 -m py_compile /home/cass/llama.cpp/local-llm-switcher.py && python3 - <<"PY"
import importlib.util
for name in ["fastapi", "uvicorn", "httpx"]:
    print(name, bool(importlib.util.find_spec(name)))
PY'
```

If dependencies are missing, install user-local only if safe, or switch implementation to dependencies already present.

### Task 4: Move Open WebUI Behind Proxy

**Files:**
- Remote user/system service or process config for Open WebUI.

**Step 1: Identify Open WebUI service/process source**

Run:

```bash
ssh ubt26 'systemctl --user list-units --type=service | grep -i webui || true; systemctl list-units --type=service | grep -i webui || true; pgrep -af "open_webui|uvicorn.*3001"'
```

**Step 2: Move Open WebUI to port 3002**

Edit the service or launch command that starts Open WebUI so it uses `--port 3002`.

Restart Open WebUI and verify:

```bash
ssh ubt26 'curl -fsS http://127.0.0.1:3002/ >/dev/null'
```

Expected: Open WebUI responds on `3002`, and nothing except the future switcher uses `3001`.

### Task 5: Start Switcher And Verify Proxy

**Files:**
- Remote service: `local-llm-switcher.service`

**Step 1: Enable/start switcher**

Run:

```bash
ssh ubt26 'systemctl --user daemon-reload && systemctl --user enable --now local-llm-switcher.service'
```

**Step 2: Verify API**

Run:

```bash
ssh ubt26 'curl -fsS http://127.0.0.1:3001/api/local-llm/models; curl -fsS http://127.0.0.1:3001/api/local-llm/current'
```

Expected: JSON model list and current model.

**Step 3: Verify Open WebUI proxy/injection**

Run:

```bash
ssh ubt26 'curl -fsS http://127.0.0.1:3001/ | grep -q "local-llm-switcher"'
```

Expected: HTML includes injected switcher snippet.

### Task 6: Verify Switching End-To-End

**Files:**
- Remote: `/home/cass/llama.cpp/current-model.env`

**Step 1: Switch to a small/current model via API**

Use the current model first, then one alternate reliable model.

Run:

```bash
ssh ubt26 'curl -fsS -X POST http://127.0.0.1:3001/api/local-llm/switch -H "Content-Type: application/json" --data "{\"id\":\"qwen-27b-hauhau:reliable\"}"'
```

Expected: JSON ok response and `/v1/models` reports `qwen3.6-27b-hauhau`.

**Step 2: Switch to another known-good model**

Run:

```bash
ssh ubt26 'curl -fsS -X POST http://127.0.0.1:3001/api/local-llm/switch -H "Content-Type: application/json" --data "{\"id\":\"qwen-hauhau:reliable\"}"'
```

Expected: JSON ok response and `/v1/models` reports `qwen3.6-35b-a3b-hauhau`.

**Step 3: Restore preferred model**

Restore `qwen-27b-hauhau:reliable` unless user requested a different final model.

### Task 7: Docs And Verification

**Files:**
- Modify: `README.md`
- Modify: `test_oc_local.sh` if adding assertions for new files/docs is appropriate.

**Step 1: Update docs**

Document:

- Open WebUI now listens on `3002`.
- Switcher proxy listens on `3001`.
- Cloudflare stays on `3001`.
- How to inspect/restart services.
- Rollback steps.

**Step 2: Verify**

Run:

```bash
python3 -m py_compile scripts/local-llm-switcher.py
bash -n test_oc_local.sh
shellcheck test_oc_local.sh
```

Also verify remote:

```bash
ssh ubt26 'systemctl --user is-active local-llm-switcher.service open-webui.service llama-server.service || true; curl -fsS http://127.0.0.1:3001/api/local-llm/current; curl -fsS http://127.0.0.1:3001/ >/dev/null'
```
