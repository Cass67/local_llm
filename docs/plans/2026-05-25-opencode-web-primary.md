# OpenCode Web Primary Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make OpenCode web the primary internet-facing UI and inject the local_llm model-switcher pill into OpenCode instead of Open WebUI.

**Architecture:** Keep `llama-server.service`, generated launcher state, `model-manager`, and the switcher API. Replace the default browser upstream from Open WebUI to OpenCode web while preserving the existing Caddy slot and `/api/local-llm/*` switcher endpoints. Open WebUI becomes optional legacy documentation, not the default web app.

**Tech Stack:** Bash, Python 3 `http.server`, Caddy, user systemd, Docker only for optional Caddy packaging, Cloudflare Access.

---

### Task 1: Rename Browser UI Concepts In Tests

**Files:**
- Modify: `test_oc_local.sh`
- Modify: `README.md`

**Step 1: Write failing README assertions**

Add assertions near the current README checks:

```bash
assert_contains "$readme_contents" "OpenCode web is the primary browser UI"
assert_contains "$readme_contents" "LOCAL_LLM_WEB_UPSTREAM=http://127.0.0.1:3002"
assert_contains "$readme_contents" "LOCAL_LLM_INJECT_TARGET=opencode"
assert_contains "$readme_contents" "Open WebUI is optional legacy"
assert_not_contains "$readme_contents" "The public Open WebUI path uses"
assert_not_contains "$readme_contents" "Open WebUI application and SQLite data volume"
```

**Step 2: Run test to verify failure**

Run: `./test_oc_local.sh`
Expected: FAIL because the docs still describe Open WebUI as the primary browser UI.

### Task 2: Make Switcher Upstream Generic

**Files:**
- Modify: `scripts/local-llm-switcher.py`
- Modify: `test_oc_local.sh`

**Step 1: Add tests for generic upstream env vars**

Add a Python compile/grep-style test that asserts the switcher uses generic names:

```bash
assert_contains "$(<"$repo_root/scripts/local-llm-switcher.py")" "LOCAL_LLM_WEB_UPSTREAM"
assert_contains "$(<"$repo_root/scripts/local-llm-switcher.py")" "LOCAL_LLM_INJECT_TARGET"
assert_not_contains "$(<"$repo_root/scripts/local-llm-switcher.py")" "OPENWEBUI_BASE_URL"
```

**Step 2: Replace Open WebUI-specific upstream names**

Change:

```python
OPENWEBUI_BASE_URL = os.environ.get("OPENWEBUI_BASE_URL", "http://127.0.0.1:3002").rstrip("/")
```

to:

```python
WEB_UPSTREAM = os.environ.get("LOCAL_LLM_WEB_UPSTREAM", "http://127.0.0.1:3002").rstrip("/")
INJECT_TARGET = os.environ.get("LOCAL_LLM_INJECT_TARGET", "opencode")
```

Keep a temporary fallback to `OPENWEBUI_BASE_URL` only if existing deployed configs need it. If kept, document it as deprecated and add a test that generic env wins.

**Step 3: Rename proxy helper references**

Replace variable/function names and user-facing messages that say Open WebUI when they mean generic browser upstream.

**Step 4: Verify**

Run: `python3 -m py_compile scripts/local-llm-switcher.py && ./test_oc_local.sh`

Expected: PASS.

### Task 3: Add OpenCode Injection Mode

**Files:**
- Modify: `scripts/local-llm-switcher.py`
- Modify: `test_oc_local.sh`

**Step 1: Add focused HTML injection test**

Add a small Python-driven test in `test_oc_local.sh` or a helper fixture that imports/executes the injection function if available. If current injection is not factored, first extract a pure function:

```python
def inject_switcher_widget(body: bytes, content_type: str, target: str) -> bytes:
    ...
```

Test OpenCode-like HTML:

```html
<!doctype html><html><head></head><body><div id="root"></div><script src="/assets/app.js"></script></body></html>
```

Expected: output contains `id="local-llm-switcher"` or the existing pill marker before `</body>`.

**Step 2: Preserve existing generic HTML injection**

The injection should not depend on Open WebUI-specific DOM IDs. It should inject before `</body>` for HTML responses from OpenCode.

**Step 3: Make target explicit**

Support:

```text
LOCAL_LLM_INJECT_TARGET=opencode
LOCAL_LLM_INJECT_TARGET=none
```

`none` disables injection but keeps APIs available.

**Step 4: Verify**

Run: `python3 -m py_compile scripts/local-llm-switcher.py && ./test_oc_local.sh`.

### Task 4: Update Caddy To Slot OpenCode Into The Same Web Port

**Files:**
- Modify: `scripts/Caddyfile.local-llm`
- Modify: `README.md`
- Modify: `test_oc_local.sh`

**Step 1: Test generic upstream comments/config**

Assert Caddy no longer documents Open WebUI-specific routing as default:

```bash
caddyfile_contents="$(<"$repo_root/scripts/Caddyfile.local-llm")"
assert_contains "$caddyfile_contents" "OpenCode web upstream"
assert_not_contains "$caddyfile_contents" "open-webui"
```

**Step 2: Keep same slot behavior**

The Caddy file should still expose:

```text
:3001
/api/local-llm/* -> 127.0.0.1:3003
/_switcher -> 127.0.0.1:3003
everything else -> switcher proxy/injection service or OpenCode upstream
```

The easiest slot-in shape is:

```caddyfile
:3001 {
  handle /api/local-llm/* { reverse_proxy 127.0.0.1:3003 }
  handle /_switcher { reverse_proxy 127.0.0.1:3003 }
  handle { reverse_proxy 127.0.0.1:3003 }
}
```

Then `local-llm-switcher.py` proxies OpenCode upstream and injects the pill.

**Step 3: Verify**

Run: `./test_oc_local.sh`.

### Task 5: Add OpenCode Web Service Template

**Files:**
- Create: `scripts/opencode-web.service`
- Modify: `README.md`
- Modify: `test_oc_local.sh`

**Step 1: Add test for service template**

```bash
assert_contains "$(<"$repo_root/scripts/opencode-web.service")" "ExecStart="
assert_contains "$(<"$repo_root/scripts/opencode-web.service")" "127.0.0.1"
```

**Step 2: Add minimal user systemd unit**

Use the existing OpenCode web command as configured on the machine. Since the user wants “same as it is now,” make the unit configurable:

```ini
[Unit]
Description=OpenCode web frontend

[Service]
Environment=OPENCODE_WEB_HOST=127.0.0.1
Environment=OPENCODE_WEB_PORT=3002
EnvironmentFile=%h/.config/local_llm/opencode-web.env
ExecStart=/bin/sh -lc 'exec ${OPENCODE_WEB_COMMAND}'
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
```

Example env file:

```bash
OPENCODE_WEB_COMMAND='opencode serve --host 127.0.0.1 --port 3002'
```

Adjust command to the real OpenCode web command during implementation if known.

**Step 3: Verify syntax**

Run: `systemd-analyze verify scripts/opencode-web.service` if available, otherwise assert file content only in tests.

### Task 6: Remove Open WebUI From Default README Path

**Files:**
- Modify: `README.md`
- Modify: `test_oc_local.sh`

**Step 1: Rewrite architecture section**

Default browser stack should be:

```text
Cloudflare Access -> Caddy :3001 -> local-llm-switcher :3003 -> OpenCode web :3002
                                                  -> llama-server :8080
```

**Step 2: Move Open WebUI to optional legacy section**

Add a short section:

```markdown
## Optional Legacy: Open WebUI

Open WebUI is no longer the default browser UI. Use it only if you want its chat/RAG interface. The switcher pill target is OpenCode by default.
```

**Step 3: Update Cloudflare text**

The public hostname points at Caddy, which proxies OpenCode web and switcher APIs. Do not mention Open WebUI as the default public app.

**Step 4: Verify**

Run: `./test_oc_local.sh`.

### Task 7: Update Deployment Preview

**Files:**
- Modify: `scripts/model-manager.sh`
- Modify: `test_oc_local.sh`

**Step 1: Add expected deploy plan text**

Deploy dry-run should mention OpenCode support files instead of Open WebUI support files:

```bash
assert_contains "$deploy_output" "opencode-web.service"
assert_contains "$deploy_output" "LOCAL_LLM_WEB_UPSTREAM"
assert_not_contains "$deploy_output" "open-webui"
```

**Step 2: Update deploy dry-run support file list**

Include:

- `scripts/local-llm-switcher.py`
- `scripts/local-llm-switcher.service`
- `scripts/opencode-web.service`
- `scripts/Caddyfile.local-llm`
- generated launchers

**Step 3: Verify**

Run: `./test_oc_local.sh`.

### Task 8: End-To-End Local Smoke Test

**Files:**
- Modify: `README.md`
- Modify: `test_oc_local.sh`

**Step 1: Document manual smoke**

Add commands:

```bash
ssh "$MODEL_HOST" 'systemctl --user status opencode-web.service local-llm-switcher.service'
curl -fsS http://127.0.0.1:3001/_switcher
curl -fsS http://127.0.0.1:3001/api/local-llm/models
```

**Step 2: Full verification**

Run:

```bash
bash -n install.sh installer.sh scripts/*.sh test_oc_local.sh
shellcheck install.sh installer.sh scripts/*.sh test_oc_local.sh
python3 -m py_compile scripts/*.py
./test_oc_local.sh
```

Expected: all pass.

**Step 3: Commit**

```bash
git add README.md test_oc_local.sh scripts/local-llm-switcher.py scripts/Caddyfile.local-llm scripts/opencode-web.service scripts/model-manager.sh
git commit -m "feat: make opencode web the primary UI"
```
