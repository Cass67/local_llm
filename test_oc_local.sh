#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
script="${OC_LOCAL_SCRIPT:-$repo_root/scripts/oc-local}"

run_dry() {
  "$script" --dry-run "$@"
}

run_info() {
  "$script" --info "$@"
}

assert_contains() {
  local haystack="$1"
  local needle="$2"
  if [[ "$haystack" != *"$needle"* ]]; then
    printf 'expected output to contain %q\noutput was:\n%s\n' "$needle" "$haystack" >&2
    return 1
  fi
}

assert_not_contains() {
  local haystack="$1"
  local needle="$2"
  if [[ "$haystack" == *"$needle"* ]]; then
    printf 'expected output not to contain %q\noutput was:\n%s\n' "$needle" "$haystack" >&2
    return 1
  fi
}

assert_line() {
  local haystack="$1"
  local expected_line="$2"
  if ! grep -qxF -- "$expected_line" <<<"$haystack"; then
    printf 'expected output to contain exact line %q\noutput was:\n%s\n' "$expected_line" "$haystack" >&2
    return 1
  fi
}

line_number_for() {
  local haystack="$1"
  local marker="$2"
  local line=''
  line="$(grep -nF -- "$marker" <<<"$haystack" | cut -d: -f1 | head -n 1 || true)"
  if [[ -z "$line" ]]; then
    printf 'expected output to contain marker %q for order check\noutput was:\n%s\n' "$marker" "$haystack" >&2
    return 1
  fi
  printf '%s\n' "$line"
}

help_output="$($script --help 2>&1)"
assert_contains "$help_output" "oc-local [family] [profile]"
assert_contains "$help_output" "--remote HOST"
assert_contains "$help_output" "--user USER"
assert_contains "$help_output" "-k"
assert_not_contains "$help_output" "speed     32k context"
assert_not_contains "$help_output" "tiny      40k context"
readme_contents="$(<"$repo_root/README.md")"
readme_default_install_section="${readme_contents%%## Optional Legacy: Open WebUI*}"
caddyfile_contents="$(<"$repo_root/scripts/Caddyfile.local-llm")"
switcher_service_contents="$(<"$repo_root/scripts/local-llm-switcher.service")"
opencode_web_service_contents="$(<"$repo_root/scripts/opencode-web.service")"
model_manager_contents="$(<"$repo_root/scripts/model-manager.sh")"
model_discovery_contents="$(<"$repo_root/scripts/model-discovery.sh")"
oc_local_contents="$(<"$repo_root/scripts/oc-local")"
tracked_start_scripts="$(git -C "$repo_root" ls-files 'scripts/start*.sh')"
if [[ -n "$tracked_start_scripts" ]]; then
  printf 'expected no tracked scripts/start*.sh launchers, but found:\n%s\n' "$tracked_start_scripts" >&2
  exit 1
fi
assert_contains "$oc_local_contents" "tail -80 \$remote_dir/model.log"
assert_not_contains "$oc_local_contents" "llama-\${remote_profile}.log"
assert_contains "$readme_contents" "Fresh pull workflow"
assert_contains "$readme_contents" "\`local_llm\` is a bootstrap engine"
assert_contains "$readme_contents" "./install.sh"
assert_contains "$readme_contents" "OpenCode web is the primary browser UI"
assert_contains "$readme_contents" "Cloudflare Access -> Caddy :3001 -> local-llm-switcher :3003 -> OpenCode web :3002 -> llama-server :8080"
assert_contains "$readme_contents" "## Optional Legacy: Open WebUI"
assert_contains "$readme_contents" "Open WebUI is no longer the default browser UI. Use it only if you want its chat/RAG interface. The switcher pill target is OpenCode by default."
assert_contains "$readme_contents" "injectable OpenCode web browser routes to the switcher on"
assert_contains "$readme_contents" "WebSocket upgrade routes such as"
assert_contains "$readme_contents" "bypass injection and go directly to the OpenCode web upstream"
assert_contains "$readme_contents" "The switcher proxies OpenCode web upstream"
assert_contains "$readme_contents" "LOCAL_LLM_WEB_UPSTREAM=http://127.0.0.1:3002"
assert_contains "$readme_contents" "\`OPENWEBUI_BASE_URL\` is deprecated"
assert_contains "$readme_contents" "\`LOCAL_LLM_WEB_UPSTREAM\` wins"
assert_contains "$readme_contents" "LOCAL_LLM_INJECT_TARGET=opencode"
assert_contains "$readme_contents" "Open WebUI is optional legacy"
assert_not_contains "$readme_default_install_section" "scp docker-compose.yml"
assert_not_contains "$readme_default_install_section" "docker compose up -d"
assert_contains "$readme_default_install_section" "run-local-llm-caddy-container.sh"
assert_not_contains "$readme_contents" "The public Open WebUI path uses"
assert_not_contains "$readme_contents" "Open WebUI application and SQLite data volume"
assert_not_contains "$readme_contents" "public Open WebUI path"
assert_not_contains "$readme_contents" "Caddy routes Open WebUI API/assets"
assert_not_contains "$readme_contents" "Open WebUI listens"
assert_not_contains "$readme_contents" "Open WebUI selected-model DB sync"
assert_contains "$switcher_service_contents" "Description=Local LLM OpenCode Web Switcher Proxy"
assert_contains "$switcher_service_contents" "EnvironmentFile=-%h/.config/local_llm/local-llm-switcher.env"
assert_contains "$switcher_service_contents" "\$\${LLAMA_DIR:?set LLAMA_DIR in ~/.config/local_llm/local-llm-switcher.env}"
assert_contains "$switcher_service_contents" "\$\$LLAMA_DIR/local-llm-switcher.py"
assert_not_contains "$switcher_service_contents" "OPENWEBUI_BASE_URL"
assert_contains "$opencode_web_service_contents" "Description=OpenCode web frontend"
assert_contains "$opencode_web_service_contents" "127.0.0.1"
assert_contains "$opencode_web_service_contents" "OPENCODE_WEB_COMMAND"
assert_contains "$opencode_web_service_contents" "EnvironmentFile=%h/.config/local_llm/opencode-web.env"
assert_contains "$opencode_web_service_contents" "ExecStart=/bin/sh -lc 'exec \$\${OPENCODE_WEB_COMMAND:?set OPENCODE_WEB_COMMAND in ~/.config/local_llm/opencode-web.env}'"
assert_contains "$opencode_web_service_contents" "RestartSec=3"
assert_contains "$caddyfile_contents" "OpenCode web upstream"
assert_contains "$caddyfile_contents" ":3001"
assert_contains "$caddyfile_contents" "handle /api/local-llm/*"
assert_contains "$caddyfile_contents" "handle /_switcher"
assert_contains "$caddyfile_contents" "reverse_proxy 127.0.0.1:3003"
assert_contains "$caddyfile_contents" "OpenCode WebSocket upgrades bypass injection"
assert_contains "$caddyfile_contents" "handle /ws/*"
assert_contains "$caddyfile_contents" "handle /socket.io/*"
assert_contains "$caddyfile_contents" "handle /pty/*/connect"
assert_contains "$caddyfile_contents" $'handle /pty/*/connect {\n\t\treverse_proxy 127.0.0.1:3002'
assert_contains "$caddyfile_contents" "reverse_proxy 127.0.0.1:3002"
assert_not_contains "$caddyfile_contents" "open-webui"
assert_not_contains "$caddyfile_contents" "handle /_app/*"
assert_not_contains "$caddyfile_contents" "handle /ollama/*"
ws_route_line="$(line_number_for "$caddyfile_contents" "handle /ws/*")"
socketio_route_line="$(line_number_for "$caddyfile_contents" "handle /socket.io/*")"
pty_route_line="$(line_number_for "$caddyfile_contents" "handle /pty/*/connect")"
catch_all_route_line="$(line_number_for "$caddyfile_contents" "handle {")"
if ((ws_route_line >= catch_all_route_line || socketio_route_line >= catch_all_route_line || pty_route_line >= catch_all_route_line)); then
  printf 'expected OpenCode WebSocket routes to appear before catch-all route\n' >&2
  exit 1
fi
if [[ ! -f "$repo_root/install.sh" ]]; then
  printf 'expected install.sh wrapper to exist\n' >&2
  exit 1
fi
if [[ ! -x "$repo_root/install.sh" ]]; then
  printf 'expected install.sh wrapper to be executable\n' >&2
  exit 1
fi
bash -n "$repo_root/install.sh"
assert_line "$readme_contents" "model-manager bootstrap --target remote:<host> --dry-run"
assert_line "$readme_contents" "model-manager bootstrap --target remote:<host> --yes"
assert_contains "$readme_contents" "model-manager discover \"coding gguf\" --target remote:<host>"
assert_contains "$readme_contents" "model-manager benchmark <source> --target remote:<host> --full"
assert_contains "$readme_contents" "model-manager accept <benchmark.json>"
assert_contains "$readme_contents" "model-manager deploy --target remote:<host> --dry-run"
assert_contains "$readme_contents" "model-manager export > local-llm-backup.json"
assert_not_contains "$readme_contents" "scripts/start3.sh"
assert_not_contains "$readme_contents" "Recommended Choices"
assert_not_contains "$readme_contents" "Qwen dense-thinking comparison"
assert_not_contains "$readme_contents" "oc-qwen-reliable"
assert_not_contains "$readme_contents" "oc-gemma-reliable"
assert_not_contains "$readme_contents" "oc-gpt-oss"
assert_not_contains "$readme_contents" "\`local_llm\` is a small operations repo"
assert_contains "$readme_contents" "## Features"
assert_contains "$readme_contents" "## Test A Fresh Checkout"
assert_contains "$readme_contents" "LOCAL_LLM_BIN_DIR=\"\$tmp/bin\" LOCAL_LLM_SHARE_DIR=\"\$tmp/share\" ./install.sh"
assert_contains "$readme_contents" "LOCAL_LLM_RUNS_DIR=\"\$tmp/share/runs\" model-manager list"
assert_contains "$readme_contents" "git ls-files 'scripts/start*.sh'"
assert_contains "$readme_contents" "Expected: no output."
assert_contains "$readme_contents" "oc-local qwen reliable --info"
assert_contains "$readme_contents" "Expected: fails with guidance until you accept a model."
assert_contains "$readme_contents" "## Architecture"
assert_contains "$readme_contents" "## Install Guide"
assert_contains "$readme_contents" "docs/assets/local-llm-architecture.svg"
assert_not_contains "$readme_contents" "docs/assets/open-webui-switcher-pill.svg"
assert_contains "$readme_contents" "Cloudflare is the public security boundary"
assert_contains "$readme_contents" "Cloudflare Access login and policy check"
assert_contains "$readme_contents" "Do not commit Cloudflare credentials"
expected_cloudflared_install="Install \`cloudflared\` on Ubuntu 26"
assert_contains "$readme_contents" "$expected_cloudflared_install"
assert_contains "$readme_contents" "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main"
assert_contains "$readme_contents" "cloudflared tunnel login"
assert_contains "$readme_contents" "cloudflared tunnel route dns local-llm"
assert_contains "$readme_contents" "sudo systemctl enable --now cloudflared"
assert_contains "$readme_contents" "service: http://localhost:3001"
assert_contains "$readme_contents" "MODEL_HOST=gpu-box.example.lan"
assert_contains "$readme_contents" "MODEL_API_BASE=http://gpu-box.example.lan:8080/v1"
assert_not_contains "$readme_default_install_section" "LOCAL_LLM_CADDYFILE=./Caddyfile.local-llm docker compose up -d"
assert_not_contains "$readme_default_install_section" "scp docker-compose.yml \"\$MODEL_HOST:\$REMOTE_DIR/docker-compose.yml\""
assert_contains "$readme_contents" "The repo's \`docker-compose.yml\` is the legacy Open WebUI compose file."
assert_contains "$readme_contents" "Do not copy or run it for the default OpenCode web setup"
assert_not_contains "$readme_contents" "not the responsive daily driver"
assert_not_contains "$readme_contents" "Qwen 35B defaults are vision-enabled"
assert_not_contains "$readme_contents" "Quant, KV Q4/Q5, and MMQ changes remain future benchmark/promotion work"
assert_contains "$readme_contents" "## Helper Tools"
assert_contains "$readme_contents" "hardware-analyzer reports the machine it runs on"
assert_contains "$readme_contents" "model-discovery --detailed"
assert_contains "$readme_contents" "model-manager discover"
assert_contains "$readme_contents" "model-manager export > local-llm-backup.json"
assert_contains "$readme_contents" "model-manager restore local-llm-backup.json"
assert_contains "$readme_contents" "model-manager deploy --target \"remote:\$MODEL_HOST\" --dry-run"
assert_contains "$readme_contents" "oc-local <family> <profile> --info"
assert_contains "$readme_contents" "The client machine runs OpenCode"
assert_contains "$readme_contents" "Run from this repo on the client machine"
assert_contains "$readme_contents" "tested from a macOS client and expected to work from Linux clients"
assert_not_contains "$readme_contents" "The Mac runs OpenCode"
assert_not_contains "$readme_contents" "so the Mac can drive models"
assert_not_contains "$readme_contents" "Run from this repo on the Mac"
assert_not_contains "$readme_contents" "On the Mac, it reports"
assert_contains "$readme_contents" "model-manager update --target \"remote:\$MODEL_HOST\" --dry-run"
assert_contains "$readme_contents" "model-manager replace <old-file> <new-repo> --target \"remote:\$MODEL_HOST\" --dry-run"
assert_contains "$readme_contents" "Readable inventory"
assert_contains "$readme_contents" "source: Hugging Face repo or local profile source"
assert_contains "$readme_contents" "file: selected GGUF file or quant"
assert_contains "$readme_contents" "Accepting a benchmark records accepted metadata and generated launchers under \`\$HOME/.local/share/local_llm\` / \`runs\`."
assert_contains "$readme_contents" "model-manager deploy --target remote:<host> --dry-run\` previews the generated launchers and switcher/service files"
assert_contains "$readme_contents" "it does not copy files yet"
assert_contains "$readme_contents" "Do not enable \`llama-server.service\` from a fresh checkout until generated launcher state has been manually copied from the deploy preview plan."
assert_contains "$readme_contents" "Server service and OpenCode web wiring are still a later/manual setup step."
assert_not_contains "$readme_contents" "systemctl --user enable --now llama-server.service"
assert_not_contains "$readme_contents" "Deployment and switcher wiring happen later through the generated/deploy workflow."
assert_not_contains "$readme_contents" "Accepting a benchmark promotes the model"
assert_not_contains "$readme_contents" "creates or reuses a \`scripts/startN.sh\` launcher"
assert_not_contains "$readme_contents" "updates the Open WebUI switcher allowlist"
assert_contains "$readme_contents" "fall back to a Python stdlib downloader"
assert_not_contains "$readme_contents" "It currently creates the launcher only"
assert_not_contains "$readme_contents" "manual promotion step"
assert_contains "$readme_contents" "update-manager is a compatibility helper"
assert_contains "$readme_contents" "update-manager --candidates"
assert_not_contains "$readme_contents" "for family in qwen qwen-27b qwen-coder qwen-coder-next gemma gpt-oss deepseek-r1 qwen-opus qwen-heretic; do"
assert_not_contains "$readme_contents" "scripts/start14.sh scripts/start15.sh scripts/run-current-model.sh"
assert_not_contains "$model_manager_contents" "qwen-hauhau"
assert_not_contains "$model_manager_contents" "qwen-27b-hauhau"
assert_not_contains "$model_manager_contents" "qwen-heretic"
assert_not_contains "$model_discovery_contents" "Qwen3.6-35B-A3B"
assert_not_contains "$model_discovery_contents" "Gemma-4-31B-it"
assert_contains "$model_discovery_contents" 'OC_LOCAL_HF_FETCH_LIMIT:-100'
assert_not_contains "$model_discovery_contents" "gpt-oss-20B"
assert_contains "$readme_contents" "shellcheck install.sh installer.sh scripts/model-discovery.sh scripts/model-manager.sh scripts/oc-local scripts/update-manager.sh test_oc_local.sh scripts/bench-installed-kv-remote.sh scripts/bench-mtp-remote.sh scripts/run-current-model.sh scripts/run-local-llm-caddy-container.sh"
assert_contains "$readme_contents" "systemctl --user restart llama-server.service"
assert_contains "$readme_contents" "run-current-model.sh"
assert_contains "$readme_contents" "REMOTE_SCRIPT=<generated-launcher>"
assert_not_contains "$readme_contents" 'localllm/qwen3.6-35b-a3b-mtp'
assert_not_contains "$readme_contents" "scripts/start11.sh scripts/start12.sh scripts/start14.sh"
assert_not_contains "$readme_contents" "scripts/start15.sh scripts/run-current-model.sh"
assert_contains "$readme_contents" "ssh \"\$MODEL_HOST\" 'systemctl --user restart llama-server.service'"
assert_contains "$readme_contents" "ssh \"\$MODEL_HOST\" 'journalctl --user -u llama-server.service -n 160 --no-pager'"
assert_contains "$readme_contents" "OpenCode web listens on http://127.0.0.1:3002"
assert_contains "$readme_contents" "%h/.config/local_llm/opencode-web.env"
assert_contains "$readme_contents" "OPENCODE_WEB_COMMAND='<replace-with-your-opencode-web-command> --host 127.0.0.1 --port 3002'"
assert_contains "$readme_contents" "Adapt the example command to your OpenCode web installation, but keep an explicit bind address of 127.0.0.1 and port 3002 in OPENCODE_WEB_COMMAND."
assert_contains "$readme_contents" "The environment file is required; create it before enabling \`opencode-web.service\`."
assert_contains "$readme_contents" "The exact OpenCode web command may vary"
assert_contains "$readme_contents" "Caddy listens on http://127.0.0.1:3001"
assert_contains "$readme_contents" "local-llm-switcher listens on http://127.0.0.1:3003"
assert_contains "$readme_contents" "Cloudflare stays pointed at port 3001"
assert_contains "$readme_contents" "local-llm-caddy"
assert_contains "$readme_contents" "run-local-llm-caddy-container.sh"
assert_contains "$readme_contents" "Caddyfile.local-llm"
assert_contains "$readme_contents" "open-webui"
assert_contains "$readme_contents" "Caddy routes all other OpenCode web browser traffic to the switcher."
assert_contains "$readme_contents" "Caddy routes WebSocket upgrade paths such as"
assert_contains "$readme_contents" "/pty/*/connect"
assert_contains "$readme_contents" "directly to OpenCode web on http://127.0.0.1:3002 so they bypass injection."
assert_contains "$readme_contents" "The switcher proxies OpenCode web upstream"
assert_contains "$readme_contents" "## Experimental Vulkan Split"
assert_contains "$readme_contents" "GGML_VK_VISIBLE_DEVICES=0,1"
assert_contains "$readme_contents" "--split-mode layer"
assert_contains "$readme_contents" "--tensor-split 20,24"
assert_contains "$readme_contents" "20,24"
assert_contains "$readme_contents" "22,22"
assert_contains "$readme_contents" "24,20"
assert_contains "$readme_contents" "28,16"
assert_contains "$readme_contents" "32,12"
assert_contains "$readme_contents" "36,8"
assert_contains "$readme_contents" "local-llm-caddy"
assert_contains "$readme_contents" "ssh \"\$MODEL_HOST\" 'systemctl --user status opencode-web.service local-llm-switcher.service'"
assert_contains "$readme_contents" "ssh \"\$MODEL_HOST\" 'curl -fsS http://127.0.0.1:3001/_switcher'"
assert_contains "$readme_contents" "ssh \"\$MODEL_HOST\" 'curl -fsS http://127.0.0.1:3001/api/local-llm/models'"
assert_contains "$readme_contents" "caddy validate"
assert_contains "$readme_contents" "systemd-analyze"
assert_not_contains "$readme_contents" "docker ps --filter name=open-webui"
assert_not_contains "$readme_contents" "docker logs open-webui"
assert_contains "$readme_contents" "systemctl --user restart opencode-web.service local-llm-switcher.service llama-server.service"
assert_not_contains "$readme_contents" "docker restart open-webui"
assert_not_contains "$readme_contents" "docker run -d --name open-webui"
if grep -Eq 'docker[[:space:]]+run.*open-webui' <<<"$readme_contents"; then
  printf 'expected README not to document docker run commands for Open WebUI\n' >&2
  exit 1
fi
assert_contains "$readme_contents" "reports the expected alias"
assert_contains "$readme_contents" "optional legacy upstream"
assert_contains "$readme_contents" "fresh OpenCode web pane"
assert_contains "$readme_contents" "Model Workflow"
assert_contains "$readme_contents" "model-manager select"
assert_contains "$readme_contents" "docs/benchmarks/"
assert_contains "$readme_contents" "docs/plans/"
assert_contains "$readme_contents" "docs/superpowers/"
if ! grep -qxF '/docs/plans/' "$repo_root/.gitignore"; then
  printf 'expected .gitignore to ignore /docs/plans/\n' >&2
  exit 1
fi
if ! grep -qxF '/docs/superpowers/' "$repo_root/.gitignore"; then
  printf 'expected .gitignore to ignore /docs/superpowers/\n' >&2
  exit 1
fi
switcher_contents="$(<"$repo_root/scripts/local-llm-switcher.py")"
assert_contains "$switcher_contents" "LOCAL_LLM_WEB_UPSTREAM"
assert_contains "$switcher_contents" "LOCAL_LLM_INJECT_TARGET"
assert_contains "$switcher_contents" "LOCAL_LLM_SYNC_OPENWEBUI"
python3 - "$repo_root/scripts/local-llm-switcher.py" <<'PY'
import importlib.util
import os
import sys

script_path = sys.argv[1]


def load_with_name(module_name):
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise SystemExit("failed to load switcher module spec")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


os.environ["LOCAL_LLM_INJECT_TARGET"] = "unexpected"
try:
    load_with_name("local_llm_switcher_invalid_target")
except ValueError as exc:
    if "LOCAL_LLM_INJECT_TARGET" not in str(exc):
        raise SystemExit(f"expected invalid target error to name env var: {exc}")
else:
    raise SystemExit("expected invalid LOCAL_LLM_INJECT_TARGET to fail at import")

os.environ["LOCAL_LLM_WEB_UPSTREAM"] = "http://generic.example:3002/"
os.environ["OPENWEBUI_BASE_URL"] = "http://deprecated.example:3002/"
os.environ.pop("LOCAL_LLM_INJECT_TARGET", None)
module = load_with_name("local_llm_switcher")
if module.WEB_UPSTREAM != "http://generic.example:3002":
    raise SystemExit(f"expected LOCAL_LLM_WEB_UPSTREAM to win: {module.WEB_UPSTREAM!r}")
if module.INJECT_TARGET != "opencode":
    raise SystemExit(f"expected default LOCAL_LLM_INJECT_TARGET opencode: {module.INJECT_TARGET!r}")
if module.SYNC_OPENWEBUI:
    raise SystemExit("expected LOCAL_LLM_SYNC_OPENWEBUI to default false")
html_body = b"<html><body><main>app</main></body></html>"
opencode_body = (
    b'<!doctype html><html><head></head><body><div id="root"></div>'
    b'<script src="/assets/app.js"></script></body></html>'
)
injected = module.inject_switcher_widget(opencode_body, "text/html; charset=utf-8", "opencode")
if b'id="local-llm-switcher"' not in injected:
    raise SystemExit("expected OpenCode-like HTML to add switcher widget")
if injected.rfind(b'id="local-llm-switcher"') > injected.lower().rfind(b"</body>"):
    raise SystemExit("expected switcher widget before closing body tag")
already_injected = b'<html><body><div id="local-llm-switcher"></div></body></html>'
if module.inject_switcher_widget(already_injected, "text/html", "opencode") != already_injected:
    raise SystemExit("expected existing switcher marker to skip duplicate injection")
if module.inject_switcher_widget(opencode_body, "text/html", "none") != opencode_body:
    raise SystemExit("expected target none to skip widget injection")
if module.should_rewrite_html_response("GET", "text/html", "none"):
    raise SystemExit("expected target none to skip HTML rewrite path")
if not module.should_rewrite_html_response("GET", "text/html", "opencode"):
    raise SystemExit("expected opencode HTML GET to use rewrite path")
if module.should_rewrite_html_response("HEAD", "text/html", "opencode"):
    raise SystemExit("expected HEAD to skip HTML rewrite path")
if module.should_rewrite_html_response("GET", "application/json", "opencode"):
    raise SystemExit("expected non-HTML content to skip rewrite path")
json_body = b'{"html":"<body></body>"}'
if module.inject_switcher_widget(json_body, "application/json", "opencode") != json_body:
    raise SystemExit("expected non-HTML content to remain unchanged")
if b"local-llm-switcher" not in module.inject_widget(html_body, "text/html; charset=utf-8"):
    raise SystemExit("expected default injection to add switcher widget")
module.INJECT_TARGET = "none"
if module.inject_widget(html_body, "text/html; charset=utf-8") != html_body:
    raise SystemExit("expected LOCAL_LLM_INJECT_TARGET=none to skip widget injection")
module.INJECT_TARGET = "opencode"
if b"local-llm-switcher" not in module.inject_widget(html_body, "text/html; charset=utf-8"):
    raise SystemExit("expected LOCAL_LLM_INJECT_TARGET=opencode to inject widget")
PY
python3 - "$repo_root/scripts/local-llm-switcher.py" <<'PY'
import importlib.util
import os
import sys
import tempfile
from pathlib import Path

script_path = sys.argv[1]


def load_switcher(sync_openwebui=None):
    if sync_openwebui is None:
        os.environ.pop("LOCAL_LLM_SYNC_OPENWEBUI", None)
    else:
        os.environ["LOCAL_LLM_SYNC_OPENWEBUI"] = sync_openwebui
    spec = importlib.util.spec_from_file_location("local_llm_switcher", script_path)
    if spec is None or spec.loader is None:
        raise SystemExit("failed to load switcher module spec")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def exercise_switch(module):
    with tempfile.TemporaryDirectory() as tmp:
        launcher = Path(tmp) / "run-model.sh"
        launcher.write_text("#!/bin/sh\n", encoding="utf-8")
        launcher.chmod(0o755)
        module.LLAMA_DIR = Path(tmp)
        module.CURRENT_MODEL_ENV = Path(tmp) / "current-model.env"
        model = module.Model("qwen", "run-model.sh", "oc-qwen", "Qwen")
        module.MODELS = [model]
        module.MODELS_BY_ID = {model.id: model}
        module.restart_llama_server = lambda: None
        module.wait_for_alias = lambda alias, timeout: alias == model.alias
        calls = []
        module.sync_openwebui_selected_model = lambda alias: calls.append(alias) or {"alias": alias}
        return module.switch_to_model(model.id), calls


default_module = load_switcher()
payload, calls = exercise_switch(default_module)
if calls:
    raise SystemExit(f"expected default switch to skip Open WebUI sync, got {calls!r}")
if "openwebui" in payload:
    raise SystemExit(f"expected default switch payload to omit openwebui: {payload!r}")

enabled_module = load_switcher("true")
payload, calls = exercise_switch(enabled_module)
if calls != ["oc-qwen"]:
    raise SystemExit(f"expected enabled switch to sync Open WebUI once, got {calls!r}")
if payload.get("openwebui", {}).get("alias") != "oc-qwen":
    raise SystemExit(f"expected enabled switch payload to include Open WebUI sync: {payload!r}")
PY
assert_contains "$switcher_contents" "@media (max-width: 640px)"
assert_contains "$switcher_contents" "@media (hover: none), (pointer: coarse), (max-width: 900px)"
assert_contains "$switcher_contents" "local-llm-switcher-toggle"
assert_contains "$switcher_contents" "local-llm-switcher-panel"
assert_contains "$switcher_contents" "MODELS: list[Model] = []"
assert_contains "$switcher_contents" "No local models configured"
assert_not_contains "$switcher_contents" "Qwen Coder Next"
default_llama_dir="${HOME/#$HOME/~}/llama.cpp"
assert_contains "$switcher_contents" "$default_llama_dir"
assert_contains "$switcher_contents" "bottom: max(96px, env(safe-area-inset-bottom))"
assert_contains "$switcher_contents" "border-radius: 999px"
assert_contains "$switcher_contents" "position: absolute"
assert_contains "$switcher_contents" "bottom: calc(100% + 8px)"
assert_contains "$switcher_contents" "right: 0"
assert_contains "$switcher_contents" '"cache-control"'
assert_contains "$switcher_contents" '"if-none-match"'
assert_contains "$switcher_contents" "no-store"
assert_not_contains "$switcher_contents" "top: 50%"
assert_not_contains "$switcher_contents" "top: 12px"
assert_not_contains "$switcher_contents" "bottom: 16px"
assert_contains "$readme_contents" "without prompting"
assert_contains "$readme_contents" "GET /api/local-llm/models"
assert_contains "$readme_contents" "GET /api/local-llm/current"
assert_contains "$readme_contents" "POST /api/local-llm/switch"
assert_contains "$readme_contents" "GET /_switcher"
assert_line "$readme_contents" "ssh \"\$MODEL_HOST\" 'systemctl --user status opencode-web.service local-llm-switcher.service'"
assert_line "$readme_contents" "ssh \"\$MODEL_HOST\" 'curl -fsS http://127.0.0.1:3001/_switcher'"
assert_line "$readme_contents" "ssh \"\$MODEL_HOST\" 'curl -fsS http://127.0.0.1:3001/api/local-llm/models'"
assert_line "$readme_contents" "bash -n install.sh installer.sh scripts/model-discovery.sh scripts/model-manager.sh scripts/oc-local scripts/update-manager.sh test_oc_local.sh scripts/bench-installed-kv-remote.sh scripts/bench-mtp-remote.sh scripts/run-current-model.sh scripts/run-local-llm-caddy-container.sh"
assert_line "$readme_contents" "shellcheck install.sh installer.sh scripts/model-discovery.sh scripts/model-manager.sh scripts/oc-local scripts/update-manager.sh test_oc_local.sh scripts/bench-installed-kv-remote.sh scripts/bench-mtp-remote.sh scripts/run-current-model.sh scripts/run-local-llm-caddy-container.sh"
assert_line "$readme_contents" "python3 -m py_compile scripts/*.py"
assert_line "$readme_contents" "./test_oc_local.sh"
assert_contains "$readme_contents" "systemctl --user restart opencode-web.service local-llm-switcher.service llama-server.service"
assert_contains "$readme_contents" "systemctl --user status opencode-web.service local-llm-switcher.service llama-server.service"
assert_contains "$readme_contents" "journalctl --user -u opencode-web.service -u local-llm-switcher.service -u llama-server.service"
assert_not_contains "$readme_contents" "docker ps --filter name=open-webui"
assert_contains "$readme_contents" "--remote"
assert_not_contains "$readme_contents" "--target local"
assert_contains "$readme_contents" "--target remote:<host>"
assert_not_contains "$readme_contents" "OC_LOCAL_TARGET"
assert_not_contains "$readme_contents" "OC_LOCAL_LLAMA_DIR"
gitignore_contents="$(<"$repo_root/.gitignore")"
if ! grep -qxF '/runs/' <<<"$gitignore_contents"; then
  printf 'expected .gitignore to contain active exact line /runs/\n.gitignore was:\n%s\n' "$gitignore_contents" >&2
  exit 1
fi

model_discovery_output="$(OC_LOCAL_HF_FIXTURE="$repo_root/testdata/huggingface-model-search.json" OC_LOCAL_REMOTE_HOST=__none__ "$repo_root/scripts/model-discovery.sh" --limit 12)"
assert_contains "$model_discovery_output" "Model Discovery Results:"
assert_contains "$model_discovery_output" "Hardware source: local"
assert_contains "$model_discovery_output" "GPU:"
assert_contains "$model_discovery_output" "VRAM:"
assert_contains "$model_discovery_output" "ROCm target:"
assert_contains "$model_discovery_output" "Hugging Face GGUF Candidates"
assert_contains "$model_discovery_output" "unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF"
assert_contains "$model_discovery_output" "TargetOrg/Target-16B-GGUF | purpose=chat | class=target"
assert_contains "$model_discovery_output" "HugeOrg/Huge-80B-GGUF | purpose=reasoning | class=huge"
assert_contains "$model_discovery_output" "HugeOrg/Huge-405B-A22B-GGUF | purpose=reasoning | class=huge"
assert_contains "$model_discovery_output" "class=target"
assert_contains "$model_discovery_output" "class=small"
assert_contains "$model_discovery_output" "class=huge"
assert_contains "$model_discovery_output" "class=unknown"
assert_contains "$model_discovery_output" "Already Tuned Profiles"
assert_contains "$model_discovery_output" "None"
assert_not_contains "$model_discovery_output" "oc-qwen-reliable --lean"
assert_not_contains "$model_discovery_output" "example/not-a-gguf-model"
assert_not_contains "$model_discovery_output" "not a Hugging Face search"
assert_not_contains "$model_discovery_output" "Recommended models:"
qwen_target_line="$(line_number_for "$model_discovery_output" "unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF")"
tiny_small_line="$(line_number_for "$model_discovery_output" "TinyOrg/Tiny-1B-GGUF")"
huge_line="$(line_number_for "$model_discovery_output" "HugeOrg/Huge-70B-GGUF")"
if ((qwen_target_line >= tiny_small_line || tiny_small_line >= huge_line)); then
  printf 'expected ranked order qwen target before tiny small before huge\noutput was:\n%s\n' "$model_discovery_output" >&2
  exit 1
fi
fit_files_tmp="$(mktemp -d)"
cat >"$fit_files_tmp/candidates.json" <<'JSON'
[
  {
    "id": "unsloth/Qwen3-Coder-Next-GGUF",
    "downloads": 10,
    "likes": 2,
    "tags": ["gguf", "code"],
    "siblings": [
      {"rfilename": "Qwen3-Coder-Next-Q3_K_M.gguf", "size": 38322487328},
      {"rfilename": "Qwen3-Coder-Next-UD-IQ1_S.gguf", "size": 21508749344},
      {"rfilename": "Qwen3-Coder-Next-UD-TQ1_0.gguf", "size": 18941835296}
    ]
  }
]
JSON
python3 "$repo_root/scripts/model-fit.py" --hardware-json '{"gpu_name":"RX 7900 XT","vram_gb":20,"ram_gb":64,"cpu_cores":16}' --limit 1 --json <"$fit_files_tmp/candidates.json" >"$fit_files_tmp/ranked.json"
python3 - "$fit_files_tmp/ranked.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    candidate = json.load(handle)["candidates"][0]
if candidate["best_file"] != "Qwen3-Coder-Next-UD-TQ1_0.gguf":
    raise SystemExit(f"expected TQ1_0 file to fit 20GB VRAM: {candidate!r}")
if candidate["best_quant"] != "UD-TQ1_0":
    raise SystemExit(f"expected quant from file name: {candidate!r}")
if candidate["fit_level"] == "too_tight":
    raise SystemExit(f"expected selected file to fit: {candidate!r}")
PY
discovery_dynamic_output="$(OC_LOCAL_HF_FIXTURE="$fit_files_tmp/candidates.json" LOCAL_LLM_HF_TREE_FIXTURE="$fit_files_tmp/candidates.json" OC_LOCAL_REMOTE_HOST=__none__ "$repo_root/scripts/model-discovery.sh" --limit 1)"
assert_contains "$discovery_dynamic_output" "quant=UD-TQ1_0"
assert_contains "$discovery_dynamic_output" "file=Qwen3-Coder-Next-UD-TQ1_0.gguf"

model_discovery_installed_output="$(OC_LOCAL_HF_FIXTURE="$repo_root/testdata/huggingface-model-search.json" OC_LOCAL_REMOTE_HOST=__none__ "$repo_root/scripts/model-discovery.sh" --installed-only)"
assert_contains "$model_discovery_installed_output" "Already Tuned Profiles"
assert_not_contains "$model_discovery_installed_output" "Hugging Face GGUF Candidates"

model_discovery_help_output="$("$repo_root/scripts/model-discovery.sh" --help 2>&1)"
assert_contains "$model_discovery_help_output" "--query <text>"
assert_contains "$model_discovery_help_output" "--limit <n>"
assert_contains "$model_discovery_help_output" "maximum ranked candidates to print"
assert_not_contains "$model_discovery_help_output" "maximum Hugging Face results to request"
assert_contains "$model_discovery_help_output" "--installed-only"
model_manager_help_output="$("$repo_root/scripts/model-manager.sh" --help 2>&1)"
assert_contains "$model_manager_help_output" "Usage: model-manager"
assert_contains "$model_manager_help_output" "bootstrap"
assert_contains "$model_manager_help_output" "discover"
assert_contains "$model_manager_help_output" "select"
assert_contains "$model_manager_help_output" "benchmark"
assert_contains "$model_manager_help_output" "accept"
assert_contains "$model_manager_help_output" "status"
assert_contains "$model_manager_help_output" "list"
assert_contains "$model_manager_help_output" "update"
assert_contains "$model_manager_help_output" "replace"
update_manager_output="$("$repo_root/scripts/update-manager.sh" 2>&1)"
assert_contains "$update_manager_output" "model-manager status"
assert_contains "$update_manager_output" "model-manager discover"
assert_contains "$update_manager_output" "model-manager benchmark"
assert_contains "$update_manager_output" "model-manager update --dry-run"
update_manager_list_output="$("$repo_root/scripts/update-manager.sh" --candidates 2>&1)"
assert_not_contains "$update_manager_list_output" "list-candidates"
assert_contains "$update_manager_list_output" "model-manager list"
update_manager_usage_status=0
update_manager_usage_output="$("$repo_root/scripts/update-manager.sh" --unknown 2>&1)" || update_manager_usage_status=$?
if [[ "$update_manager_usage_status" != 1 ]]; then
  printf 'expected update-manager unknown option to exit 1, got %s\noutput was:\n%s\n' "$update_manager_usage_status" "$update_manager_usage_output" >&2
  exit 1
fi
assert_contains "$update_manager_usage_output" "Usage: update-manager.sh [options]"
manager_tmp="$(mktemp -d)"
mkdir -p "$manager_tmp/candidates" "$manager_tmp/selections" "$manager_tmp/benchmarks"
printf '{}\n' >"$manager_tmp/candidates/sample.json"
status_output="$(LOCAL_LLM_RUNS_DIR="$manager_tmp" "$repo_root/scripts/model-manager.sh" status)"
assert_contains "$status_output" "Model Manager Status"
assert_contains "$status_output" "Candidates: 1"
assert_contains "$status_output" "Selections: 0"
assert_contains "$status_output" "Benchmarks: 0"
bootstrap_tmp="$(mktemp -d)"
bootstrap_output="$(LOCAL_LLM_RUNS_DIR="$bootstrap_tmp/runs" "$repo_root/scripts/model-manager.sh" bootstrap --target remote:bench-host --dry-run)"
assert_contains "$bootstrap_output" "Bootstrap plan"
assert_contains "$bootstrap_output" "target=remote:bench-host"
assert_contains "$bootstrap_output" "next=model-manager discover"
bootstrap_dry_yes_status=0
bootstrap_dry_yes_output="$(LOCAL_LLM_RUNS_DIR="$bootstrap_tmp/dry-yes-runs" "$repo_root/scripts/model-manager.sh" bootstrap --target remote:bench-host --dry-run --yes 2>&1)" || bootstrap_dry_yes_status=$?
if [[ "$bootstrap_dry_yes_status" == 0 ]]; then
  printf 'expected bootstrap --dry-run --yes to fail\noutput was:\n%s\n' "$bootstrap_dry_yes_output" >&2
  exit 1
fi
assert_contains "$bootstrap_dry_yes_output" "choose either --dry-run or --yes"
if [[ -f "$bootstrap_tmp/dry-yes-runs/bootstrap/config.json" ]]; then
  printf 'expected bootstrap --dry-run --yes not to write config at %s\n' "$bootstrap_tmp/dry-yes-runs/bootstrap/config.json" >&2
  exit 1
fi
bootstrap_bad_target_status=0
bootstrap_bad_target_output="$(LOCAL_LLM_RUNS_DIR="$bootstrap_tmp/bad-target-runs" "$repo_root/scripts/model-manager.sh" bootstrap --target 'remote:bad host' --dry-run 2>&1)" || bootstrap_bad_target_status=$?
if [[ "$bootstrap_bad_target_status" == 0 ]]; then
  printf 'expected bootstrap unsafe target to fail\noutput was:\n%s\n' "$bootstrap_bad_target_output" >&2
  exit 1
fi
assert_contains "$bootstrap_bad_target_output" "invalid target"
bootstrap_bad_remote_host_status=0
bootstrap_bad_remote_host_output="$(LOCAL_LLM_RUNS_DIR="$bootstrap_tmp/bad-remote-host-runs" "$repo_root/scripts/model-manager.sh" bootstrap --target remote:-bad --dry-run 2>&1)" || bootstrap_bad_remote_host_status=$?
if [[ "$bootstrap_bad_remote_host_status" == 0 ]]; then
  printf 'expected bootstrap with unsafe remote host to fail\noutput was:\n%s\n' "$bootstrap_bad_remote_host_output" >&2
  exit 1
fi
assert_contains "$bootstrap_bad_remote_host_output" "remote target host must not start with '-'"
LOCAL_LLM_RUNS_DIR="$bootstrap_tmp/runs" "$repo_root/scripts/model-manager.sh" bootstrap --target remote:bench-host --yes >/dev/null
if [[ ! -f "$bootstrap_tmp/runs/bootstrap/config.json" ]]; then
  printf 'expected bootstrap config at %s\n' "$bootstrap_tmp/runs/bootstrap/config.json" >&2
  exit 1
fi
python3 - "$bootstrap_tmp/runs/bootstrap/config.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    config = json.load(handle)
if config.get("target") != "remote:bench-host":
    raise SystemExit(f"expected bootstrap target remote:bench-host: {config!r}")
if not isinstance(config.get("created_at"), str) or not config["created_at"]:
    raise SystemExit(f"expected non-empty created_at: {config!r}")
PY
bootstrap_symlink_runs="$bootstrap_tmp/symlink-runs"
bootstrap_symlink_outside="$bootstrap_tmp/bootstrap-outside"
mkdir -p "$bootstrap_symlink_runs" "$bootstrap_symlink_outside"
ln -s "$bootstrap_symlink_outside" "$bootstrap_symlink_runs/bootstrap"
bootstrap_symlink_output="$bootstrap_tmp/bootstrap-symlink.out"
if LOCAL_LLM_RUNS_DIR="$bootstrap_symlink_runs" "$repo_root/scripts/model-manager.sh" bootstrap --target remote:bench-host --yes >"$bootstrap_symlink_output" 2>&1; then
  printf 'expected bootstrap --yes with symlinked bootstrap dir to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$bootstrap_symlink_output")" "refuses symlinked bootstrap dir"
if [[ -e "$bootstrap_symlink_outside/config.json" ]]; then
  printf 'bootstrap wrote through symlinked bootstrap dir\n' >&2
  exit 1
fi
bootstrap_config_symlink_runs="$bootstrap_tmp/config-symlink-runs"
bootstrap_config_symlink_outside="$bootstrap_tmp/config-symlink-outside.json"
mkdir -p "$bootstrap_config_symlink_runs/bootstrap"
ln -s "$bootstrap_config_symlink_outside" "$bootstrap_config_symlink_runs/bootstrap/config.json"
bootstrap_config_symlink_output="$bootstrap_tmp/bootstrap-config-symlink.out"
if LOCAL_LLM_RUNS_DIR="$bootstrap_config_symlink_runs" "$repo_root/scripts/model-manager.sh" bootstrap --target remote:bench-host --yes >"$bootstrap_config_symlink_output" 2>&1; then
  printf 'expected bootstrap --yes with symlinked config file to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$bootstrap_config_symlink_output")" "refuses symlinked state file"
if [[ -e "$bootstrap_config_symlink_outside" ]]; then
  printf 'bootstrap wrote through symlinked config file\n' >&2
  exit 1
fi
bootstrap_symlink_root="$bootstrap_tmp/symlink-root"
bootstrap_symlink_root_outside="$bootstrap_tmp/symlink-root-outside"
mkdir -p "$bootstrap_symlink_root_outside"
ln -s "$bootstrap_symlink_root_outside" "$bootstrap_symlink_root"
bootstrap_symlink_root_output="$bootstrap_tmp/bootstrap-symlink-root.out"
if LOCAL_LLM_RUNS_DIR="$bootstrap_symlink_root" "$repo_root/scripts/model-manager.sh" bootstrap --target remote:bench-host --yes >"$bootstrap_symlink_root_output" 2>&1; then
  printf 'expected bootstrap --yes with symlinked runs root to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$bootstrap_symlink_root_output")" "refuses symlinked runs dir"
if [[ -e "$bootstrap_symlink_root_outside/bootstrap/config.json" ]]; then
  printf 'bootstrap wrote through symlinked runs root\n' >&2
  exit 1
fi
export_restore_tmp="$(mktemp -d)"
export_runs="$export_restore_tmp/runs"
restore_runs="$export_restore_tmp/restored-runs"
mkdir -p "$export_runs/bootstrap" "$export_runs/accepted" "$export_runs/launchers"
printf '{"target":"remote:bench-host","created_at":"2026-05-24T00:00:00Z"}\n' >"$export_runs/bootstrap/config.json"
cat >"$export_runs/accepted/example.json" <<'JSON'
{
  "alias": "example-model",
  "family": "example",
  "repo": "Example/Model-GGUF",
  "remote_start": "./start201.sh"
}
JSON
cat >"$export_runs/launchers/start201.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
exec ./build/bin/llama-server --alias example-model
EOF
chmod +x "$export_runs/launchers/start201.sh"
printf '{"outside":true}\n' >"$export_restore_tmp/outside-accepted.json"
printf '#!/usr/bin/env bash\nprintf outside\n' >"$export_restore_tmp/outside-launcher.sh"
printf '{"target":"remote:outside"}\n' >"$export_restore_tmp/outside-bootstrap-config.json"
ln -s "$export_restore_tmp/outside-accepted.json" "$export_runs/accepted/link.json"
ln -s "$export_restore_tmp/outside-launcher.sh" "$export_runs/launchers/link.sh"
export_output="$(LOCAL_LLM_RUNS_DIR="$export_runs" "$repo_root/scripts/model-manager.sh" export)"
python3 - "$export_output" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
if payload.get("version") != 1:
    raise SystemExit(f"expected version 1: {payload!r}")
if payload.get("bootstrap", {}).get("target") != "remote:bench-host":
    raise SystemExit(f"expected bootstrap config: {payload!r}")
if payload.get("accepted", {}).get("example.json", {}).get("alias") != "example-model":
    raise SystemExit(f"expected accepted entry: {payload!r}")
launcher = payload.get("launchers", {}).get("start201.sh")
if not isinstance(launcher, dict) or "content" not in launcher:
    raise SystemExit(f"expected launcher content: {payload!r}")
if "link.json" in payload.get("accepted", {}):
    raise SystemExit(f"expected accepted symlink to be skipped: {payload!r}")
if "link.sh" in payload.get("launchers", {}):
    raise SystemExit(f"expected launcher symlink to be skipped: {payload!r}")
PY
mv "$export_runs/bootstrap/config.json" "$export_runs/bootstrap/config.real.json"
ln -s "$export_restore_tmp/outside-bootstrap-config.json" "$export_runs/bootstrap/config.json"
bootstrap_config_symlink_export="$(LOCAL_LLM_RUNS_DIR="$export_runs" "$repo_root/scripts/model-manager.sh" export)"
python3 - "$bootstrap_config_symlink_export" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
if "bootstrap" in payload:
    raise SystemExit(f"expected symlinked bootstrap config to be skipped: {payload!r}")
PY
rm "$export_runs/bootstrap/config.json"
mv "$export_runs/bootstrap/config.real.json" "$export_runs/bootstrap/config.json"
mv "$export_runs/bootstrap" "$export_runs/bootstrap.real"
ln -s "$export_restore_tmp" "$export_runs/bootstrap"
bootstrap_dir_symlink_export="$(LOCAL_LLM_RUNS_DIR="$export_runs" "$repo_root/scripts/model-manager.sh" export)"
python3 - "$bootstrap_dir_symlink_export" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
if "bootstrap" in payload:
    raise SystemExit(f"expected symlinked bootstrap dir to be skipped: {payload!r}")
PY
rm "$export_runs/bootstrap"
mv "$export_runs/bootstrap.real" "$export_runs/bootstrap"
export_symlink_root_runs="$export_restore_tmp/export-symlink-root-runs"
export_symlink_root_outside="$export_restore_tmp/export-symlink-root-outside"
mkdir -p "$export_symlink_root_outside/bootstrap"
printf '{"target":"remote:outside-state"}\n' >"$export_symlink_root_outside/bootstrap/config.json"
ln -s "$export_symlink_root_outside" "$export_symlink_root_runs"
export_symlink_root_output="$export_restore_tmp/export-symlink-root.out"
if LOCAL_LLM_RUNS_DIR="$export_symlink_root_runs" "$repo_root/scripts/model-manager.sh" export >"$export_symlink_root_output" 2>&1; then
  printf 'expected export with symlinked runs root to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$export_symlink_root_output")" "export refuses symlinked runs dir"
assert_not_contains "$(<"$export_symlink_root_output")" "outside-state"
printf '%s\n' "$export_output" >"$export_restore_tmp/backup.json"
LOCAL_LLM_RUNS_DIR="$restore_runs" "$repo_root/scripts/model-manager.sh" restore "$export_restore_tmp/backup.json" >/dev/null
if [[ ! -f "$restore_runs/accepted/example.json" ]]; then
  printf 'expected restored accepted metadata\n' >&2
  exit 1
fi
if [[ ! -x "$restore_runs/launchers/start201.sh" ]]; then
  printf 'expected restored executable launcher\n' >&2
  exit 1
fi
assert_contains "$(<"$restore_runs/accepted/example.json")" '"alias": "example-model"'
assert_contains "$(<"$restore_runs/launchers/start201.sh")" '--alias example-model'
python3 - "$export_restore_tmp/unsafe-backup.json" <<'PY'
import json
import sys

with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump(
        {
            "version": 1,
            "accepted": {
                "unsafe.json": {
                    "alias": "unsafe-model",
                    "family": "unsafe",
                    "repo": "Example/Unsafe-GGUF",
                    "remote_start": "./start202.sh",
                }
            },
            "launchers": {
                "start202.sh": {"content": "#!/usr/bin/env bash\n"},
                "zz/escape.sh": {"content": "#!/usr/bin/env bash\n"},
            },
        },
        handle,
    )
    handle.write("\n")
PY
unsafe_restore_output="$export_restore_tmp/unsafe-restore.out"
unsafe_restore_runs="$export_restore_tmp/unsafe-runs"
if LOCAL_LLM_RUNS_DIR="$unsafe_restore_runs" "$repo_root/scripts/model-manager.sh" restore "$export_restore_tmp/unsafe-backup.json" >"$unsafe_restore_output" 2>&1; then
  printf 'expected restore with unsafe launcher name to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$unsafe_restore_output")" "unsafe launcher name"
if [[ -e "$unsafe_restore_runs/accepted/unsafe.json" ]]; then
  printf 'unsafe restore left accepted metadata behind\n' >&2
  exit 1
fi
if [[ -e "$unsafe_restore_runs/launchers/start202.sh" ]]; then
  printf 'unsafe restore left launcher behind\n' >&2
  exit 1
fi
python3 - "$export_restore_tmp/invalid-accepted-numeric-backup.json" <<'PY'
import json
import sys

with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump(
        {
            "version": 1,
            "accepted": {
                "unsafe.json": {
                    "alias": "unsafe-model",
                    "family": "unsafe",
                    "repo": "Example/Unsafe-GGUF",
                    "remote_start": "./start203.sh",
                    "config": {"ctx": "1; touch /tmp/pwned", "batch": 128, "ubatch": 64, "ngl": 999},
                }
            },
        },
        handle,
    )
    handle.write("\n")
PY
invalid_accepted_numeric_output="$export_restore_tmp/invalid-accepted-numeric-restore.out"
invalid_accepted_numeric_runs="$export_restore_tmp/invalid-accepted-numeric-runs"
if LOCAL_LLM_RUNS_DIR="$invalid_accepted_numeric_runs" "$repo_root/scripts/model-manager.sh" restore "$export_restore_tmp/invalid-accepted-numeric-backup.json" >"$invalid_accepted_numeric_output" 2>&1; then
  printf 'expected restore with invalid accepted metadata numeric field to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$invalid_accepted_numeric_output")" "accepted config field must be an integer: unsafe.json config.ctx"
if [[ -e "$invalid_accepted_numeric_runs/accepted/unsafe.json" ]]; then
  printf 'invalid accepted numeric restore left accepted metadata behind\n' >&2
  exit 1
fi
python3 - "$export_restore_tmp/unsafe-accepted-remote-start-backup.json" <<'PY'
import json
import sys

with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump(
        {
            "version": 1,
            "accepted": {
                "unsafe.json": {
                    "alias": "unsafe-model",
                    "family": "unsafe",
                    "repo": "Example/Unsafe-GGUF",
                    "remote_start": "$(touch /tmp/local-llm-restore-pwned)",
                }
            },
        },
        handle,
    )
    handle.write("\n")
PY
unsafe_accepted_remote_start_output="$export_restore_tmp/unsafe-accepted-remote-start-restore.out"
unsafe_accepted_remote_start_runs="$export_restore_tmp/unsafe-accepted-remote-start-runs"
if LOCAL_LLM_RUNS_DIR="$unsafe_accepted_remote_start_runs" "$repo_root/scripts/model-manager.sh" restore "$export_restore_tmp/unsafe-accepted-remote-start-backup.json" >"$unsafe_accepted_remote_start_output" 2>&1; then
  printf 'expected restore with unsafe accepted remote_start to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$unsafe_accepted_remote_start_output")" "accepted remote_start must be a safe relative launcher path: unsafe.json"
if [[ -e "$unsafe_accepted_remote_start_runs/accepted/unsafe.json" ]]; then
  printf 'unsafe accepted remote_start restore left accepted metadata behind\n' >&2
  exit 1
fi
restore_partial_runs="$export_restore_tmp/partial-symlink-runs"
restore_partial_outside="$export_restore_tmp/partial-accepted-outside.json"
mkdir -p "$restore_partial_runs/accepted"
ln -s "$restore_partial_outside" "$restore_partial_runs/accepted/example.json"
partial_restore_output="$export_restore_tmp/partial-symlink-restore.out"
if LOCAL_LLM_RUNS_DIR="$restore_partial_runs" "$repo_root/scripts/model-manager.sh" restore "$export_restore_tmp/backup.json" >"$partial_restore_output" 2>&1; then
  printf 'expected restore with symlinked accepted target file to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$partial_restore_output")" "restore refuses symlinked state file"
if [[ -e "$restore_partial_runs/bootstrap/config.json" ]]; then
  printf 'restore wrote bootstrap before failing on accepted target symlink\n' >&2
  exit 1
fi
if [[ -e "$restore_partial_outside" ]]; then
  printf 'restore wrote through symlinked accepted target file\n' >&2
  exit 1
fi
restore_symlink_accepted_runs="$export_restore_tmp/symlink-accepted-runs"
restore_symlink_accepted_outside="$export_restore_tmp/symlink-accepted-outside"
mkdir -p "$restore_symlink_accepted_runs" "$restore_symlink_accepted_outside"
ln -s "$restore_symlink_accepted_outside" "$restore_symlink_accepted_runs/accepted"
symlink_accepted_output="$export_restore_tmp/symlink-accepted-restore.out"
if LOCAL_LLM_RUNS_DIR="$restore_symlink_accepted_runs" "$repo_root/scripts/model-manager.sh" restore "$export_restore_tmp/backup.json" >"$symlink_accepted_output" 2>&1; then
  printf 'expected restore with symlinked accepted dir to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$symlink_accepted_output")" "restore refuses symlinked accepted dir"
if [[ -e "$restore_symlink_accepted_outside/example.json" ]]; then
  printf 'restore wrote through symlinked accepted dir\n' >&2
  exit 1
fi
restore_symlink_launcher_runs="$export_restore_tmp/symlink-launcher-runs"
restore_symlink_launcher_outside="$export_restore_tmp/symlink-launcher-outside"
mkdir -p "$restore_symlink_launcher_runs" "$restore_symlink_launcher_outside"
ln -s "$restore_symlink_launcher_outside" "$restore_symlink_launcher_runs/launchers"
symlink_launcher_output="$export_restore_tmp/symlink-launcher-restore.out"
if LOCAL_LLM_RUNS_DIR="$restore_symlink_launcher_runs" "$repo_root/scripts/model-manager.sh" restore "$export_restore_tmp/backup.json" >"$symlink_launcher_output" 2>&1; then
  printf 'expected restore with symlinked launchers dir to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$symlink_launcher_output")" "restore refuses symlinked launchers dir"
if [[ -e "$restore_symlink_launcher_outside/start201.sh" ]]; then
  printf 'restore wrote through symlinked launchers dir\n' >&2
  exit 1
fi
restore_symlink_bootstrap_runs="$export_restore_tmp/symlink-bootstrap-runs"
restore_symlink_bootstrap_outside="$export_restore_tmp/symlink-bootstrap-outside"
mkdir -p "$restore_symlink_bootstrap_runs" "$restore_symlink_bootstrap_outside"
ln -s "$restore_symlink_bootstrap_outside" "$restore_symlink_bootstrap_runs/bootstrap"
symlink_bootstrap_output="$export_restore_tmp/symlink-bootstrap-restore.out"
if LOCAL_LLM_RUNS_DIR="$restore_symlink_bootstrap_runs" "$repo_root/scripts/model-manager.sh" restore "$export_restore_tmp/backup.json" >"$symlink_bootstrap_output" 2>&1; then
  printf 'expected restore with symlinked bootstrap dir to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$symlink_bootstrap_output")" "restore refuses symlinked bootstrap dir"
if [[ -e "$restore_symlink_bootstrap_outside/config.json" ]]; then
  printf 'restore wrote through symlinked bootstrap dir\n' >&2
  exit 1
fi
restore_symlink_root_runs="$export_restore_tmp/symlink-root-runs"
restore_symlink_root_outside="$export_restore_tmp/symlink-root-outside"
mkdir -p "$restore_symlink_root_outside"
ln -s "$restore_symlink_root_outside" "$restore_symlink_root_runs"
symlink_root_output="$export_restore_tmp/symlink-root-restore.out"
if LOCAL_LLM_RUNS_DIR="$restore_symlink_root_runs" "$repo_root/scripts/model-manager.sh" restore "$export_restore_tmp/backup.json" >"$symlink_root_output" 2>&1; then
  printf 'expected restore with symlinked runs root to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$symlink_root_output")" "restore refuses symlinked runs dir"
if [[ -e "$restore_symlink_root_outside/accepted/example.json" || -e "$restore_symlink_root_outside/launchers/start201.sh" ]]; then
  printf 'restore wrote through symlinked runs root\n' >&2
  exit 1
fi
list_tmp="$(mktemp -d)"
mkdir -p "$list_tmp/runs/selections" "$list_tmp/runs/benchmarks" "$list_tmp/bin"
printf '{"repo":"Example/Old-GGUF","family":"qwen-coder","alias":"old","target":"remote:bench-host"}\n' >"$list_tmp/runs/selections/old.json"
cat >"$list_tmp/bin/ssh" <<'EOF'
#!/usr/bin/env bash
printf '{"repo":"Example/Old-GGUF","file":"Old-Q4_K_M.gguf","size_gb":"12.3","cache":"remote"}\n'
EOF
chmod +x "$list_tmp/bin/ssh"
list_output="$(PATH="$list_tmp/bin:$PATH" LOCAL_LLM_RUNS_DIR="$list_tmp/runs" "$repo_root/scripts/model-manager.sh" list --target remote:bench-host)"
assert_contains "$list_output" "Models"
assert_contains "$list_output" "Profiles"
assert_contains "$list_output" "Launchers"
assert_contains "$list_output" "Pending Selections"
assert_contains "$list_output" "Remote Cache"
assert_contains "$list_output" "  None"
assert_not_contains "$list_output" "qwen3.6-35b-a3b-mtp"
assert_not_contains "$list_output" "source: unsloth/Qwen3.6-35B-A3B-MTP-GGUF"
assert_contains "$list_output" "old"
assert_contains "$list_output" "target: remote:bench-host"
assert_contains "$list_output" "Example/Old-GGUF"
assert_contains "$list_output" "Old-Q4_K_M.gguf"
assert_not_contains "$list_output" "selection repo=unsloth/Qwen3-Coder-Next-GGUF"
update_tmp="$(mktemp -d)"
mkdir -p "$update_tmp/bin"
cat >"$update_tmp/tree.json" <<'JSON'
[
  {"type":"file","path":"Model-Q3_K_M.gguf","size":22000000000},
  {"type":"file","path":"Model-Q4_K_M.gguf","size":17000000000}
]
JSON
cat >"$update_tmp/bin/ssh" <<'EOF'
#!/usr/bin/env bash
printf '{"repo":"Example/Model-GGUF","file":"Model-Q2_K.gguf","size_gb":"8","cache":"remote"}\n'
printf '{"repo":"Example/Model-GGUF","file":"mmproj-BF16.gguf","size_gb":"1","cache":"remote"}\n'
EOF
chmod +x "$update_tmp/bin/ssh"
update_missing_dry_run_output="$update_tmp/missing-dry-run.out"
if PATH="$update_tmp/bin:$PATH" "$repo_root/scripts/model-manager.sh" update --target remote:bench-host >"$update_missing_dry_run_output" 2>&1; then
  printf 'expected update without --dry-run to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$update_missing_dry_run_output")" "update requires exactly one of --dry-run or --yes"
update_output="$(PATH="$update_tmp/bin:$PATH" LOCAL_LLM_HF_TREE_FIXTURE="$update_tmp/tree.json" "$repo_root/scripts/model-manager.sh" update --target remote:bench-host --dry-run)"
assert_contains "$update_output" "Updates"
assert_contains "$update_output" "[1] Example/Model-GGUF"
assert_contains "$update_output" "Replace this cached file:"
assert_contains "$update_output" "With this Hugging Face file:"
assert_contains "$update_output" "Why this is recommended:"
assert_contains "$update_output" "What --yes will do:"
assert_contains "$update_output" "Model-Q2_K.gguf"
assert_contains "$update_output" "Model-Q4_K_M.gguf"
assert_contains "$update_output" "Download Model-Q4_K_M.gguf"
assert_contains "$update_output" "Delete Model-Q2_K.gguf"
assert_not_contains "$update_output" "current=mmproj-BF16.gguf"
cat >"$update_tmp/tree-matching-basename.json" <<'JSON'
[
  {"type":"file","path":"Q4/Model-Q4_K_M.gguf","size":17000000000}
]
JSON
cat >"$update_tmp/bin/ssh" <<'EOF'
#!/usr/bin/env bash
printf '{"repo":"Example/Model-GGUF","file":"Model-Q4_K_M.gguf","size_gb":"17","cache":"remote","revision":"oldrev"}\n'
EOF
chmod +x "$update_tmp/bin/ssh"
update_same_basename_output="$(PATH="$update_tmp/bin:$PATH" LOCAL_LLM_HF_TREE_FIXTURE="$update_tmp/tree-matching-basename.json" LOCAL_LLM_HF_REVISION_FIXTURE="newrev" "$repo_root/scripts/model-manager.sh" update --target remote:bench-host --dry-run)"
assert_contains "$update_same_basename_output" "Recommended Updates"
assert_contains "$update_same_basename_output" "Model-Q4_K_M.gguf"
assert_contains "$update_same_basename_output" "Q4/Model-Q4_K_M.gguf"
assert_contains "$update_same_basename_output" "same GGUF filename exists in a newer Hugging Face snapshot"
assert_contains "$update_same_basename_output" "cached revision: oldrev"
assert_contains "$update_same_basename_output" "latest revision: newrev"
cat >"$update_tmp/bin/ssh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "$*" == *"bash -s"* ]]; then
  cat >"$LOCAL_LLM_FAKE_UPDATE_SCRIPT"
  printf 'deleted=Model-Q2_K.gguf\n'
  printf 'delete_status=deleted\n'
  printf 'download_status=success\n'
else
  printf '{"repo":"Example/Model-GGUF","file":"Model-Q2_K.gguf","size_gb":"8","cache":"remote"}\n'
fi
EOF
chmod +x "$update_tmp/bin/ssh"
update_yes_output="$(PATH="$update_tmp/bin:$PATH" LOCAL_LLM_HF_TREE_FIXTURE="$update_tmp/tree.json" LOCAL_LLM_FAKE_UPDATE_SCRIPT="$update_tmp/update-remote.sh" "$repo_root/scripts/model-manager.sh" update --target remote:bench-host --yes || true)"
assert_contains "$update_yes_output" "Update result"
assert_contains "$update_yes_output" "download_status=success"
assert_contains "$update_yes_output" "delete_status=deleted"
assert_contains "$(<"$update_tmp/update-remote.sh")" "python3 -m pip install --user -U 'huggingface_hub[cli]'"
assert_contains "$(<"$update_tmp/update-remote.sh")" "download_tool=python-urllib"
assert_contains "$(<"$update_tmp/update-remote.sh")" "urllib.request.urlopen"
assert_contains "$(<"$update_tmp/update-remote.sh")" "huggingface-cli download \"\$new_repo\" \"\$selected_file\""
assert_contains "$(<"$update_tmp/update-remote.sh")" "rm -f"
replace_tmp="$(mktemp -d)"
mkdir -p "$replace_tmp/bin" "$replace_tmp/runs"
cat >"$replace_tmp/tree.json" <<'JSON'
[
  {"type":"file","path":"New-Q3_K_M.gguf","size":22000000000},
  {"type":"file","path":"New-Q4_K_M.gguf","size":17000000000}
]
JSON
cat >"$replace_tmp/bin/ssh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "$*" == *"bash -s"* ]]; then
  script_input="$(cat)"
  printf '%s\n' "$script_input" >"$LOCAL_LLM_FAKE_REPLACE_SCRIPT"
  printf 'secret-from-ssh\n' >&2
  printf 'deleted=Old-Q2_K.gguf\n'
  printf 'delete_status=deleted\n'
  printf 'download_status=success\n'
else
  printf 'not-a-vram-number\n'
fi
EOF
chmod +x "$replace_tmp/bin/ssh"
replace_dry_run_output="$(PATH="$replace_tmp/bin:$PATH" LOCAL_LLM_RUNS_DIR="$replace_tmp/runs" LOCAL_LLM_HF_TREE_FIXTURE="$replace_tmp/tree.json" "$repo_root/scripts/model-manager.sh" replace Old-Q2_K.gguf Example/New-GGUF --target remote:bench-host --dry-run)"
assert_contains "$replace_dry_run_output" "Replacement dry-run"
assert_contains "$replace_dry_run_output" "old_file=Old-Q2_K.gguf"
assert_contains "$replace_dry_run_output" "new_repo=Example/New-GGUF"
assert_contains "$replace_dry_run_output" "selected_quant=Q4_K_M"
assert_contains "$replace_dry_run_output" "selected_file=New-Q4_K_M.gguf"
assert_contains "$replace_dry_run_output" "target=remote:bench-host"
assert_contains "$replace_dry_run_output" "would_delete_remote_basename=Old-Q2_K.gguf"
assert_contains "$replace_dry_run_output" "would_download_repo=Example/New-GGUF"
replace_no_mode_output="$replace_tmp/no-mode.out"
if LOCAL_LLM_RUNS_DIR="$replace_tmp/runs" LOCAL_LLM_HF_TREE_FIXTURE="$replace_tmp/tree.json" "$repo_root/scripts/model-manager.sh" replace Old-Q2_K.gguf Example/New-GGUF --target remote:bench-host >"$replace_no_mode_output" 2>&1; then
  printf 'expected replace without --dry-run or --yes to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$replace_no_mode_output")" "replace requires exactly one of --dry-run or --yes"
replace_both_modes_output="$replace_tmp/both-modes.out"
if LOCAL_LLM_RUNS_DIR="$replace_tmp/runs" LOCAL_LLM_HF_TREE_FIXTURE="$replace_tmp/tree.json" "$repo_root/scripts/model-manager.sh" replace Old-Q2_K.gguf Example/New-GGUF --target remote:bench-host --dry-run --yes >"$replace_both_modes_output" 2>&1; then
  printf 'expected replace with both modes to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$replace_both_modes_output")" "replace requires exactly one of --dry-run or --yes"
replace_bad_old_output="$replace_tmp/bad-old.out"
if LOCAL_LLM_RUNS_DIR="$replace_tmp/runs" "$repo_root/scripts/model-manager.sh" replace path/Old-Q2_K.gguf Example/New-GGUF --target remote:bench-host --dry-run >"$replace_bad_old_output" 2>&1; then
  printf 'expected replace with unsafe old file to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$replace_bad_old_output")" "old-file must be a basename"
replace_metachar_old_output="$replace_tmp/metachar-old.out"
if PATH="$replace_tmp/bin:$PATH" LOCAL_LLM_RUNS_DIR="$replace_tmp/runs" LOCAL_LLM_HF_TREE_FIXTURE="$replace_tmp/tree.json" "$repo_root/scripts/model-manager.sh" replace 'bad;touch-pwn.gguf' Example/New-GGUF --target remote:bench-host --yes >"$replace_metachar_old_output" 2>&1; then
  printf 'expected replace with shell metacharacter old file to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$replace_metachar_old_output")" "old-file must be a safe GGUF basename"
if [[ -e "$replace_tmp/script.sh" ]]; then
  printf 'expected metacharacter old file to be rejected before ssh\n' >&2
  exit 1
fi
replace_bad_target_output="$replace_tmp/bad-target.out"
if LOCAL_LLM_RUNS_DIR="$replace_tmp/runs" "$repo_root/scripts/model-manager.sh" replace Old-Q2_K.gguf Example/New-GGUF --target remote:-bad --dry-run >"$replace_bad_target_output" 2>&1; then
  printf 'expected replace with unsafe target to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$replace_bad_target_output")" "remote target host must not start with '-'"
replace_output="$(PATH="$replace_tmp/bin:$PATH" LOCAL_LLM_RUNS_DIR="$replace_tmp/runs" LOCAL_LLM_HF_TREE_FIXTURE="$replace_tmp/tree.json" LOCAL_LLM_FAKE_REPLACE_SCRIPT="$replace_tmp/script.sh" "$repo_root/scripts/model-manager.sh" replace Old-Q2_K.gguf Example/New-GGUF --target remote:bench-host --yes 2>"$replace_tmp/yes.stderr")"
assert_contains "$replace_output" "Replacement complete"
assert_contains "$replace_output" "old_file=Old-Q2_K.gguf"
assert_contains "$replace_output" "new_repo=Example/New-GGUF"
assert_contains "$replace_output" "selected_quant=Q4_K_M"
assert_contains "$replace_output" "selected_file=New-Q4_K_M.gguf"
assert_contains "$replace_output" "delete_status=deleted"
assert_contains "$replace_output" "download_status=success"
assert_contains "$(<"$replace_tmp/script.sh")" "basename"
assert_contains "$(<"$replace_tmp/script.sh")" "old_file_b64="
assert_not_contains "$(<"$replace_tmp/script.sh")" "bash -s --"
assert_not_contains "$(<"$replace_tmp/script.sh")" "HF_HOME"
assert_not_contains "$(<"$replace_tmp/yes.stderr")" "secret-from-ssh"
cat >"$replace_tmp/bin/ssh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "$*" == *"bash -s"* ]]; then
  cat >"$LOCAL_LLM_FAKE_REPLACE_FAIL_SCRIPT"
  printf 'deleted=none\n'
  printf 'delete_status=not_attempted\n'
  printf 'download_status=failed\n'
else
  printf 'not-a-vram-number\n'
fi
EOF
chmod +x "$replace_tmp/bin/ssh"
replace_fail_output="$replace_tmp/download-failed.out"
if PATH="$replace_tmp/bin:$PATH" LOCAL_LLM_RUNS_DIR="$replace_tmp/runs" LOCAL_LLM_HF_TREE_FIXTURE="$replace_tmp/tree.json" LOCAL_LLM_FAKE_REPLACE_FAIL_SCRIPT="$replace_tmp/fail-script.sh" "$repo_root/scripts/model-manager.sh" replace Old-Q2_K.gguf Example/New-GGUF --target remote:bench-host --yes >"$replace_fail_output" 2>&1; then
  printf 'expected replace with failed download to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$replace_fail_output")" "Replacement did not complete"
assert_contains "$(<"$replace_fail_output")" "download_status=failed"
assert_contains "$(<"$replace_fail_output")" "delete_status=not_attempted"
assert_not_contains "$(<"$replace_fail_output")" "Replacement complete"
cat >"$replace_tmp/bin/ssh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "$*" == *"bash -s"* ]]; then
  cat >"$LOCAL_LLM_FAKE_REPLACE_AMBIGUOUS_SCRIPT"
  printf 'deleted=none\n'
  printf 'delete_status=ambiguous\n'
  printf 'download_status=success\n'
else
  printf 'not-a-vram-number\n'
fi
EOF
chmod +x "$replace_tmp/bin/ssh"
replace_ambiguous_output="$replace_tmp/ambiguous-delete.out"
if PATH="$replace_tmp/bin:$PATH" LOCAL_LLM_RUNS_DIR="$replace_tmp/runs" LOCAL_LLM_HF_TREE_FIXTURE="$replace_tmp/tree.json" LOCAL_LLM_FAKE_REPLACE_AMBIGUOUS_SCRIPT="$replace_tmp/ambiguous-script.sh" "$repo_root/scripts/model-manager.sh" replace Old-Q2_K.gguf Example/New-GGUF --target remote:bench-host --yes >"$replace_ambiguous_output" 2>&1; then
  printf 'expected replace with duplicate old-file matches to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$replace_ambiguous_output")" "Replacement did not complete"
assert_contains "$(<"$replace_ambiguous_output")" "delete_status=ambiguous"
assert_contains "$(<"$replace_ambiguous_output")" "download_status=success"
assert_not_contains "$(<"$replace_ambiguous_output")" "Replacement complete"
replace_remote_logic_tmp="$(mktemp -d)"
mkdir -p "$replace_remote_logic_tmp/bin" "$replace_remote_logic_tmp/runs" "$replace_remote_logic_tmp/home/.cache/huggingface/hub/a" "$replace_remote_logic_tmp/home/.cache/local_llm/models/b"
cp "$replace_tmp/tree.json" "$replace_remote_logic_tmp/tree.json"
cat >"$replace_remote_logic_tmp/bin/ssh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "$*" == *"bash -s"* ]]; then
  HOME="$LOCAL_LLM_FAKE_REMOTE_HOME" PATH="$LOCAL_LLM_FAKE_REMOTE_BIN:$PATH" bash -s
else
  printf 'not-a-vram-number\n'
fi
EOF
chmod +x "$replace_remote_logic_tmp/bin/ssh"
cat >"$replace_remote_logic_tmp/bin/huggingface-cli" <<'EOF'
#!/usr/bin/env bash
exit 1
EOF
chmod +x "$replace_remote_logic_tmp/bin/huggingface-cli"
printf 'old\n' >"$replace_remote_logic_tmp/home/.cache/huggingface/hub/a/Old-Q2_K.gguf"
replace_real_fail_output="$replace_remote_logic_tmp/real-failed-download.out"
if PATH="$replace_remote_logic_tmp/bin:$PATH" LOCAL_LLM_RUNS_DIR="$replace_remote_logic_tmp/runs" LOCAL_LLM_HF_TREE_FIXTURE="$replace_remote_logic_tmp/tree.json" LOCAL_LLM_FAKE_REMOTE_HOME="$replace_remote_logic_tmp/home" LOCAL_LLM_FAKE_REMOTE_BIN="$replace_remote_logic_tmp/bin" "$repo_root/scripts/model-manager.sh" replace Old-Q2_K.gguf Example/New-GGUF --target remote:bench-host --yes >"$replace_real_fail_output" 2>&1; then
  printf 'expected real remote replace logic with failed download to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$replace_real_fail_output")" "delete_status=not_attempted"
assert_contains "$(<"$replace_real_fail_output")" "download_status=failed"
if [[ ! -e "$replace_remote_logic_tmp/home/.cache/huggingface/hub/a/Old-Q2_K.gguf" ]]; then
  printf 'expected failed download to leave old file in place\n' >&2
  exit 1
fi
cat >"$replace_remote_logic_tmp/bin/huggingface-cli" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
chmod +x "$replace_remote_logic_tmp/bin/huggingface-cli"
printf 'old\n' >"$replace_remote_logic_tmp/home/.cache/local_llm/models/b/Old-Q2_K.gguf"
replace_real_ambiguous_output="$replace_remote_logic_tmp/real-ambiguous.out"
if PATH="$replace_remote_logic_tmp/bin:$PATH" LOCAL_LLM_RUNS_DIR="$replace_remote_logic_tmp/runs" LOCAL_LLM_HF_TREE_FIXTURE="$replace_remote_logic_tmp/tree.json" LOCAL_LLM_FAKE_REMOTE_HOME="$replace_remote_logic_tmp/home" LOCAL_LLM_FAKE_REMOTE_BIN="$replace_remote_logic_tmp/bin" "$repo_root/scripts/model-manager.sh" replace Old-Q2_K.gguf Example/New-GGUF --target remote:bench-host --yes >"$replace_real_ambiguous_output" 2>&1; then
  printf 'expected real remote replace logic with duplicate matches to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$replace_real_ambiguous_output")" "delete_status=ambiguous"
assert_contains "$(<"$replace_real_ambiguous_output")" "download_status=success"
if [[ ! -e "$replace_remote_logic_tmp/home/.cache/huggingface/hub/a/Old-Q2_K.gguf" || ! -e "$replace_remote_logic_tmp/home/.cache/local_llm/models/b/Old-Q2_K.gguf" ]]; then
  printf 'expected ambiguous matches to leave all old files in place\n' >&2
  exit 1
fi
replace_audit_file_count="$(find "$replace_tmp/runs/replacements" -maxdepth 1 -type f -name '*.json' | wc -l | tr -d ' ')"
if [[ "$replace_audit_file_count" != 4 ]]; then
  printf 'expected dry-run, yes, failed download, and ambiguous replacement audit JSON files, got %s\n' "$replace_audit_file_count" >&2
  exit 1
fi
python3 - "$replace_tmp/runs/replacements" <<'PY'
import json
import pathlib
import sys

records = []
for path in pathlib.Path(sys.argv[1]).glob("*.json"):
    with path.open(encoding="utf-8") as handle:
        records.append(json.load(handle))
actions = sorted(record.get("action") for record in records)
if actions != ["dry-run", "replace", "replace", "replace"]:
    raise SystemExit(f"unexpected actions: {actions!r}")
download_statuses = sorted(record.get("download_status") for record in records)
if download_statuses != ["failed", "planned", "success", "success"]:
    raise SystemExit(f"unexpected download statuses: {download_statuses!r}")
delete_statuses = sorted(record.get("delete_status") for record in records)
if delete_statuses != ["ambiguous", "deleted", "not_attempted", "planned"]:
    raise SystemExit(f"unexpected delete statuses: {delete_statuses!r}")
for record in records:
    expected = {
        "old_file": "Old-Q2_K.gguf",
        "new_repo": "Example/New-GGUF",
        "selected_quant": "Q4_K_M",
        "selected_file": "New-Q4_K_M.gguf",
        "target": "remote:bench-host",
    }
    for key, value in expected.items():
        if record.get(key) != value:
            raise SystemExit(f"unexpected {key}: {record!r}")
    if not isinstance(record.get("timestamp"), str) or not record["timestamp"]:
        raise SystemExit(f"missing timestamp: {record!r}")
PY
list_invalid_target_output="$list_tmp/invalid-target.out"
if LOCAL_LLM_RUNS_DIR="$list_tmp/runs" "$repo_root/scripts/model-manager.sh" list --target remote:-bad >"$list_invalid_target_output" 2>&1; then
  printf 'expected list with unsafe remote target to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$list_invalid_target_output")" "remote target host must not start with '-'"
cat >"$list_tmp/bin/ssh" <<'EOF'
#!/usr/bin/env bash
exit 42
EOF
chmod +x "$list_tmp/bin/ssh"
list_ssh_fail_stdout="$list_tmp/ssh-fail.stdout"
list_ssh_fail_stderr="$list_tmp/ssh-fail.stderr"
PATH="$list_tmp/bin:$PATH" LOCAL_LLM_RUNS_DIR="$list_tmp/runs" "$repo_root/scripts/model-manager.sh" list --target remote:bench-host >"$list_ssh_fail_stdout" 2>"$list_ssh_fail_stderr"
assert_contains "$(<"$list_ssh_fail_stdout")" "Models"
assert_contains "$(<"$list_ssh_fail_stdout")" "Pending Selections"
assert_contains "$(<"$list_ssh_fail_stdout")" "old"
assert_contains "$(<"$list_ssh_fail_stdout")" "source: Example/Old-GGUF"
assert_contains "$(<"$list_ssh_fail_stderr")" "Warning: remote cache inventory failed for remote:bench-host"
discover_tmp="$(mktemp -d)"
discover_output="$(LOCAL_LLM_RUNS_DIR="$discover_tmp" OC_LOCAL_HF_FIXTURE="$repo_root/testdata/huggingface-model-search.json" "$repo_root/scripts/model-manager.sh" discover --target local --query "qwen coder gguf" --limit 3)"
assert_contains "$discover_output" "Model Discovery Results:"
assert_contains "$discover_output" "Hardware source: local"
assert_contains "$discover_output" "unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF"
discover_positional_output="$(LOCAL_LLM_RUNS_DIR="$discover_tmp" OC_LOCAL_HF_FIXTURE="$repo_root/testdata/huggingface-model-search.json" "$repo_root/scripts/model-manager.sh" discover qwen --target local --limit 3)"
assert_contains "$discover_positional_output" "Model Discovery Results:"
assert_contains "$discover_positional_output" "Hardware source: local"
assert_not_contains "$discover_positional_output" "Unknown discover option: qwen"
discover_missing_target_output="$discover_tmp/missing-target.out"
if "$repo_root/scripts/model-manager.sh" discover --target >"$discover_missing_target_output" 2>&1; then
  printf 'expected discover --target without value to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$discover_missing_target_output")" "--target requires local or remote:<host>"
discover_missing_query_output="$discover_tmp/missing-query.out"
if "$repo_root/scripts/model-manager.sh" discover --query >"$discover_missing_query_output" 2>&1; then
  printf 'expected discover --query without value to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$discover_missing_query_output")" "--query requires text"
discover_missing_limit_output="$discover_tmp/missing-limit.out"
if "$repo_root/scripts/model-manager.sh" discover --limit >"$discover_missing_limit_output" 2>&1; then
  printf 'expected discover --limit without value to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$discover_missing_limit_output")" "--limit requires a number"
select_tmp="$(mktemp -d)"
select_output="$(LOCAL_LLM_RUNS_DIR="$select_tmp" "$repo_root/scripts/model-manager.sh" select --repo 'Example/Foo "Bar" GGUF' --family foo --alias foo-30b --purpose 'code "chat"' --target local)"
assert_contains "$select_output" 'Selected Example/Foo "Bar" GGUF'
selection_file_count="$(find "$select_tmp/selections" -maxdepth 1 -type f -name '*.json' | wc -l | tr -d ' ')"
if [[ "$selection_file_count" != 1 ]]; then
  printf 'expected one selection file, got %s\n' "$selection_file_count" >&2
  exit 1
fi
selection_file="$(find "$select_tmp/selections" -maxdepth 1 -type f -name '*.json' -print -quit)"
python3 - "$selection_file" 'Example/Foo "Bar" GGUF' foo foo-30b 'code "chat"' local <<'PY'
import json
import sys

path, repo, family, alias, purpose, target = sys.argv[1:]
with open(path, encoding="utf-8") as handle:
    selection = json.load(handle)
expected = {
    "repo": repo,
    "family": family,
    "alias": alias,
    "purpose": purpose,
    "target": target,
}
if selection != expected:
    raise SystemExit(f"unexpected selection JSON: {selection!r}")
PY
select_positional_tmp="$(mktemp -d)"
select_positional_output="$(LOCAL_LLM_RUNS_DIR="$select_positional_tmp" "$repo_root/scripts/model-manager.sh" select unsloth/Qwen3-Coder-Next-GGUF)"
assert_contains "$select_positional_output" "Selected unsloth/Qwen3-Coder-Next-GGUF"
select_positional_file="$(find "$select_positional_tmp/selections" -maxdepth 1 -type f -name '*.json' -print -quit)"
python3 - "$select_positional_file" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    selection = json.load(handle)
expected = {
    "repo": "unsloth/Qwen3-Coder-Next-GGUF",
    "family": "qwen-coder-next",
    "alias": "qwen3-coder-next",
    "target": "local",
}
if selection != expected:
    raise SystemExit(f"unexpected positional selection JSON: {selection!r}")
PY
select_collision_tmp="$(mktemp -d)"
mkdir -p "$select_collision_tmp/bin"
cat >"$select_collision_tmp/bin/date" <<'EOF'
#!/usr/bin/env bash
printf '20260515-120000\n'
EOF
chmod +x "$select_collision_tmp/bin/date"
PATH="$select_collision_tmp/bin:$PATH" LOCAL_LLM_RUNS_DIR="$select_collision_tmp" "$repo_root/scripts/model-manager.sh" select --repo Example/Foo-GGUF --family foo --alias foo-30b --target local >/dev/null
PATH="$select_collision_tmp/bin:$PATH" LOCAL_LLM_RUNS_DIR="$select_collision_tmp" "$repo_root/scripts/model-manager.sh" select --repo Example/Foo-GGUF --family foo --alias foo-30b --target local >/dev/null
selection_collision_file_count="$(find "$select_collision_tmp/selections" -maxdepth 1 -type f -name '*.json' | wc -l | tr -d ' ')"
if [[ "$selection_collision_file_count" != 2 ]]; then
  printf 'expected two selection files for repeated selects, got %s\n' "$selection_collision_file_count" >&2
  exit 1
fi
select_missing_repo_output="$select_tmp/missing-repo.out"
if LOCAL_LLM_RUNS_DIR="$select_tmp" "$repo_root/scripts/model-manager.sh" select --family foo --alias foo-30b >"$select_missing_repo_output" 2>&1; then
  printf 'expected select without --repo to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$select_missing_repo_output")" "select requires --repo"
select_inferred_family_output="$(LOCAL_LLM_RUNS_DIR="$select_tmp/inferred-family" "$repo_root/scripts/model-manager.sh" select --repo Example/Foo-GGUF --alias foo-30b)"
assert_contains "$select_inferred_family_output" "Selected Example/Foo-GGUF"
select_inferred_family_file="$(find "$select_tmp/inferred-family/selections" -maxdepth 1 -type f -name '*.json' -print -quit)"
python3 - "$select_inferred_family_file" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    selection = json.load(handle)
if selection["family"] != "candidate" or selection["alias"] != "foo-30b":
    raise SystemExit(f"unexpected inferred family selection JSON: {selection!r}")
PY
select_inferred_alias_output="$(LOCAL_LLM_RUNS_DIR="$select_tmp/inferred-alias" "$repo_root/scripts/model-manager.sh" select --repo Example/Foo-GGUF --family foo)"
assert_contains "$select_inferred_alias_output" "Selected Example/Foo-GGUF"
select_inferred_alias_file="$(find "$select_tmp/inferred-alias/selections" -maxdepth 1 -type f -name '*.json' -print -quit)"
python3 - "$select_inferred_alias_file" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    selection = json.load(handle)
if selection["family"] != "foo" or selection["alias"] != "foo":
    raise SystemExit(f"unexpected inferred alias selection JSON: {selection!r}")
PY
select_invalid_target_output="$select_tmp/invalid-target.out"
if LOCAL_LLM_RUNS_DIR="$select_tmp" "$repo_root/scripts/model-manager.sh" select --repo Example/Foo-GGUF --family foo --alias foo-30b --target nowhere >"$select_invalid_target_output" 2>&1; then
  printf 'expected select with invalid target to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$select_invalid_target_output")" "invalid target: nowhere"
select_empty_remote_output="$select_tmp/empty-remote.out"
if LOCAL_LLM_RUNS_DIR="$select_tmp" "$repo_root/scripts/model-manager.sh" select --repo Example/Foo-GGUF --family foo --alias foo-30b --target remote: >"$select_empty_remote_output" 2>&1; then
  printf 'expected select with empty remote host to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$select_empty_remote_output")" "remote target requires a host: remote:"
benchmark_tmp="$(mktemp -d)"
benchmark_output="$(LOCAL_LLM_RUNS_DIR="$benchmark_tmp" "$repo_root/scripts/model-manager.sh" benchmark --repo Example/Foo-GGUF --family foo --alias foo-30b --profiles reliable --target local --dry-run)"
assert_contains "$benchmark_output" "Benchmark plan"
assert_contains "$benchmark_output" "repo=Example/Foo-GGUF"
assert_contains "$benchmark_output" "family=foo"
assert_contains "$benchmark_output" "target=local"
assert_contains "$benchmark_output" "profiles=reliable"
benchmark_default_output="$(LOCAL_LLM_RUNS_DIR="$benchmark_tmp" OC_LOCAL_REMOTE_HOST=bench-host "$repo_root/scripts/model-manager.sh" benchmark --repo Example/Foo-GGUF --family foo --alias foo-30b --dry-run)"
assert_contains "$benchmark_default_output" "profiles=reliable"
assert_contains "$benchmark_default_output" "target=remote:bench-host"
benchmark_positional_output="$(LOCAL_LLM_RUNS_DIR="$benchmark_tmp" "$repo_root/scripts/model-manager.sh" benchmark unsloth/Qwen3-Coder-Next-GGUF --dry-run)"
assert_contains "$benchmark_positional_output" "Benchmark plan"
assert_contains "$benchmark_positional_output" "repo=unsloth/Qwen3-Coder-Next-GGUF"
assert_contains "$benchmark_positional_output" "family=qwen-coder-next"
assert_contains "$benchmark_positional_output" "alias=qwen3-coder-next"
benchmark_dynamic_tree="$benchmark_tmp/dynamic-tree.json"
cat >"$benchmark_dynamic_tree" <<'JSON'
[
  {"type":"file","path":"Dynamic-Q5_K_M.gguf","size":23622320128},
  {"type":"file","path":"Dynamic-Q4_K_M.gguf","size":17179869184},
  {"type":"file","path":"Dynamic-Q2_K.gguf","size":8589934592}
]
JSON
benchmark_dynamic_output="$(LOCAL_LLM_RUNS_DIR="$benchmark_tmp" LOCAL_LLM_HF_TREE_FIXTURE="$benchmark_dynamic_tree" "$repo_root/scripts/model-manager.sh" benchmark Example/Dynamic-GGUF --dry-run --target remote:bench-host)"
assert_contains "$benchmark_dynamic_output" "repo=Example/Dynamic-GGUF"
assert_contains "$benchmark_dynamic_output" "quant=Q4_K_M"
assert_contains "$benchmark_dynamic_output" "hf_file=Dynamic-Q4_K_M.gguf"
benchmark_run_tmp="$(mktemp -d)"
mkdir -p "$benchmark_run_tmp/bin"
cat >"$benchmark_run_tmp/bin/ssh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
script_input="$(cat)"
printf '%s\n' "$script_input" >"$LOCAL_LLM_FAKE_SSH_SCRIPT"
printf 'load_status=success\n'
printf 'prompt_tok_s=321.5\n'
printf 'decode_tok_s=45.25\n'
printf 'prompt_tokens=128\n'
printf 'decode_tokens=256\n'
printf 'ctx=65536\n'
printf 'batch=128\n'
printf 'ubatch=128\n'
printf 'ngl=999\n'
printf 'cache_type_k=q8_0\n'
printf 'cache_type_v=q8_0\n'
printf 'command=./build/bin/llama-server -hf unsloth/Qwen3-Coder-Next-GGUF:Q3_K_M -ctk q8_0 -ctv q8_0 --alias qwen3-coder-next\n'
EOF
chmod +x "$benchmark_run_tmp/bin/ssh"
benchmark_run_output="$(PATH="$benchmark_run_tmp/bin:$PATH" LOCAL_LLM_RUNS_DIR="$benchmark_run_tmp" LOCAL_LLM_FAKE_SSH_SCRIPT="$benchmark_run_tmp/remote-script.sh" "$repo_root/scripts/model-manager.sh" benchmark unsloth/Qwen3-Coder-Next-GGUF --target remote:bench-host --cache-type-k q8_0 --cache-type-v q8_0)"
assert_contains "$benchmark_run_output" "Benchmark result"
assert_contains "$benchmark_run_output" "load_status=success"
assert_contains "$benchmark_run_output" "prompt_tok_s=321.5"
assert_contains "$benchmark_run_output" "decode_tok_s=45.25"
assert_contains "$(<"$benchmark_run_tmp/remote-script.sh")" "llama-server"
assert_contains "$(<"$benchmark_run_tmp/remote-script.sh")" "current-model.env"
assert_contains "$(<"$benchmark_run_tmp/remote-script.sh")" "systemctl --user restart llama-server.service"
assert_contains "$(<"$benchmark_run_tmp/remote-script.sh")" "http://127.0.0.1:\${port}/v1/chat/completions"
assert_contains "$(<"$benchmark_run_tmp/remote-script.sh")" "-ctk"
assert_contains "$(<"$benchmark_run_tmp/remote-script.sh")" "-ctv"
assert_contains "$(<"$benchmark_run_tmp/remote-script.sh")" '== \~/*'
assert_not_contains "$(<"$benchmark_run_tmp/remote-script.sh")" '== ~/*'
assert_contains "$(<"$benchmark_run_tmp/remote-script.sh")" "printf -v command_text_part '%q'"
assert_contains "$(<"$benchmark_run_tmp/remote-script.sh")" "(^|:)[[:space:]]+eval time"
assert_not_contains "$(<"$benchmark_run_tmp/remote-script.sh")" "eval.*tokens per second"
assert_contains "$(<"$benchmark_run_tmp/remote-script.sh")" '\"max_tokens\":512'
assert_not_contains "$(<"$benchmark_run_tmp/remote-script.sh")" "Reply with exactly: ok"
benchmark_run_file="$(find "$benchmark_run_tmp/benchmarks" -maxdepth 1 -type f -name '*.json' -print -quit)"
python3 - "$benchmark_run_file" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    result = json.load(handle)
expected = {
    "target": "remote:bench-host",
    "repo": "unsloth/Qwen3-Coder-Next-GGUF",
    "family": "qwen-coder-next",
    "alias": "qwen3-coder-next",
    "profile": "reliable",
    "ctx": 65536,
    "batch": 128,
    "ubatch": 128,
    "ngl": 999,
    "load_status": "success",
    "prompt_tok_s": 321.5,
    "decode_tok_s": 45.25,
    "prompt_tokens": 128,
    "decode_tokens": 256,
}
for key, value in expected.items():
    if result[key] != value:
        raise SystemExit(f"unexpected {key}: {result[key]!r}")
if "llama-server" not in result["command"]:
    raise SystemExit(f"missing command: {result!r}")
if result.get("cache_type_k") != "q8_0" or result.get("cache_type_v") != "q8_0":
    raise SystemExit(f"unexpected cache types: {result!r}")
PY
cat >"$benchmark_run_tmp/bin/ssh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
cat >>"$LOCAL_LLM_FAKE_SSH_SCRIPT"
printf 'load_status=success\n'
printf 'prompt_tok_s=222.0\n'
printf 'decode_tok_s=44.0\n'
printf 'prompt_tokens=128\n'
printf 'decode_tokens=256\n'
printf 'ctx=32768\n'
printf 'batch=128\n'
printf 'ubatch=64\n'
printf 'ngl=999\n'
printf 'backend=vulkan\n'
printf 'visible_devices=0,1\n'
printf 'split_mode=layer\n'
printf 'tensor_split=44,1\n'
printf 'command=GGML_VK_VISIBLE_DEVICES=0,1 ./build-vulkan/bin/llama-server --split-mode layer --tensor-split 44,1 --parallel 1 --no-cont-batching --alias qwen3-coder-next\n'
EOF
chmod +x "$benchmark_run_tmp/bin/ssh"
benchmark_vulkan_output="$(PATH="$benchmark_run_tmp/bin:$PATH" LOCAL_LLM_RUNS_DIR="$benchmark_run_tmp/vulkan-runs" LOCAL_LLM_FAKE_SSH_SCRIPT="$benchmark_run_tmp/vulkan-remote-script.sh" "$repo_root/scripts/model-manager.sh" benchmark unsloth/Qwen3-Coder-Next-GGUF --target remote:bench-host --backend vulkan --visible-devices 0,1 --split-mode layer --tensor-split 44,1 --ctx 131072 --batch 64 --ubatch 64)"
assert_contains "$benchmark_vulkan_output" "Benchmark result"
assert_contains "$benchmark_vulkan_output" "load_status=success"
assert_contains "$(<"$benchmark_run_tmp/vulkan-remote-script.sh")" "export GGML_VK_VISIBLE_DEVICES"
assert_contains "$(<"$benchmark_run_tmp/vulkan-remote-script.sh")" "./build-vulkan/bin/llama-server"
assert_contains "$(<"$benchmark_run_tmp/vulkan-remote-script.sh")" "--split-mode"
assert_contains "$(<"$benchmark_run_tmp/vulkan-remote-script.sh")" "--tensor-split"
assert_contains "$(<"$benchmark_run_tmp/vulkan-remote-script.sh")" "--parallel"
assert_contains "$(<"$benchmark_run_tmp/vulkan-remote-script.sh")" "--no-cont-batching"
benchmark_vulkan_file="$(find "$benchmark_run_tmp/vulkan-runs/benchmarks" -maxdepth 1 -type f -name '*.json' -print -quit)"
python3 - "$benchmark_vulkan_file" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    result = json.load(handle)
expected = {
    "backend": "vulkan",
    "visible_devices": "0,1",
    "split_mode": "layer",
    "tensor_split": "44,1",
    "ctx": 32768,
    "batch": 128,
    "ubatch": 64,
}
for key, value in expected.items():
    if result.get(key) != value:
        raise SystemExit(f"unexpected {key}: {result!r}")
PY
cat >"$benchmark_run_tmp/bin/ssh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
cat >>"$LOCAL_LLM_FAKE_SSH_SCRIPT"
printf 'load_status=success\n'
printf 'prompt_tok_s=240.0\n'
printf 'decode_tok_s=88.0\n'
printf 'prompt_tokens=128\n'
printf 'decode_tokens=256\n'
printf 'ctx=65536\n'
printf 'batch=128\n'
printf 'ubatch=128\n'
printf 'ngl=999\n'
printf 'backend=rocm\n'
printf 'visible_devices=0,1\n'
printf 'split_mode=row\n'
printf 'tensor_split=1,1\n'
printf 'ctx_shift=on\n'
printf 'command=HIP_VISIBLE_DEVICES=0,1 ROCR_VISIBLE_DEVICES=0,1 ./build/bin/llama-server --split-mode row --tensor-split 1,1 --context-shift --alias qwen3-coder-next\n'
EOF
chmod +x "$benchmark_run_tmp/bin/ssh"
benchmark_rocm_output="$(PATH="$benchmark_run_tmp/bin:$PATH" LOCAL_LLM_RUNS_DIR="$benchmark_run_tmp/rocm-runs" LOCAL_LLM_FAKE_SSH_SCRIPT="$benchmark_run_tmp/rocm-remote-script.sh" "$repo_root/scripts/model-manager.sh" benchmark unsloth/Qwen3-Coder-Next-GGUF --target remote:bench-host --backend rocm --visible-devices 0,1 --split-mode row --tensor-split 1,1 --ctx-shift on)"
assert_contains "$benchmark_rocm_output" "Benchmark result"
assert_contains "$(<"$benchmark_run_tmp/rocm-remote-script.sh")" "export HIP_VISIBLE_DEVICES"
assert_contains "$(<"$benchmark_run_tmp/rocm-remote-script.sh")" "export ROCR_VISIBLE_DEVICES"
assert_contains "$(<"$benchmark_run_tmp/rocm-remote-script.sh")" "--context-shift"
benchmark_rocm_file="$(find "$benchmark_run_tmp/rocm-runs/benchmarks" -maxdepth 1 -type f -name '*.json' -print -quit)"
python3 - "$benchmark_rocm_file" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    result = json.load(handle)
expected = {
    "backend": "rocm",
    "visible_devices": "0,1",
    "split_mode": "row",
    "tensor_split": "1,1",
    "ctx_shift": "on",
}
for key, value in expected.items():
    if result.get(key) != value:
        raise SystemExit(f"unexpected {key}: {result!r}")
PY
if "$repo_root/scripts/model-manager.sh" benchmark Example/Bad --target remote:bench-host --ctx-shift '../../bad' >/tmp/local-llm-bad-ctx-shift.out 2>&1; then
  printf 'expected invalid ctx-shift benchmark option to fail\n' >&2
  exit 1
fi
assert_contains "$(</tmp/local-llm-bad-ctx-shift.out)" "invalid ctx shift"
cat >"$benchmark_run_tmp/bin/ssh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
cat >>"$LOCAL_LLM_FAKE_SSH_SCRIPT"
printf 'load_status=success\n'
printf 'prompt_tok_s=100.0\n'
printf 'decode_tok_s=50.0\n'
printf 'prompt_tokens=128\n'
printf 'decode_tokens=256\n'
printf 'ctx=65536\n'
printf 'batch=128\n'
printf 'ubatch=128\n'
printf 'ngl=999\n'
printf 'command=./build/bin/llama-server -hf Example/Dynamic-GGUF --hf-file Dynamic-Q4_K_M.gguf --alias dynamic\n'
EOF
chmod +x "$benchmark_run_tmp/bin/ssh"
benchmark_full_output="$(PATH="$benchmark_run_tmp/bin:$PATH" LOCAL_LLM_RUNS_DIR="$benchmark_run_tmp/full-runs" LOCAL_LLM_HF_TREE_FIXTURE="$benchmark_dynamic_tree" LOCAL_LLM_FAKE_SSH_SCRIPT="$benchmark_run_tmp/full-remote-script.sh" "$repo_root/scripts/model-manager.sh" benchmark Example/Dynamic-GGUF --full --target remote:bench-host)"
assert_contains "$benchmark_full_output" "Full benchmark result"
assert_contains "$benchmark_full_output" "Full benchmark start"
assert_contains "$benchmark_full_output" "trials=7"
assert_contains "$benchmark_full_output" "running trial=1/7 profile=speed ctx=32768 batch=256 ubatch=256"
assert_contains "$benchmark_full_output" "trial=1 profile=speed"
assert_contains "$benchmark_full_output" "recommendation=best-overall"
assert_contains "$benchmark_full_output" "decode_tokens=256"
assert_contains "$(<"$benchmark_run_tmp/full-remote-script.sh")" "current-model.env"
assert_contains "$(<"$benchmark_run_tmp/full-remote-script.sh")" "systemctl --user restart llama-server.service"
benchmark_full_file="$(find "$benchmark_run_tmp/full-runs/benchmarks" -maxdepth 1 -type f -name '*.json' -print -quit)"
python3 - "$benchmark_full_file" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    result = json.load(handle)
if result.get("mode") != "full":
    raise SystemExit(f"expected full mode: {result!r}")
trials = result.get("trials")
if not isinstance(trials, list) or len(trials) < 5:
    raise SystemExit(f"expected multiple trials: {result!r}")
for trial in trials:
    for key in ("profile", "ctx", "batch", "ubatch", "prompt_tokens", "decode_tokens", "decode_tok_s"):
        if key not in trial:
            raise SystemExit(f"missing {key}: {trial!r}")
recommendations = result.get("recommendations")
if not isinstance(recommendations, dict) or "best-overall" not in recommendations:
    raise SystemExit(f"missing recommendations: {result!r}")
PY
cat >"$benchmark_run_tmp/bin/ssh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
cat >/dev/null
printf 'load_status=timeout\n'
printf 'prompt_tok_s=\n'
printf 'decode_tok_s=\n'
printf 'ctx=65536\n'
printf 'batch=128\n'
printf 'ubatch=128\n'
printf 'ngl=999\n'
printf 'command=./build/bin/llama-server -hf unsloth/Qwen3-Coder-Next-GGUF --alias qwen3-coder-next\n'
EOF
chmod +x "$benchmark_run_tmp/bin/ssh"
benchmark_timeout_output="$(PATH="$benchmark_run_tmp/bin:$PATH" LOCAL_LLM_RUNS_DIR="$benchmark_run_tmp" "$repo_root/scripts/model-manager.sh" benchmark unsloth/Qwen3-Coder-Next-GGUF --target remote:bench-host)"
assert_contains "$benchmark_timeout_output" "Benchmark did not complete"
assert_contains "$benchmark_timeout_output" "load_status=timeout"
assert_contains "$benchmark_timeout_output" "reason=model did not become ready or did not emit throughput metrics"
benchmark_record_tmp="$(mktemp -d)"
record_output="$(LOCAL_LLM_RUNS_DIR="$benchmark_record_tmp" "$repo_root/scripts/model-manager.sh" benchmark --repo Example/Foo-GGUF --family foo --alias foo-30b --profiles reliable --target local --record-only)"
assert_contains "$record_output" "Wrote benchmark result"
benchmark_file_count="$(find "$benchmark_record_tmp/benchmarks" -maxdepth 1 -type f -name '*.json' | wc -l | tr -d ' ')"
if [[ "$benchmark_file_count" != 1 ]]; then
  printf 'expected one benchmark file, got %s\n' "$benchmark_file_count" >&2
  exit 1
fi
benchmark_file="$(find "$benchmark_record_tmp/benchmarks" -maxdepth 1 -type f -name '*.json' -print -quit)"
python3 - "$benchmark_file" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    result = json.load(handle)
expected_keys = {
    "target", "repo", "family", "alias", "profile", "ctx", "batch", "ubatch", "ngl",
    "load_status", "prompt_tok_s", "decode_tok_s", "command", "timestamp",
}
if set(result) != expected_keys:
    raise SystemExit(f"unexpected benchmark keys: {sorted(result)}")
expected_values = {
    "target": "local",
    "repo": "Example/Foo-GGUF",
    "family": "foo",
    "alias": "foo-30b",
    "profile": "reliable",
    "load_status": "not_run",
    "prompt_tok_s": None,
    "decode_tok_s": None,
}
for key, value in expected_values.items():
    if result[key] != value:
        raise SystemExit(f"unexpected {key}: {result[key]!r}")
PY
benchmark_multi_tmp="$(mktemp -d)"
multi_record_output="$(LOCAL_LLM_RUNS_DIR="$benchmark_multi_tmp" "$repo_root/scripts/model-manager.sh" benchmark --repo Example/Foo-GGUF --family foo --alias foo-30b --profiles speed,reliable --target local --record-only)"
assert_contains "$multi_record_output" "Wrote benchmark result"
benchmark_multi_file_count="$(find "$benchmark_multi_tmp/benchmarks" -maxdepth 1 -type f -name '*.json' | wc -l | tr -d ' ')"
if [[ "$benchmark_multi_file_count" != 2 ]]; then
  printf 'expected two benchmark files, got %s\n' "$benchmark_multi_file_count" >&2
  exit 1
fi
python3 - "$benchmark_multi_tmp/benchmarks" <<'PY'
import json
import pathlib
import sys

benchmark_dir = pathlib.Path(sys.argv[1])
results = []
for path in benchmark_dir.glob("*.json"):
    with path.open(encoding="utf-8") as handle:
        result = json.load(handle)
    if "/" in path.name or "," in result["profile"]:
        raise SystemExit(f"unsafe benchmark result: {path.name} {result!r}")
    results.append(result)
profiles = sorted(result["profile"] for result in results)
if profiles != ["reliable", "speed"]:
    raise SystemExit(f"unexpected benchmark profiles: {profiles!r}")
if any(result["load_status"] != "not_run" for result in results):
    raise SystemExit(f"unexpected load status: {results!r}")
if any(result["prompt_tok_s"] is not None or result["decode_tok_s"] is not None for result in results):
    raise SystemExit(f"expected null token rates: {results!r}")
PY
benchmark_bad_profile_tmp="$(mktemp -d)"
benchmark_bad_profile_output="$benchmark_bad_profile_tmp/bad-profile.out"
if LOCAL_LLM_RUNS_DIR="$benchmark_bad_profile_tmp" "$repo_root/scripts/model-manager.sh" benchmark --repo Example/Foo-GGUF --family foo --alias foo-30b --profiles bad/profile --target local --record-only >"$benchmark_bad_profile_output" 2>&1; then
  printf 'expected benchmark with invalid profile path segment to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$benchmark_bad_profile_output")" "invalid benchmark profile: bad/profile"
benchmark_bad_profile_count="$(find "$benchmark_bad_profile_tmp/benchmarks" -maxdepth 1 -type f -name '*.json' 2>/dev/null | wc -l | tr -d ' ')"
if [[ "$benchmark_bad_profile_count" != 0 ]]; then
  printf 'expected invalid benchmark profile to write no files, got %s\n' "$benchmark_bad_profile_count" >&2
  exit 1
fi
benchmark_empty_entry_output="$benchmark_tmp/empty-profile-entry.out"
if LOCAL_LLM_RUNS_DIR="$benchmark_tmp" "$repo_root/scripts/model-manager.sh" benchmark --repo Example/Foo-GGUF --family foo --alias foo-30b --profiles speed,,reliable --target local --record-only >"$benchmark_empty_entry_output" 2>&1; then
  printf 'expected benchmark with empty profile entry to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$benchmark_empty_entry_output")" "--profiles contains an empty profile"
benchmark_trailing_empty_entry_output="$benchmark_tmp/trailing-empty-profile-entry.out"
if LOCAL_LLM_RUNS_DIR="$benchmark_tmp" "$repo_root/scripts/model-manager.sh" benchmark --repo Example/Foo-GGUF --family foo --alias foo-30b --profiles speed, --target local --record-only >"$benchmark_trailing_empty_entry_output" 2>&1; then
  printf 'expected benchmark with trailing empty profile entry to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$benchmark_trailing_empty_entry_output")" "--profiles contains an empty profile"
benchmark_missing_repo_output="$benchmark_tmp/missing-repo.out"
if LOCAL_LLM_RUNS_DIR="$benchmark_tmp" "$repo_root/scripts/model-manager.sh" benchmark --family foo --alias foo-30b --dry-run >"$benchmark_missing_repo_output" 2>&1; then
  printf 'expected benchmark without --repo to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$benchmark_missing_repo_output")" "benchmark requires --repo"
benchmark_inferred_family_output="$(LOCAL_LLM_RUNS_DIR="$benchmark_tmp" "$repo_root/scripts/model-manager.sh" benchmark --repo Example/Foo-GGUF --alias foo-30b --target local --dry-run)"
assert_contains "$benchmark_inferred_family_output" "Benchmark plan"
assert_contains "$benchmark_inferred_family_output" "family=foo"
assert_contains "$benchmark_inferred_family_output" "alias=foo-30b"
benchmark_qwopus_family_output="$(LOCAL_LLM_RUNS_DIR="$benchmark_tmp" "$repo_root/scripts/model-manager.sh" benchmark --repo Jackrong/Qwopus3.6-27B-v2-MTP-GGUF --target local --dry-run)"
assert_contains "$benchmark_qwopus_family_output" "family=qwopus3.6-27b-v2-mtp"
assert_contains "$benchmark_qwopus_family_output" "alias=qwopus3.6-27b-v2-mtp"
benchmark_inferred_alias_output="$(LOCAL_LLM_RUNS_DIR="$benchmark_tmp" "$repo_root/scripts/model-manager.sh" benchmark --repo Example/Foo-GGUF --family foo --target local --dry-run)"
assert_contains "$benchmark_inferred_alias_output" "Benchmark plan"
assert_contains "$benchmark_inferred_alias_output" "family=foo"
assert_contains "$benchmark_inferred_alias_output" "alias=foo"
benchmark_invalid_target_output="$benchmark_tmp/invalid-target.out"
if LOCAL_LLM_RUNS_DIR="$benchmark_tmp" "$repo_root/scripts/model-manager.sh" benchmark --repo Example/Foo-GGUF --family foo --alias foo-30b --target nowhere --dry-run >"$benchmark_invalid_target_output" 2>&1; then
  printf 'expected benchmark with invalid target to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$benchmark_invalid_target_output")" "invalid target: nowhere"
benchmark_profiles_flag_value_output="$benchmark_tmp/profiles-flag-value.out"
if LOCAL_LLM_RUNS_DIR="$benchmark_tmp" "$repo_root/scripts/model-manager.sh" benchmark --repo Example/Foo-GGUF --family foo --alias foo-30b --profiles --dry-run >"$benchmark_profiles_flag_value_output" 2>&1; then
  printf 'expected benchmark --profiles without a value to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$benchmark_profiles_flag_value_output")" "--profiles requires a non-empty value"
benchmark_empty_profiles_output="$benchmark_tmp/empty-profiles.out"
if LOCAL_LLM_RUNS_DIR="$benchmark_tmp" "$repo_root/scripts/model-manager.sh" benchmark --repo Example/Foo-GGUF --family foo --alias foo-30b --profiles '' --dry-run >"$benchmark_empty_profiles_output" 2>&1; then
  printf 'expected benchmark with empty --profiles to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$benchmark_empty_profiles_output")" "--profiles requires a non-empty value"
accept_tmp="$(mktemp -d)"
accept_runs="$accept_tmp/runs"
cat >"$accept_tmp/foo.json" <<'EOF'
{"repo":"Example/Foo-GGUF","family":"foo","alias":"foo-30b","target":"local","profile":"reliable","load_status":"success"}
EOF
accept_output="$(LOCAL_LLM_RUNS_DIR="$accept_runs" "$repo_root/scripts/model-manager.sh" accept "$accept_tmp/foo.json" --dry-run)"
assert_contains "$accept_output" "Accept plan"
assert_contains "$accept_output" "family=foo"
assert_contains "$accept_output" "alias=foo-30b"
assert_not_contains "$accept_output" "would update scripts/oc-local"
assert_contains "$accept_output" "launcher_file=$accept_runs/launchers/start"
assert_contains "$accept_output" "would create $accept_runs/launchers/start"
assert_contains "$accept_output" "would write accepted metadata under $accept_runs/accepted"
cat >"$accept_tmp/full.json" <<'EOF'
{"mode":"full","target":"remote:bench-host","repo":"Example/Full-GGUF","family":"full","alias":"full-next","quant":"Q4_K_M","hf_file":"Full-Q4_K_M.gguf","recommendations":{"best-overall":{"profile":"reliable","ctx":65536,"batch":128,"ubatch":64,"ngl":999,"load_status":"success","decode_tok_s":76.8,"decode_tokens":512}}}
EOF
cat >"$accept_tmp/vulkan.json" <<'EOF'
{"mode":"full","target":"remote:bench-host","repo":"Example/Vulkan-GGUF","family":"vulkan","alias":"vulkan-split","quant":"Q4_K_M","hf_file":"Vulkan-Q4_K_M.gguf","cache_type_k":"q8_0","cache_type_v":"q8_0","recommendations":{"best-overall":{"profile":"reliable","ctx":65536,"batch":128,"ubatch":64,"ngl":999,"backend":"vulkan","visible_devices":"0,1","split_mode":"layer","tensor_split":"20,24","cache_type_k":"q8_0","cache_type_v":"q8_0","load_status":"success","decode_tok_s":76.8,"decode_tokens":512}}}
EOF
cat >"$accept_tmp/bad-alias.json" <<'EOF'
{"mode":"full","target":"remote:bench-host","repo":"Example/Bad-GGUF","family":"badalias","alias":"bad\"alias","quant":"Q4_K_M","hf_file":"Bad-Q4_K_M.gguf","recommendations":{"best-overall":{"profile":"reliable","ctx":65536,"batch":128,"ubatch":64,"ngl":999,"load_status":"success","decode_tok_s":76.8,"decode_tokens":512}}}
EOF
accept_bad_alias_runs="$accept_tmp/bad-alias-runs"
accept_bad_alias_output="$accept_tmp/bad-alias.out"
if LOCAL_LLM_RUNS_DIR="$accept_bad_alias_runs" "$repo_root/scripts/model-manager.sh" accept "$accept_tmp/bad-alias.json" >"$accept_bad_alias_output" 2>&1; then
  printf 'expected accept with unsafe alias to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$accept_bad_alias_output")" "benchmark JSON field contains an unsafe alias: alias"
if [[ -e "$accept_bad_alias_runs/accepted/badalias.json" ]]; then
  printf 'accept wrote accepted metadata for unsafe alias\n' >&2
  exit 1
fi
cp "$repo_root/scripts/local-llm-switcher.py" "$accept_tmp/local-llm-switcher.before"
accept_full_start="$accept_runs/launchers/start98.sh"
rm -f "$accept_full_start"
accept_full_output="$(LOCAL_LLM_RUNS_DIR="$accept_runs" LOCAL_LLM_ACCEPT_START_SCRIPT="$accept_full_start" "$repo_root/scripts/model-manager.sh" accept "$accept_tmp/full.json")"
assert_contains "$accept_full_output" "Accepted benchmark"
assert_contains "$accept_full_output" "launcher_file=$accept_full_start"
assert_contains "$accept_full_output" "start_script=$accept_full_start"
assert_contains "$accept_full_output" "accepted_metadata_file=$accept_runs/accepted/full.json"
assert_contains "$accept_full_output" "profile=reliable"
assert_not_contains "$accept_full_output" "Dry-run actions"
assert_not_contains "$accept_full_output" "would update scripts/oc-local"
if [[ ! -f "$accept_full_start" ]]; then
  printf 'expected generated launcher at %s\n' "$accept_full_start" >&2
  exit 1
fi
assert_contains "$(<"$accept_full_start")" '--hf-file Full-Q4_K_M.gguf'
assert_contains "$(<"$accept_full_start")" "-c \"\$ctx\""
assert_contains "$(<"$accept_full_start")" 'ctx=65536'
assert_contains "$(<"$accept_full_start")" 'batch=128'
assert_contains "$(<"$accept_full_start")" 'ubatch=64'
# shellcheck disable=SC2016
assert_contains "$(<"$accept_full_start")" 'script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"'
# shellcheck disable=SC2016
assert_contains "$(<"$accept_full_start")" 'log_file="${LOCAL_LLM_MODEL_LOG:-$script_dir/model.log}"'
# shellcheck disable=SC2016
assert_contains "$(<"$accept_full_start")" 'exec > >(tee "$log_file") 2>&1'
cmp -s "$repo_root/scripts/local-llm-switcher.py" "$accept_tmp/local-llm-switcher.before"
if [[ ! -f "$accept_runs/accepted/full.json" ]]; then
  printf 'expected accepted metadata at family path %s\n' "$accept_runs/accepted/full.json" >&2
  exit 1
fi
if [[ -e "$accept_runs/accepted/full-next.json" ]]; then
  printf 'expected no alias-named accepted metadata duplicate\n' >&2
  exit 1
fi
accept_full_info="$(LOCAL_LLM_RUNS_DIR="$accept_runs" "$repo_root/scripts/oc-local" full reliable --info)"
assert_contains "$accept_full_info" "family=full"
assert_contains "$accept_full_info" "profile=reliable"
assert_contains "$accept_full_info" "remote_start=./start98.sh reliable"
assert_contains "$accept_full_info" "model_name=full-next"
accept_vulkan_runs="$accept_tmp/vulkan-runs"
accept_vulkan_start="$accept_vulkan_runs/launchers/start1.sh"
accept_vulkan_output="$(LOCAL_LLM_RUNS_DIR="$accept_vulkan_runs" LOCAL_LLM_ACCEPT_START_SCRIPT="$accept_vulkan_start" "$repo_root/scripts/model-manager.sh" accept "$accept_tmp/vulkan.json")"
assert_contains "$accept_vulkan_output" "Accepted benchmark"
assert_contains "$accept_vulkan_output" "launcher_file=$accept_vulkan_start"
if [[ ! -f "$accept_vulkan_start" ]]; then
  printf 'expected generated Vulkan launcher at %s\n' "$accept_vulkan_start" >&2
  exit 1
fi
assert_contains "$(<"$accept_vulkan_start")" 'export GGML_VK_VISIBLE_DEVICES=0,1'
assert_contains "$(<"$accept_vulkan_start")" './build-vulkan/bin/llama-server'
assert_contains "$(<"$accept_vulkan_start")" '--split-mode layer'
assert_contains "$(<"$accept_vulkan_start")" '--tensor-split 20,24'
assert_contains "$(<"$accept_vulkan_start")" '-ctk q8_0'
assert_contains "$(<"$accept_vulkan_start")" '-ctv q8_0'
python3 - "$accept_vulkan_runs/accepted/vulkan.json" "$accept_vulkan_start" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    accepted = json.load(handle)
expected_config = {
    "ctx": 65536,
    "batch": 128,
    "ubatch": 64,
    "ngl": 999,
    "backend": "vulkan",
    "visible_devices": "0,1",
    "split_mode": "layer",
    "tensor_split": "20,24",
    "cache_type_k": "q8_0",
    "cache_type_v": "q8_0",
}
if accepted.get("config") != expected_config:
    raise SystemExit(f"unexpected Vulkan config: {accepted.get('config')!r}")
if accepted.get("launcher_file") != sys.argv[2]:
    raise SystemExit(f"unexpected Vulkan launcher file: {accepted.get('launcher_file')!r}")
PY
accept_vulkan_info="$(LOCAL_LLM_RUNS_DIR="$accept_vulkan_runs" "$repo_root/scripts/oc-local" vulkan reliable --info)"
assert_contains "$accept_vulkan_info" "backend=vulkan"
assert_contains "$accept_vulkan_info" "visible_devices=0,1"
assert_contains "$accept_vulkan_info" "split_mode=layer"
assert_contains "$accept_vulkan_info" "tensor_split=20,24"
assert_contains "$accept_vulkan_info" "GGML_VK_VISIBLE_DEVICES=0,1"
assert_contains "$accept_vulkan_info" "./build-vulkan/bin/llama-server"
assert_contains "$accept_vulkan_info" "--split-mode layer"
assert_contains "$accept_vulkan_info" "--tensor-split 20,24"
accept_bad_repo_runs="$accept_tmp/bad-repo-runs"
mkdir -p "$accept_bad_repo_runs/accepted"
cat >"$accept_bad_repo_runs/accepted/badrepo.json" <<'EOF'
{"repo":"Example/Bad-GGUF\nremote_start=./shifted.sh","family":"badrepo","alias":"badrepo","remote_start":"./start98.sh","quant":"Q4_K_M","profile":"reliable","config":{"ctx":65536,"batch":128,"ubatch":64,"ngl":999}}
EOF
accept_bad_repo_output="$accept_tmp/bad-repo.out"
if LOCAL_LLM_RUNS_DIR="$accept_bad_repo_runs" "$repo_root/scripts/oc-local" badrepo reliable --info >"$accept_bad_repo_output" 2>&1; then
  printf 'expected oc-local to reject accepted repo containing newline\n' >&2
  exit 1
fi
assert_contains "$(<"$accept_bad_repo_output")" "invalid accepted metadata"
assert_not_contains "$(<"$accept_bad_repo_output")" "remote_start=./shifted.sh"
assert_not_contains "$(<"$accept_bad_repo_output")" "OPENCODE_CONFIG_CONTENT"
accept_bad_quant_runs="$accept_tmp/bad-quant-runs"
mkdir -p "$accept_bad_quant_runs/accepted"
cat >"$accept_bad_quant_runs/accepted/badquant.json" <<'EOF'
{"repo":"Example/Bad-GGUF","family":"badquant","alias":"badquant","remote_start":"./start98.sh","quant":"Q4_K_M\nremote_start=./shifted.sh","profile":"reliable","config":{"ctx":65536,"batch":128,"ubatch":64,"ngl":999}}
EOF
accept_bad_quant_output="$accept_tmp/bad-quant.out"
if LOCAL_LLM_RUNS_DIR="$accept_bad_quant_runs" "$repo_root/scripts/oc-local" badquant reliable --info >"$accept_bad_quant_output" 2>&1; then
  printf 'expected oc-local to reject accepted quant containing newline\n' >&2
  exit 1
fi
assert_contains "$(<"$accept_bad_quant_output")" "invalid accepted metadata"
assert_not_contains "$(<"$accept_bad_quant_output")" "remote_start=./shifted.sh"
accept_full_repeat_output="$(LOCAL_LLM_RUNS_DIR="$accept_runs" "$repo_root/scripts/model-manager.sh" accept "$accept_tmp/full.json")"
assert_contains "$accept_full_repeat_output" "Accepted benchmark already has launcher"
assert_contains "$accept_full_repeat_output" "start_script=$accept_full_start"
assert_contains "$accept_full_repeat_output" "accepted_metadata_file=$accept_runs/accepted/full.json"
if [[ -e "$accept_runs/launchers/start99.sh" ]]; then
  printf 'expected repeated accept to reuse existing generated launcher, not create start99.sh\n' >&2
  exit 1
fi
cat >"$accept_tmp/full-new-alias.json" <<'EOF'
{"mode":"full","target":"remote:bench-host","repo":"Example/Full-GGUF","family":"full","alias":"full-different","quant":"Q4_K_M","hf_file":"Full-Q4_K_M.gguf","recommendations":{"best-overall":{"profile":"reliable","ctx":65536,"batch":128,"ubatch":64,"ngl":999,"load_status":"success","decode_tok_s":76.8,"decode_tokens":512}}}
EOF
accept_alias_mismatch_metadata_before="$(<"$accept_runs/accepted/full.json")"
accept_alias_mismatch_launcher_before="$(<"$accept_full_start")"
accept_alias_mismatch_output="$accept_tmp/alias-mismatch.out"
if LOCAL_LLM_RUNS_DIR="$accept_runs" "$repo_root/scripts/model-manager.sh" accept "$accept_tmp/full-new-alias.json" >"$accept_alias_mismatch_output" 2>&1; then
  printf 'expected accept with existing family metadata but different alias to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$accept_alias_mismatch_output")" "accepted metadata alias mismatch for family full"
assert_contains "$(<"$accept_alias_mismatch_output")" "existing_alias=full-next"
assert_contains "$(<"$accept_alias_mismatch_output")" "requested_alias=full-different"
if [[ "$(<"$accept_runs/accepted/full.json")" != "$accept_alias_mismatch_metadata_before" ]]; then
  printf 'accept alias mismatch mutated accepted metadata\n' >&2
  exit 1
fi
if [[ "$(<"$accept_full_start")" != "$accept_alias_mismatch_launcher_before" ]]; then
  printf 'accept alias mismatch mutated existing launcher\n' >&2
  exit 1
fi
if [[ -e "$accept_runs/launchers/start99.sh" ]]; then
  printf 'accept alias mismatch created a new launcher\n' >&2
  exit 1
fi
python3 - "$accept_runs/accepted/full.json" "$accept_full_start" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    accepted = json.load(handle)
expected = {
    "repo": "Example/Full-GGUF",
    "hf_repo": "Example/Full-GGUF",
    "family": "full",
    "alias": "full-next",
    "model_name": "full-next",
    "remote_start": "./start98.sh",
    "launcher_file": sys.argv[2],
    "hf_file": "Full-Q4_K_M.gguf",
    "quant": "Q4_K_M",
    "profile": "reliable",
    "target": "remote:bench-host",
    "config": {"ctx": 65536, "batch": 128, "ubatch": 64, "ngl": 999},
}
if accepted != expected:
    raise SystemExit(f"unexpected accepted metadata: {accepted!r}")
PY
rm -f "$accept_full_start"
cat >"$accept_tmp/qwen-coder-next-full.json" <<'EOF'
{"mode":"full","target":"remote:bench-host","repo":"unsloth/Qwen3-Coder-Next-GGUF","family":"qwen-coder","alias":"qwen3-coder-next","quant":"UD-TQ1_0","hf_file":"Qwen3-Coder-Next-UD-TQ1_0.gguf","recommendations":{"best-overall":{"profile":"reliable","ctx":65536,"batch":64,"ubatch":64,"ngl":999,"load_status":"success","decode_tok_s":76.8,"decode_tokens":512}}}
EOF
accept_existing_runs="$accept_tmp/existing-runs"
mkdir -p "$accept_existing_runs/selections"
printf '{"repo":"unsloth/Qwen3-Coder-Next-GGUF","family":"qwen-coder","alias":"qwen3-coder-next","target":"remote:bench-host"}\n' >"$accept_existing_runs/selections/qcn.json"
accept_existing_output="$(LOCAL_LLM_RUNS_DIR="$accept_existing_runs" "$repo_root/scripts/model-manager.sh" accept "$accept_tmp/qwen-coder-next-full.json")"
assert_contains "$accept_existing_output" "Accepted benchmark"
assert_contains "$accept_existing_output" "start_script=$accept_existing_runs/launchers/start1.sh"
assert_contains "$accept_existing_output" "accepted_metadata_file=$accept_existing_runs/accepted/qwen-coder.json"
assert_contains "$accept_existing_output" "removed_selection_count=1"
assert_not_contains "$accept_existing_output" "scripts/start98.sh"
python3 - "$accept_existing_runs/accepted/qwen-coder.json" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as handle:
    accepted = json.load(handle)
if accepted.get("target") != "remote:bench-host":
    raise SystemExit(f"expected accepted target to be preserved: {accepted!r}")
PY
deploy_output="$(LOCAL_LLM_RUNS_DIR="$accept_existing_runs" "$repo_root/scripts/model-manager.sh" deploy --target remote:bench-host --dry-run)"
assert_contains "$deploy_output" "Deploy plan"
assert_contains "$deploy_output" "target=remote:bench-host"
assert_contains "$deploy_output" "remote_dir=~/llama.cpp"
assert_contains "$deploy_output" "replace /home/<user>/llama.cpp with the absolute path on the GPU host"
assert_contains "$deploy_output" "start1.sh"
assert_contains "$deploy_output" "bench-host:"
assert_contains "$deploy_output" "copy launcher"
assert_contains "$deploy_output" "local-llm-switcher.py"
assert_contains "$deploy_output" "local-llm-switcher.service"
assert_contains "$deploy_output" "opencode-web.service"
assert_contains "$deploy_output" "Caddyfile.local-llm"
assert_contains "$deploy_output" "required env file: ~/.config/local_llm/opencode-web.env"
assert_contains "$deploy_output" "OPENCODE_WEB_COMMAND='<replace-with-your-opencode-web-command> --host 127.0.0.1 --port 3002'"
assert_contains "$deploy_output" "required env file: ~/.config/local_llm/local-llm-switcher.env"
assert_contains "$deploy_output" "LLAMA_DIR=/home/<user>/llama.cpp"
assert_not_contains "$deploy_output" "LLAMA_DIR=~/llama.cpp"
assert_contains "$deploy_output" "LOCAL_LLM_WEB_UPSTREAM"
assert_contains "$deploy_output" "LOCAL_LLM_WEB_UPSTREAM=http://127.0.0.1:3002"
assert_contains "$deploy_output" "LOCAL_LLM_INJECT_TARGET=opencode"
assert_not_contains "$deploy_output" "open-webui"
deploy_remote_dir_output="$(LOCAL_LLM_RUNS_DIR="$accept_existing_runs" OC_LOCAL_REMOTE_DIR=/srv/llama "$repo_root/scripts/model-manager.sh" deploy --target remote:bench-host --dry-run)"
assert_contains "$deploy_remote_dir_output" "remote_dir=/srv/llama"
assert_contains "$deploy_remote_dir_output" "LLAMA_DIR=/srv/llama"
assert_not_contains "$deploy_remote_dir_output" "replace /home/<user>/llama.cpp with the absolute path on the GPU host"
assert_contains "$deploy_remote_dir_output" "LOCAL_LLM_WEB_UPSTREAM=http://127.0.0.1:3002"
assert_contains "$deploy_remote_dir_output" "required env file: ~/.config/local_llm/opencode-web.env"
assert_contains "$deploy_remote_dir_output" "required env file: ~/.config/local_llm/local-llm-switcher.env"
deploy_empty_tmp="$(mktemp -d)"
deploy_empty_runs="$deploy_empty_tmp/runs"
deploy_empty_output="$(LOCAL_LLM_RUNS_DIR="$deploy_empty_runs" "$repo_root/scripts/model-manager.sh" deploy --target remote:bench-host --dry-run)"
assert_contains "$deploy_empty_output" "Nothing to deploy"
assert_contains "$deploy_empty_output" "no accepted models"
if [[ -e "$deploy_empty_runs" ]]; then
  printf 'deploy --dry-run created local state at %s\n' "$deploy_empty_runs" >&2
  exit 1
fi
deploy_unsafe_runs="$accept_tmp/deploy-unsafe-runs"
mkdir -p "$deploy_unsafe_runs/accepted" "$deploy_unsafe_runs/launchers"
cp "$accept_existing_runs/accepted/qwen-coder.json" "$deploy_unsafe_runs/accepted/qwen-coder.json"
cp "$accept_existing_runs/launchers/start1.sh" "$deploy_unsafe_runs/launchers/start1.sh"
python3 - "$deploy_unsafe_runs/accepted/qwen-coder.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    metadata = json.load(handle)
metadata["family"] = "qwen\tcoder"
metadata["alias"] = "qwen\nnext"
metadata["model_name"] = "qwen\nnext"
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump(metadata, handle)
    handle.write("\n")
PY
deploy_unsafe_output="$accept_tmp/deploy-unsafe.out"
if LOCAL_LLM_RUNS_DIR="$deploy_unsafe_runs" "$repo_root/scripts/model-manager.sh" deploy --target remote:bench-host --dry-run >"$deploy_unsafe_output" 2>&1; then
  printf 'expected deploy dry-run with unsafe accepted metadata labels to fail\n' >&2
  exit 1
fi
deploy_unsafe_contents="$(<"$deploy_unsafe_output")"
assert_contains "$deploy_unsafe_contents" "invalid accepted metadata"
assert_contains "$deploy_unsafe_contents" "family contains unsafe characters"
assert_not_contains "$deploy_unsafe_contents" "qwen next"
deploy_bin="$accept_tmp/deploy-bin"
mkdir -p "$deploy_bin"
cat >"$deploy_bin/scp" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf 'scp %s\n' "$*" >>"$LOCAL_LLM_DEPLOY_LOG"
EOF
cat >"$deploy_bin/ssh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf 'ssh %s\n' "$*" >>"$LOCAL_LLM_DEPLOY_LOG"
EOF
chmod +x "$deploy_bin/scp" "$deploy_bin/ssh"
deploy_real_log="$accept_tmp/deploy-real.log"
deploy_real_output="$(PATH="$deploy_bin:$PATH" LOCAL_LLM_DEPLOY_LOG="$deploy_real_log" LOCAL_LLM_RUNS_DIR="$accept_existing_runs" "$repo_root/scripts/model-manager.sh" deploy --target remote:bench-host)"
assert_contains "$deploy_real_output" "Deploy complete"
assert_contains "$deploy_real_output" "current=start1.sh profile=reliable"
assert_contains "$(<"$deploy_real_log")" "scp $accept_existing_runs/launchers/start1.sh bench-host:~/llama.cpp/start1.sh"
assert_contains "$(<"$deploy_real_log")" "run-current-model.sh"
assert_contains "$(<"$deploy_real_log")" "systemctl --user restart llama-server.service"
deploy_yes_log="$accept_tmp/deploy-yes.log"
deploy_yes_output="$(PATH="$deploy_bin:$PATH" LOCAL_LLM_DEPLOY_LOG="$deploy_yes_log" LOCAL_LLM_RUNS_DIR="$accept_existing_runs" "$repo_root/scripts/model-manager.sh" deploy --target remote:bench-host --yes)"
assert_contains "$deploy_yes_output" "Deploy complete"
deploy_local_output="$accept_tmp/deploy-local.out"
if LOCAL_LLM_RUNS_DIR="$accept_existing_runs" "$repo_root/scripts/model-manager.sh" deploy --target local --dry-run >"$deploy_local_output" 2>&1; then
  printf 'expected deploy local target to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$deploy_local_output")" "deploy currently requires --target remote:<host>"
cmp -s "$repo_root/scripts/local-llm-switcher.py" "$accept_tmp/local-llm-switcher.before"
if [[ -e "$accept_existing_runs/selections/qcn.json" ]]; then
  printf 'expected accept to remove matching selection file\n' >&2
  exit 1
fi
accept_symlink_accepted_runs="$accept_tmp/symlink-accepted-runs"
accept_symlink_accepted_outside="$accept_tmp/symlink-accepted-outside"
mkdir -p "$accept_symlink_accepted_runs" "$accept_symlink_accepted_outside"
ln -s "$accept_symlink_accepted_outside" "$accept_symlink_accepted_runs/accepted"
accept_symlink_accepted_output="$accept_tmp/symlink-accepted.out"
if LOCAL_LLM_RUNS_DIR="$accept_symlink_accepted_runs" "$repo_root/scripts/model-manager.sh" accept "$accept_tmp/full.json" >"$accept_symlink_accepted_output" 2>&1; then
  printf 'expected accept with symlinked accepted dir to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$accept_symlink_accepted_output")" "refuses symlinked accepted dir"
if [[ -e "$accept_symlink_accepted_outside/full.json" ]]; then
  printf 'accept wrote through symlinked accepted dir\n' >&2
  exit 1
fi
accept_symlink_launcher_runs="$accept_tmp/symlink-launcher-runs"
accept_symlink_launcher_outside="$accept_tmp/symlink-launcher-outside"
mkdir -p "$accept_symlink_launcher_runs" "$accept_symlink_launcher_outside"
ln -s "$accept_symlink_launcher_outside" "$accept_symlink_launcher_runs/launchers"
accept_symlink_launcher_output="$accept_tmp/symlink-launcher.out"
if LOCAL_LLM_RUNS_DIR="$accept_symlink_launcher_runs" "$repo_root/scripts/model-manager.sh" accept "$accept_tmp/full.json" >"$accept_symlink_launcher_output" 2>&1; then
  printf 'expected accept with symlinked launchers dir to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$accept_symlink_launcher_output")" "refuses symlinked launchers dir"
shopt -s nullglob dotglob
accept_symlink_launcher_outside_entries=("$accept_symlink_launcher_outside"/*)
shopt -u nullglob dotglob
if ((${#accept_symlink_launcher_outside_entries[@]} > 0)); then
  printf 'accept wrote through symlinked launchers dir\n' >&2
  exit 1
fi
accept_metadata_symlink_runs="$accept_tmp/metadata-symlink-runs"
accept_metadata_symlink_outside="$accept_tmp/metadata-symlink-outside.json"
mkdir -p "$accept_metadata_symlink_runs/accepted"
ln -s "$accept_metadata_symlink_outside" "$accept_metadata_symlink_runs/accepted/full.json"
accept_metadata_symlink_output="$accept_tmp/metadata-symlink.out"
if LOCAL_LLM_RUNS_DIR="$accept_metadata_symlink_runs" "$repo_root/scripts/model-manager.sh" accept "$accept_tmp/full.json" >"$accept_metadata_symlink_output" 2>&1; then
  printf 'expected accept with symlinked accepted metadata file to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$accept_metadata_symlink_output")" "refuses symlinked state file"
if [[ -e "$accept_metadata_symlink_outside" ]]; then
  printf 'accept wrote through symlinked accepted metadata file\n' >&2
  exit 1
fi
accept_override_symlink_parent="$accept_tmp/override-symlink-parent"
accept_override_symlink_outside="$accept_tmp/override-symlink-outside"
mkdir -p "$accept_override_symlink_outside"
ln -s "$accept_override_symlink_outside" "$accept_override_symlink_parent"
accept_override_symlink_output="$accept_tmp/override-symlink.out"
if LOCAL_LLM_RUNS_DIR="$accept_tmp/override-runs" LOCAL_LLM_ACCEPT_START_SCRIPT="$accept_override_symlink_parent/start99.sh" "$repo_root/scripts/model-manager.sh" accept "$accept_tmp/full.json" >"$accept_override_symlink_output" 2>&1; then
  printf 'expected accept with symlinked override parent dir to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$accept_override_symlink_output")" "launcher path must be under runs launchers dir"
if [[ -e "$accept_override_symlink_outside/start99.sh" ]]; then
  printf 'accept wrote launcher through symlinked override parent dir\n' >&2
  exit 1
fi
accept_override_symlink_ancestor_runs="$accept_tmp/override-symlink-ancestor-runs"
accept_override_symlink_ancestor_outside="$accept_tmp/override-symlink-ancestor-outside"
mkdir -p "$accept_override_symlink_ancestor_runs/launchers" "$accept_override_symlink_ancestor_outside"
ln -s "$accept_override_symlink_ancestor_outside" "$accept_override_symlink_ancestor_runs/launchers/nested"
accept_override_symlink_ancestor_output="$accept_tmp/override-symlink-ancestor.out"
if LOCAL_LLM_RUNS_DIR="$accept_override_symlink_ancestor_runs" LOCAL_LLM_ACCEPT_START_SCRIPT="$accept_override_symlink_ancestor_runs/launchers/nested/deeper/start99.sh" "$repo_root/scripts/model-manager.sh" accept "$accept_tmp/full.json" >"$accept_override_symlink_ancestor_output" 2>&1; then
  printf 'expected accept with symlinked override ancestor dir to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$accept_override_symlink_ancestor_output")" "refuses symlinked runs path component"
if [[ -e "$accept_override_symlink_ancestor_outside/deeper/start99.sh" ]]; then
  printf 'accept wrote launcher through symlinked override ancestor dir\n' >&2
  exit 1
fi
cp "$repo_root/scripts/oc-local" "$accept_tmp/oc-local.before"
cp "$repo_root/installer.sh" "$accept_tmp/installer.before"
cp "$repo_root/README.md" "$accept_tmp/README.before"
cp "$repo_root/test_oc_local.sh" "$accept_tmp/test_oc_local.before"
accept_start08="$accept_runs/launchers/start08.sh"
mkdir -p "${accept_start08%/*}"
printf '#!/usr/bin/env bash\n' >"$accept_start08"
accept_start08_output="$(LOCAL_LLM_RUNS_DIR="$accept_runs" "$repo_root/scripts/model-manager.sh" accept "$accept_tmp/foo.json" --dry-run)"
assert_contains "$accept_start08_output" "would create $accept_runs/launchers/start"
cmp -s "$repo_root/scripts/oc-local" "$accept_tmp/oc-local.before"
cmp -s "$repo_root/installer.sh" "$accept_tmp/installer.before"
cmp -s "$repo_root/README.md" "$accept_tmp/README.before"
cmp -s "$repo_root/test_oc_local.sh" "$accept_tmp/test_oc_local.before"
cat >"$accept_tmp/invalid.json" <<'EOF'
{"repo":
EOF
accept_invalid_output="$accept_tmp/invalid.out"
if "$repo_root/scripts/model-manager.sh" accept "$accept_tmp/invalid.json" --dry-run >"$accept_invalid_output" 2>&1; then
  printf 'expected accept with invalid JSON to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$accept_invalid_output")" "benchmark JSON is invalid"
assert_not_contains "$(<"$accept_invalid_output")" "Traceback"
printf '[]\n' >"$accept_tmp/non-object.json"
accept_non_object_output="$accept_tmp/non-object.out"
if "$repo_root/scripts/model-manager.sh" accept "$accept_tmp/non-object.json" --dry-run >"$accept_non_object_output" 2>&1; then
  printf 'expected accept with non-object JSON to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$accept_non_object_output")" "benchmark JSON must be an object"
assert_not_contains "$(<"$accept_non_object_output")" "Traceback"
cat >"$accept_tmp/missing-family.json" <<'EOF'
{"repo":"Example/Foo-GGUF","alias":"foo-30b","target":"local","profile":"reliable","load_status":"success"}
EOF
accept_missing_output="$accept_tmp/missing-family.out"
if "$repo_root/scripts/model-manager.sh" accept "$accept_tmp/missing-family.json" --dry-run >"$accept_missing_output" 2>&1; then
  printf 'expected accept with missing family to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$accept_missing_output")" "benchmark JSON missing required field: family"
cat >"$accept_tmp/bad-family.json" <<'EOF'
{"repo":"Example/Foo-GGUF","family":30,"alias":"foo-30b","target":"local","profile":"reliable","load_status":"success"}
EOF
accept_bad_family_output="$accept_tmp/bad-family.out"
if "$repo_root/scripts/model-manager.sh" accept "$accept_tmp/bad-family.json" --dry-run >"$accept_bad_family_output" 2>&1; then
  printf 'expected accept with non-string family to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$accept_bad_family_output")" "benchmark JSON field must be a string: family"
cat >"$accept_tmp/unsafe-family.json" <<'EOF'
{"repo":"Example/Foo-GGUF","family":"../escape","alias":"foo-30b","target":"local","profile":"reliable","load_status":"success","ctx":1,"batch":1,"ubatch":1,"ngl":1,"quant":"Q4"}
EOF
accept_unsafe_family_runs="$accept_tmp/unsafe-family-runs"
accept_unsafe_family_output="$accept_tmp/unsafe-family.out"
if LOCAL_LLM_RUNS_DIR="$accept_unsafe_family_runs" "$repo_root/scripts/model-manager.sh" accept "$accept_tmp/unsafe-family.json" >"$accept_unsafe_family_output" 2>&1; then
  printf 'expected accept with unsafe family to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$accept_unsafe_family_output")" "benchmark JSON field contains an unsafe family: family"
if [[ -e "$accept_unsafe_family_runs/accepted/escape.json" ]]; then
  printf 'accept wrote sanitized metadata for unsafe family\n' >&2
  exit 1
fi
python3 - "$accept_tmp/control.json" <<'PY'
import json
import sys

with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump(
        {
            "repo": "Example/Foo-GGUF",
            "family": "foo\nbar",
            "alias": "foo-30b",
            "target": "local",
            "profile": "reliable",
            "load_status": "success",
        },
        handle,
    )
    handle.write("\n")
PY
accept_control_output="$accept_tmp/control.out"
if "$repo_root/scripts/model-manager.sh" accept "$accept_tmp/control.json" --dry-run >"$accept_control_output" 2>&1; then
  printf 'expected accept with control character to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$accept_control_output")" "benchmark JSON field contains a control character: family"
python3 - "$accept_tmp/hf-file-tab.json" <<'PY'
import json
import sys

with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump(
        {
            "mode": "full",
            "target": "remote:bench-host",
            "repo": "Example/HfFileTab-GGUF",
            "family": "hf-file-tab",
            "alias": "hf-file-tab",
            "quant": "Q4_K_M",
            "hf_file": "HfFile\tQ4_K_M.gguf",
            "recommendations": {
                "best-overall": {
                    "profile": "reliable",
                    "ctx": 65536,
                    "batch": 128,
                    "ubatch": 64,
                    "ngl": 999,
                    "load_status": "success",
                    "decode_tok_s": 76.8,
                    "decode_tokens": 512,
                }
            },
        },
        handle,
    )
    handle.write("\n")
PY
accept_hf_file_tab_runs="$accept_tmp/hf-file-tab-runs"
accept_hf_file_tab_output="$accept_tmp/hf-file-tab.out"
if LOCAL_LLM_RUNS_DIR="$accept_hf_file_tab_runs" "$repo_root/scripts/model-manager.sh" accept "$accept_tmp/hf-file-tab.json" >"$accept_hf_file_tab_output" 2>&1; then
  printf 'expected accept with tab in hf_file to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$accept_hf_file_tab_output")" "benchmark JSON field contains a control character: hf_file"
if [[ -e "$accept_hf_file_tab_runs/accepted/hf-file-tab.json" ]]; then
  printf 'accept wrote metadata for hf_file containing tab\n' >&2
  exit 1
fi
if [[ -d "$accept_hf_file_tab_runs/launchers" ]]; then
  shopt -s nullglob
  accept_hf_file_tab_launchers=("$accept_hf_file_tab_runs/launchers"/start*.sh)
  shopt -u nullglob
  if ((${#accept_hf_file_tab_launchers[@]} > 0)); then
    printf 'accept wrote launcher for hf_file containing tab\n' >&2
    exit 1
  fi
fi
python3 - "$accept_tmp/quant-tab.json" <<'PY'
import json
import sys

with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump(
        {
            "repo": "Example/QuantTab-GGUF",
            "family": "quant-tab",
            "alias": "quant-tab",
            "target": "local",
            "profile": "reliable",
            "load_status": "success",
            "ctx": 65536,
            "batch": 128,
            "ubatch": 64,
            "ngl": 999,
            "quant": "Q4\tK_M",
        },
        handle,
    )
    handle.write("\n")
PY
accept_quant_tab_runs="$accept_tmp/quant-tab-runs"
accept_quant_tab_output="$accept_tmp/quant-tab.out"
if LOCAL_LLM_RUNS_DIR="$accept_quant_tab_runs" "$repo_root/scripts/model-manager.sh" accept "$accept_tmp/quant-tab.json" >"$accept_quant_tab_output" 2>&1; then
  printf 'expected accept with tab in quant to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$accept_quant_tab_output")" "benchmark JSON field contains a control character: quant"
if [[ -e "$accept_quant_tab_runs/accepted/quant-tab.json" ]]; then
  printf 'accept wrote metadata for quant containing tab\n' >&2
  exit 1
fi
if [[ -d "$accept_quant_tab_runs/launchers" ]]; then
  shopt -s nullglob
  accept_quant_tab_launchers=("$accept_quant_tab_runs/launchers"/start*.sh)
  shopt -u nullglob
  if ((${#accept_quant_tab_launchers[@]} > 0)); then
    printf 'accept wrote launcher for quant containing tab\n' >&2
    exit 1
  fi
fi
delete_profile_tmp="$(mktemp -d)"
cat >"$delete_profile_tmp/profiles.json" <<'JSON'
{
  "families": {
    "gemma": {},
    "gemma-vision": {}
  },
  "profiles": {
    "gemma:reliable": {"family":"gemma","hf_repo":"unsloth/gemma-4-31B-it-GGUF"},
    "gemma-vision:speed": {"family":"gemma-vision","hf_repo":"unsloth/gemma-4-31B-it-GGUF"},
    "gemma-vision:fastlong": {"family":"gemma-vision","hf_repo":"unsloth/gemma-4-31B-it-GGUF"},
    "gemma-vision:balanced": {"family":"gemma-vision","hf_repo":"unsloth/gemma-4-31B-it-GGUF"},
    "gemma-vision:reliable": {"family":"gemma-vision","hf_repo":"unsloth/gemma-4-31B-it-GGUF"},
    "gemma-vision:tiny": {"family":"gemma-vision","hf_repo":"unsloth/gemma-4-31B-it-GGUF"}
  }
}
JSON
delete_profile_dry_output="$(LOCAL_LLM_PROFILES_JSON="$delete_profile_tmp/profiles.json" "$repo_root/scripts/model-manager.sh" delete --profile 'gemma-vision:*' --target remote:bench-host --dry-run)"
assert_contains "$delete_profile_dry_output" "Delete profile dry-run"
assert_contains "$delete_profile_dry_output" "profile_pattern=gemma-vision:*"
assert_contains "$delete_profile_dry_output" "matched_profile=gemma-vision:balanced repo=unsloth/gemma-4-31B-it-GGUF"
assert_contains "$delete_profile_dry_output" "matched_profile=gemma-vision:tiny repo=unsloth/gemma-4-31B-it-GGUF"
assert_contains "$delete_profile_dry_output" "cache_action=keep repo=unsloth/gemma-4-31B-it-GGUF remaining_refs=1"
delete_profile_yes_output="$(LOCAL_LLM_PROFILES_JSON="$delete_profile_tmp/profiles.json" "$repo_root/scripts/model-manager.sh" delete --profile 'gemma-vision:*' --target remote:bench-host --yes)"
assert_contains "$delete_profile_yes_output" "Delete profile result"
assert_contains "$delete_profile_yes_output" "removed_profile_count=5"
python3 - "$delete_profile_tmp/profiles.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    profiles = json.load(handle)["profiles"]
if any(key.startswith("gemma-vision:") for key in profiles):
    raise SystemExit("gemma-vision profiles were not removed")
if not any(key.startswith("gemma:") for key in profiles):
    raise SystemExit("gemma profiles should remain")
PY
delete_repo_tmp="$(mktemp -d)"
mkdir -p "$delete_repo_tmp/bin" "$delete_repo_tmp/home/.cache/huggingface/hub/models--Qwen--Qwen3-30B-A3B-GGUF/blobs" "$delete_repo_tmp/home/.cache/huggingface/hub/models--Qwen--Qwen3-30B-A3B-GGUF/snapshots/rev" "$delete_repo_tmp/home/.cache/huggingface/hub/models--Other--Keep-GGUF/snapshots/rev"
cat >"$delete_repo_tmp/bin/ssh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
args=("$@")
for i in "${!args[@]}"; do
  if [[ "${args[$i]}" == python3 ]]; then
    HOME="$LOCAL_LLM_FAKE_REMOTE_HOME" exec "${args[@]:$i}"
  fi
done
printf 'unexpected fake ssh command: %s\n' "$*" >&2
exit 1
EOF
chmod +x "$delete_repo_tmp/bin/ssh"
printf 'blob-data\n' >"$delete_repo_tmp/home/.cache/huggingface/hub/models--Qwen--Qwen3-30B-A3B-GGUF/blobs/blob1"
printf 'snapshot-data\n' >"$delete_repo_tmp/home/.cache/huggingface/hub/models--Qwen--Qwen3-30B-A3B-GGUF/snapshots/rev/Qwen3-30B-A3B-Q4_K_M.gguf"
printf 'keep\n' >"$delete_repo_tmp/home/.cache/huggingface/hub/models--Other--Keep-GGUF/snapshots/rev/Keep.gguf"
delete_repo_dry_output="$(PATH="$delete_repo_tmp/bin:$PATH" LOCAL_LLM_FAKE_REMOTE_HOME="$delete_repo_tmp/home" "$repo_root/scripts/model-manager.sh" delete Qwen/Qwen3-30B-A3B-GGUF --target remote:bench-host --dry-run)"
assert_contains "$delete_repo_dry_output" '"action":"plan"'
assert_contains "$delete_repo_dry_output" '"repo":"Qwen/Qwen3-30B-A3B-GGUF"'
assert_contains "$delete_repo_dry_output" '"kind":"hf_repo_cache"'
assert_contains "$delete_repo_dry_output" '"planned":1'
if [[ ! -e "$delete_repo_tmp/home/.cache/huggingface/hub/models--Qwen--Qwen3-30B-A3B-GGUF/blobs/blob1" ]]; then
  printf 'dry-run deleted Hugging Face blob cache\n' >&2
  exit 1
fi
delete_repo_yes_output="$(PATH="$delete_repo_tmp/bin:$PATH" LOCAL_LLM_FAKE_REMOTE_HOME="$delete_repo_tmp/home" "$repo_root/scripts/model-manager.sh" delete Qwen/Qwen3-30B-A3B-GGUF --target remote:bench-host --yes)"
assert_contains "$delete_repo_yes_output" '"action":"delete"'
assert_contains "$delete_repo_yes_output" '"kind":"hf_repo_cache"'
assert_contains "$delete_repo_yes_output" '"planned":1'
assert_contains "$delete_repo_yes_output" '"deleted":1'
if [[ -e "$delete_repo_tmp/home/.cache/huggingface/hub/models--Qwen--Qwen3-30B-A3B-GGUF" ]]; then
  printf 'delete left Hugging Face repo cache directory in place\n' >&2
  exit 1
fi
if [[ ! -e "$delete_repo_tmp/home/.cache/huggingface/hub/models--Other--Keep-GGUF/snapshots/rev/Keep.gguf" ]]; then
  printf 'delete removed unrelated Hugging Face repo cache\n' >&2
  exit 1
fi
cat >"$accept_tmp/failed-load.json" <<'EOF'
{"repo":"Example/Foo-GGUF","family":"foo","alias":"foo-30b","target":"local","profile":"reliable","load_status":"failed"}
EOF
accept_failed_load_output="$accept_tmp/failed-load.out"
if "$repo_root/scripts/model-manager.sh" accept "$accept_tmp/failed-load.json" --dry-run >"$accept_failed_load_output" 2>&1; then
  printf 'expected accept with unsuccessful load_status to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$accept_failed_load_output")" "benchmark JSON load_status is not success: failed"
installer_contents="$(<"$repo_root/installer.sh")"
assert_contains "$installer_contents" "Installing generated convenience commands"
assert_contains "$installer_contents" "RUNS_DIR/accepted"
assert_contains "$installer_contents" "create_wrapper \"oc-\${family}-\${profile}\""
installer_help_output="$("$repo_root/installer.sh" --help 2>&1)"
assert_contains "$installer_help_output" "./installer.sh -p ~/.local/bin/localllm"
assert_not_contains "$installer_help_output" "/Users/cass"
assert_not_contains "$installer_contents" "oc-qwen-mtp"
assert_not_contains "$installer_contents" "oc-qwen-hauhau"
assert_not_contains "$installer_contents" "oc-qwen-hauhau-ses-2009"
assert_not_contains "$installer_contents" "ses_2009bfccfffeEVdvBAajurVOi4"
assert_not_contains "$installer_contents" "oc-coder-next"
assert_contains "$installer_contents" "scripts/model-manager.sh"

installer_tmp="$(mktemp -d)"
installer_bin="$installer_tmp/bin"
installer_share="$installer_tmp/share"
mkdir -p "$installer_bin"
printf '#!/usr/bin/env bash\n' >"$installer_bin/oc-qwen-reliable"
printf '#!/usr/bin/env bash\n' >"$installer_bin/oc-coder-reliable"
printf '#!/usr/bin/env bash\n' >"$installer_bin/oc-gemma-reliable"
printf '#!/usr/bin/env bash\n' >"$installer_bin/oc-user-command"
printf '#!/usr/bin/env bash\nexec oc-local custom reliable "$@"\n' >"$installer_bin/oc-my-model"
LOCAL_LLM_SHARE_DIR="$installer_share" "$repo_root/installer.sh" -p "$installer_bin" >/dev/null
if [[ -e "$installer_bin/oc-qwen-reliable" || -e "$installer_bin/oc-coder-reliable" || -e "$installer_bin/oc-gemma-reliable" ]]; then
  printf 'installer left stale generated wrappers in core-only mode\n' >&2
  exit 1
fi
if [[ ! -f "$installer_bin/oc-user-command" ]]; then
  printf 'installer removed unrelated oc-* user command\n' >&2
  exit 1
fi
if [[ ! -f "$installer_bin/oc-my-model" ]]; then
  printf 'installer removed unrelated oc-* user wrapper mentioning oc-local\n' >&2
  exit 1
fi
if [[ ! -x "$installer_bin/oc-local" ]]; then
  printf 'installer did not preserve installed oc-local binary\n' >&2
  exit 1
fi

installer_accept_tmp="$(mktemp -d)"
installer_accept_bin="$installer_accept_tmp/bin"
installer_accept_share="$installer_accept_tmp/share"
mkdir -p "$installer_accept_share/runs/accepted"
cat >"$installer_accept_share/runs/accepted/custom.json" <<'JSON'
{"family":"custom","profile":"reliable","target":"remote:bench-host"}
JSON
LOCAL_LLM_SHARE_DIR="$installer_accept_share" "$repo_root/installer.sh" -p "$installer_accept_bin" >/dev/null
if [[ ! -x "$installer_accept_bin/oc-custom-reliable" || ! -x "$installer_accept_bin/oc-custom" ]]; then
  printf 'installer did not generate accepted-state wrappers\n' >&2
  exit 1
fi
assert_contains "$(<"$installer_accept_bin/oc-custom-reliable")" "# local_llm generated wrapper"
printf '#!/usr/bin/env bash\n# local_llm generated wrapper\nexec old-wrapper\n' >"$installer_accept_bin/oc-custom-reliable"
LOCAL_LLM_SHARE_DIR="$installer_accept_share" "$repo_root/installer.sh" -p "$installer_accept_bin" >/dev/null
assert_contains "$(<"$installer_accept_bin/oc-custom-reliable")" "remote_host=\"\${OC_LOCAL_REMOTE_HOST:-bench-host}\""
assert_contains "$(<"$installer_accept_bin/oc-custom-reliable")" "OC_LOCAL_BASE_URL=\"\${OC_LOCAL_BASE_URL:-http://\$remote_host:8080/v1}\""
assert_contains "$(<"$installer_accept_bin/oc-custom-reliable")" "--remote \"\$remote_host\""

probe_tmp="$(mktemp -d)"
trap 'rm -rf "$probe_tmp" "$manager_tmp" "$discover_tmp" "$select_tmp" "$select_collision_tmp" "$benchmark_tmp" "$benchmark_record_tmp" "$benchmark_multi_tmp" "$benchmark_bad_profile_tmp" "$accept_tmp" "$installer_tmp" "$installer_accept_tmp"' EXIT
cat >"$probe_tmp/curl" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
url="${*: -1}"
case "$url" in
  *limit=12*)
    printf '[{"id":"FetchOrg/Fetch-16B-GGUF","downloads":1,"tags":["gguf"]}]\n'
    ;;
  *)
    printf 'expected Hugging Face fetch URL to request at least display limit, got: %s\n' "$url" >&2
    exit 1
    ;;
esac
EOF
chmod +x "$probe_tmp/curl"
fetch_limit_output="$(PATH="$probe_tmp:$PATH" OC_LOCAL_REMOTE_HOST=__none__ OC_LOCAL_HF_FETCH_LIMIT=3 "$repo_root/scripts/model-discovery.sh" --limit 12)"
assert_contains "$fetch_limit_output" "FetchOrg/Fetch-16B-GGUF"
cat >"$probe_tmp/ssh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
command_text="${*: -1}"
case "$command_text" in
  nproc)
    printf '16\n'
    ;;
  *free*)
    printf '64\n'
    ;;
  *rocminfo*)
    exit 0
    ;;
  *rocm-smi*)
    exit 0
    ;;
  *llama-server*)
    printf 'llama-server device 0: AMD Radeon RX 7900 XT (gfx1100) - 24560 MiB VRAM\n'
    ;;
  *)
    printf 'unknown\n'
    ;;
esac
EOF
chmod +x "$probe_tmp/ssh"
remote_fallback_output="$(PATH="$probe_tmp:$PATH" OC_LOCAL_HF_FIXTURE="$repo_root/testdata/huggingface-model-search.json" "$repo_root/scripts/model-discovery.sh" --host fake-host --installed-only)"
assert_contains "$remote_fallback_output" "Hardware source: remote:fake-host"
assert_contains "$remote_fallback_output" "CPU Cores: 16"
assert_contains "$remote_fallback_output" "RAM: 64 GB"
assert_contains "$remote_fallback_output" "GPU: unknown"

cat >"$probe_tmp/ssh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
command_text="${*: -1}"
case "$command_text" in
  nproc|*free*)
    exit 0
    ;;
  *rocminfo*)
    exit 0
    ;;
  *rocm-smi*)
    exit 0
    ;;
  *llama-server*)
    printf 'llama-server device 1: AMD Radeon PRO W7900 (gfx1100) - 48000 MiB VRAM\n'
    ;;
  *)
    printf 'unknown\n'
    ;;
esac
EOF
chmod +x "$probe_tmp/ssh"
remote_missing_cpu_output="$(PATH="$probe_tmp:$PATH" OC_LOCAL_HF_FIXTURE="$repo_root/testdata/huggingface-model-search.json" "$repo_root/scripts/model-discovery.sh" --host cpu-missing-host --installed-only)"
assert_contains "$remote_missing_cpu_output" "Hardware source: remote:cpu-missing-host"
assert_contains "$remote_missing_cpu_output" "CPU Cores: unknown"
assert_contains "$remote_missing_cpu_output" "RAM: unknown GB"
assert_contains "$remote_missing_cpu_output" "GPU: unknown"

cat >"$probe_tmp/ssh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
command_text="${*: -1}"
case "$command_text" in
  nproc|*free*|*rocminfo*|*rocm-smi*)
    exit 0
    ;;
  *"cd 'quote'\\''safe'"*)
    printf 'llama-server device 2: quoted remote dir GPU (gfx1100) - 24560 MiB VRAM\n'
    ;;
  *llama-server*)
    printf 'unsafe remote dir quoting: %s\n' "$command_text"
    ;;
  *)
    printf 'unknown\n'
    ;;
esac
EOF
chmod +x "$probe_tmp/ssh"
remote_quoted_dir_output="$(PATH="$probe_tmp:$PATH" OC_LOCAL_REMOTE_DIR="quote'safe" OC_LOCAL_HF_FIXTURE="$repo_root/testdata/huggingface-model-search.json" "$repo_root/scripts/model-discovery.sh" --host quoted-dir-host --installed-only)"
assert_contains "$remote_quoted_dir_output" "GPU: unknown"
assert_not_contains "$remote_quoted_dir_output" "unsafe remote dir quoting"

cat >"$probe_tmp/ssh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
command_text="${*: -1}"
case "$command_text" in
  nproc)
    printf '16\n'
    ;;
  *free*)
    printf '64\n'
    ;;
  *rocminfo*Marketing*)
    printf 'AMD Radeon RX 7900 XT\n'
    ;;
  *rocminfo*gfx*)
    printf 'gfx1100\n'
    ;;
  *rocm-smi*|*llama-server*)
    exit 0
    ;;
  *)
    printf 'unknown\n'
    ;;
esac
EOF
chmod +x "$probe_tmp/ssh"
remote_rocminfo_gpu_output="$(PATH="$probe_tmp:$PATH" OC_LOCAL_HF_FIXTURE="$repo_root/testdata/huggingface-model-search.json" "$repo_root/scripts/model-discovery.sh" --host rocminfo-gpu-host --installed-only)"
assert_contains "$remote_rocminfo_gpu_output" "GPU: AMD Radeon RX 7900 XT"
assert_not_contains "$remote_rocminfo_gpu_output" "GPU: Intel"

cat >"$probe_tmp/ssh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
command_text="${*: -1}"
case "$command_text" in
  nproc)
    printf '16\n'
    ;;
  *free*)
    printf '60\n'
    ;;
  *rocminfo*Marketing*)
    printf 'AMD Radeon RX 7900 XT\n'
    ;;
  *mem_info_vram_total*)
    printf '21474836480\n'
    ;;
  *nvidia-smi*)
    printf 'NVIDIA Tesla P40, 24576\n'
    ;;
  *vulkaninfo*)
    printf 'GPU0:\n\tdeviceName = AMD Radeon RX 7900 XT\nGPU1:\n\tdeviceName = NVIDIA Tesla P40\n'
    ;;
  *)
    printf 'unknown\n'
    ;;
esac
EOF
chmod +x "$probe_tmp/ssh"
remote_multi_gpu_output="$(PATH="$probe_tmp:$PATH" OC_LOCAL_HF_FIXTURE="$repo_root/testdata/huggingface-model-search.json" "$repo_root/scripts/model-discovery.sh" --host multi-gpu-host --installed-only)"
assert_contains "$remote_multi_gpu_output" "Hardware source: remote:multi-gpu-host"
assert_contains "$remote_multi_gpu_output" "GPU: AMD Radeon RX 7900 XT"
assert_contains "$remote_multi_gpu_output" "VRAM: 20 GB"
assert_contains "$remote_multi_gpu_output" "- GPUs: AMD Radeon RX 7900 XT (20 GB); NVIDIA Tesla P40 (24 GB)"
assert_contains "$remote_multi_gpu_output" "- Total VRAM: 44 GB"
assert_contains "$remote_multi_gpu_output" "ROCm target: yes"
assert_contains "$remote_multi_gpu_output" "- CUDA target: yes"
assert_contains "$remote_multi_gpu_output" "- Vulkan target: yes"

cat >"$probe_tmp/ssh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
command_text="${*: -1}"
case "$command_text" in
  nproc)
    printf '16\n'
    ;;
  *free*)
    printf '60\n'
    ;;
  *rocminfo*Marketing*head\ -1*)
    printf 'AMD Radeon RX 7900 XT\n'
    ;;
  *rocminfo*Marketing*)
    printf 'AMD Radeon RX 7900 XT\nAMD Radeon RX 7900 XT\n'
    ;;
  *mem_info_vram_total*break*)
    printf '21474836480\n'
    ;;
  *mem_info_vram_total*)
    printf '21474836480\n21474836480\n'
    ;;
  *nvidia-smi*)
    exit 0
    ;;
  *vulkaninfo*)
    printf 'GPU0:\n\tdeviceName = AMD Radeon RX 7900 XT\nGPU1:\n\tdeviceName = AMD Radeon RX 7900 XT\n'
    ;;
  *)
    printf 'unknown\n'
    ;;
esac
EOF
chmod +x "$probe_tmp/ssh"
remote_dual_amd_output="$(PATH="$probe_tmp:$PATH" OC_LOCAL_HF_FIXTURE="$repo_root/testdata/huggingface-model-search.json" "$repo_root/scripts/model-discovery.sh" --host dual-amd-host --installed-only)"
assert_contains "$remote_dual_amd_output" "Hardware source: remote:dual-amd-host"
assert_contains "$remote_dual_amd_output" "- GPUs: AMD Radeon RX 7900 XT (20 GB); AMD Radeon RX 7900 XT (20 GB)"
assert_contains "$remote_dual_amd_output" "- Total VRAM: 40 GB"

cat >"$probe_tmp/nproc" <<'EOF'
#!/usr/bin/env bash
exit 1
EOF
cat >"$probe_tmp/free" <<'EOF'
#!/usr/bin/env bash
exit 1
EOF
cat >"$probe_tmp/rocminfo" <<'EOF'
#!/usr/bin/env bash
exit 1
EOF
cat >"$probe_tmp/rocm-smi" <<'EOF'
#!/usr/bin/env bash
exit 1
EOF
chmod +x "$probe_tmp/nproc" "$probe_tmp/free" "$probe_tmp/rocminfo" "$probe_tmp/rocm-smi"
local_probe_output="$(PATH="$probe_tmp:$PATH" OC_LOCAL_HF_FIXTURE="$repo_root/testdata/huggingface-model-search.json" "$repo_root/scripts/model-discovery.sh" --local --installed-only)"
assert_contains "$local_probe_output" "Hardware source: local"
assert_contains "$local_probe_output" "GPU:"
assert_contains "$local_probe_output" "VRAM: unknown"

cat >"$probe_tmp/ssh" <<'EOF'
#!/usr/bin/env bash
exit 255
EOF
chmod +x "$probe_tmp/ssh"
default_local_output="$(PATH="$probe_tmp:$PATH" OC_LOCAL_HF_FIXTURE="$repo_root/testdata/huggingface-model-search.json" "$repo_root/scripts/model-discovery.sh" --installed-only)"
assert_contains "$default_local_output" "Hardware source: local"
assert_contains "$default_local_output" "GPU:"

hardware_output="$("$repo_root/scripts/hardware-analyzer.sh")"
assert_contains "$hardware_output" "Hardware Analysis Results:"

bench_mtp_contents="$(<"$repo_root/scripts/bench-mtp-remote.sh")"
assert_contains "$bench_mtp_contents" "--spec-type draft-mtp"
assert_contains "$bench_mtp_contents" "--spec-draft-n-max"
assert_contains "$bench_mtp_contents" "usage:"
assert_contains "$bench_mtp_contents" "--family FAMILY"
assert_contains "$bench_mtp_contents" "--repo REPO"
assert_contains "$bench_mtp_contents" "--hf-file FILE"
assert_contains "$bench_mtp_contents" "--alias ALIAS"
assert_not_contains "$bench_mtp_contents" "qwen3.6-35b-a3b-mtp"
assert_not_contains "$bench_mtp_contents" "qwen3.6-27b-mtp"
assert_contains "$bench_mtp_contents" "local compute_threads=4"
expected_threads_batch="--threads-batch \"\$compute_threads\""
assert_contains "$bench_mtp_contents" "$expected_threads_batch"
assert_contains "$bench_mtp_contents" "chat_completion_request()"
chat_request_arg='chat_request'
assert_contains "$bench_mtp_contents" "-d \"\$$chat_request_arg\""

run_current_contents="$(<"$repo_root/scripts/run-current-model.sh")"
assert_contains "$run_current_contents" "current-model.env"
assert_contains "$run_current_contents" "REMOTE_SCRIPT"
assert_contains "$run_current_contents" "REMOTE_PROFILE"
assert_contains "$run_current_contents" "exec \"\$REMOTE_SCRIPT\" \"\$REMOTE_PROFILE\""
assert_not_contains "$run_current_contents" "./start3.sh"

bench_installed_contents="$(<"$repo_root/scripts/bench-installed-kv-remote.sh")"
assert_contains "$bench_installed_contents" "usage:"
assert_contains "$bench_installed_contents" "--family FAMILY"
assert_contains "$bench_installed_contents" "--repo REPO"
assert_contains "$bench_installed_contents" "--alias ALIAS"
assert_not_contains "$bench_installed_contents" "unsloth/Qwen3.6-35B-A3B-MTP-GGUF"
assert_not_contains "$bench_installed_contents" "unsloth/gemma-4-31B-it-GGUF"

generated_accept_tmp="$(mktemp -d)"
mkdir -p "$generated_accept_tmp/runs/accepted" "$generated_accept_tmp/runs/launchers"
fresh_qwen_output="$generated_accept_tmp/fresh-qwen.out"
if LOCAL_LLM_RUNS_DIR="$generated_accept_tmp/fresh-runs" "$repo_root/scripts/oc-local" qwen reliable --info >"$fresh_qwen_output" 2>&1; then
  printf 'expected fresh qwen without accepted metadata to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$fresh_qwen_output")" "no accepted model for family: qwen"
assert_contains "$(<"$fresh_qwen_output")" "model-manager discover"
assert_contains "$(<"$fresh_qwen_output")" "model-manager benchmark"
assert_contains "$(<"$fresh_qwen_output")" "model-manager accept"
assert_not_contains "$(<"$fresh_qwen_output")" "remote_start=./start3.sh reliable"

default_profile_output="$generated_accept_tmp/default-profile.out"
if LOCAL_LLM_RUNS_DIR="$generated_accept_tmp/default-profile-runs" "$repo_root/scripts/oc-local" reliable --info >"$default_profile_output" 2>&1; then
  printf 'expected default profile without accepted default metadata to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$default_profile_output")" "no accepted default model"
assert_not_contains "$(<"$default_profile_output")" "remote_start=./start3.sh reliable"

cat >"$generated_accept_tmp/runs/accepted/custom.json" <<'JSON'
{
  "family": "custom",
  "alias": "custom-accepted-model",
  "model_name": "custom-accepted-model",
  "repo": "Example/Custom-GGUF",
  "hf_repo": "Example/Custom-GGUF",
  "remote_start": "./start42.sh",
  "launcher_file": "/tmp/generated-state/start42.sh",
  "hf_file": "Custom-Q4_K_M.gguf",
  "quant": "Custom-Q4_K_M.gguf",
  "mmproj": "enabled",
  "reasoning_effort": "medium",
  "profile": "reliable",
  "config": {
    "ctx": 98304,
    "context": 98304,
    "batch": 48,
    "ubatch": 24,
    "ngl": 123,
    "mmproj": "enabled",
    "reasoning_effort": "medium"
  }
}
JSON
cat >"$generated_accept_tmp/runs/accepted/qwen.json" <<'JSON'
{
  "family": "qwen",
  "alias": "qwen-accepted-model",
  "model_name": "qwen-accepted-model",
  "repo": "Example/Qwen-GGUF",
  "hf_repo": "Example/Qwen-GGUF",
  "remote_start": "./start43.sh",
  "hf_file": "Qwen-Q4_K_M.gguf",
  "quant": "Qwen-Q4_K_M.gguf",
  "profile": "reliable",
  "config": {"ctx": 65536, "batch": 64, "ubatch": 32, "ngl": 999}
}
JSON
generated_custom_info="$(LOCAL_LLM_RUNS_DIR="$generated_accept_tmp/runs" "$repo_root/scripts/oc-local" custom reliable --info)"
assert_contains "$generated_custom_info" "family=custom"
assert_contains "$generated_custom_info" "profile=reliable"
assert_contains "$generated_custom_info" "remote_start=./start42.sh reliable"
assert_contains "$generated_custom_info" "hf_repo=Example/Custom-GGUF"
assert_contains "$generated_custom_info" "quant=Custom-Q4_K_M.gguf"
assert_contains "$generated_custom_info" "ctx=98304"
assert_contains "$generated_custom_info" "batch=48"
assert_contains "$generated_custom_info" "ubatch=24"
assert_contains "$generated_custom_info" "ngl=123"
assert_contains "$generated_custom_info" "model_name=custom-accepted-model"
assert_contains "$generated_custom_info" "alias=custom-accepted-model"
generated_qwen_info="$(LOCAL_LLM_RUNS_DIR="$generated_accept_tmp/runs" "$repo_root/scripts/oc-local" qwen reliable --info)"
assert_contains "$generated_qwen_info" "family=qwen"
assert_contains "$generated_qwen_info" "remote_start=./start43.sh reliable"
assert_contains "$generated_qwen_info" "model_name=qwen-accepted-model"
assert_contains "$generated_qwen_info" "hf_repo=Example/Qwen-GGUF"
if LOCAL_LLM_RUNS_DIR="$generated_accept_tmp/runs" "$repo_root/scripts/oc-local" reliable --info >"$generated_accept_tmp/profile-only-without-default.out" 2>&1; then
  printf 'expected profile-only oc-local to require accepted default metadata\n' >&2
  exit 1
fi
assert_contains "$(<"$generated_accept_tmp/profile-only-without-default.out")" "no accepted default model"

ln -s "$repo_root/scripts/oc-local" "$generated_accept_tmp/oc-reliable"
if LOCAL_LLM_RUNS_DIR="$generated_accept_tmp/runs" "$generated_accept_tmp/oc-reliable" --info >"$generated_accept_tmp/oc-reliable-without-default.out" 2>&1; then
  printf 'expected oc-reliable to require accepted default metadata\n' >&2
  exit 1
fi
assert_contains "$(<"$generated_accept_tmp/oc-reliable-without-default.out")" "no accepted default model"

ln -s "$repo_root/scripts/oc-local" "$generated_accept_tmp/oc-qwen-reliable"
if LOCAL_LLM_RUNS_DIR="$generated_accept_tmp/empty-runs" "$generated_accept_tmp/oc-qwen-reliable" --info >"$generated_accept_tmp/oc-qwen-reliable-empty.out" 2>&1; then
  printf 'expected stale curated oc-qwen-reliable wrapper to require accepted default metadata\n' >&2
  exit 1
fi
assert_contains "$(<"$generated_accept_tmp/oc-qwen-reliable-empty.out")" "no accepted default model"
assert_not_contains "$(<"$generated_accept_tmp/oc-qwen-reliable-empty.out")" "no accepted model for family: qwen"

cat >"$generated_accept_tmp/runs/accepted/default.json" <<'JSON'
{"family":"custom"}
JSON
generated_default_info="$(LOCAL_LLM_RUNS_DIR="$generated_accept_tmp/runs" "$repo_root/scripts/oc-local" reliable --info)"
assert_contains "$generated_default_info" "family=custom"
assert_contains "$generated_default_info" "profile=reliable"
assert_contains "$generated_default_info" "remote_start=./start42.sh reliable"
generated_oc_reliable_info="$(LOCAL_LLM_RUNS_DIR="$generated_accept_tmp/runs" "$generated_accept_tmp/oc-reliable" --info)"
assert_contains "$generated_oc_reliable_info" "family=custom"
assert_contains "$generated_oc_reliable_info" "profile=reliable"

leading_remote_info="$(LOCAL_LLM_RUNS_DIR="$generated_accept_tmp/runs" "$repo_root/scripts/oc-local" --remote example --user alice -k custom reliable --info)"
assert_contains "$leading_remote_info" "family=custom"
assert_contains "$leading_remote_info" "profile=reliable"
assert_contains "$leading_remote_info" "remote_host=example"
assert_contains "$leading_remote_info" "remote_user=alice"
assert_contains "$leading_remote_info" "ssh_password_prompt=enabled"
assert_contains "$(<"$repo_root/scripts/oc-local")" "ssh_options=(-o BatchMode=no)"

generated_accept_symlink_outside="$generated_accept_tmp/outside-custom.json"
cp "$generated_accept_tmp/runs/accepted/custom.json" "$generated_accept_symlink_outside"

cat >"$generated_accept_tmp/runs/accepted/custom.json" <<'JSON'
{
  "family": "../evil",
  "alias": "custom-accepted-model",
  "repo": "Example/Custom-GGUF",
  "remote_start": "./start42.sh",
  "hf_file": "Custom-Q4_K_M.gguf",
  "profile": "reliable",
  "config": {"ctx": 98304, "batch": 48, "ubatch": 24, "ngl": 123}
}
JSON
generated_custom_unsafe_family_output="$generated_accept_tmp/unsafe-family.out"
if LOCAL_LLM_RUNS_DIR="$generated_accept_tmp/runs" "$repo_root/scripts/oc-local" custom reliable --info >"$generated_custom_unsafe_family_output" 2>&1; then
  printf 'expected unsafe accepted metadata family to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$generated_custom_unsafe_family_output")" "invalid accepted metadata"

cat >"$generated_accept_tmp/runs/accepted/custom.json" <<'JSON'
{
  "family": "other",
  "alias": "custom-accepted-model",
  "repo": "Example/Custom-GGUF",
  "remote_start": "./start42.sh",
  "hf_file": "Custom-Q4_K_M.gguf",
  "profile": "reliable",
  "config": {"ctx": 98304, "batch": 48, "ubatch": 24, "ngl": 123}
}
JSON
generated_custom_mismatch_family_output="$generated_accept_tmp/mismatch-family.out"
if LOCAL_LLM_RUNS_DIR="$generated_accept_tmp/runs" "$repo_root/scripts/oc-local" custom reliable --info >"$generated_custom_mismatch_family_output" 2>&1; then
  printf 'expected mismatched accepted metadata family to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$generated_custom_mismatch_family_output")" "family other does not match requested family custom"

cp "$generated_accept_symlink_outside" "$generated_accept_tmp/runs/accepted/custom.json"
python3 - "$generated_accept_tmp/runs/accepted/custom.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    metadata = json.load(handle)
metadata["alias"] = 'bad"alias'
metadata["model_name"] = 'bad"alias'
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump(metadata, handle)
    handle.write("\n")
PY
generated_custom_bad_alias_output="$generated_accept_tmp/bad-alias.out"
if LOCAL_LLM_RUNS_DIR="$generated_accept_tmp/runs" "$repo_root/scripts/oc-local" custom reliable --dry-run >"$generated_custom_bad_alias_output" 2>&1; then
  printf 'expected unsafe accepted metadata alias to fail\n' >&2
  exit 1
fi
generated_custom_bad_alias_contents="$(<"$generated_custom_bad_alias_output")"
assert_contains "$generated_custom_bad_alias_contents" "invalid accepted metadata"
assert_contains "$generated_custom_bad_alias_contents" "alias contains unsafe characters"
assert_not_contains "$generated_custom_bad_alias_contents" "OPENCODE_CONFIG_CONTENT="
cp "$generated_accept_symlink_outside" "$generated_accept_tmp/runs/accepted/custom.json"
python3 - "$generated_accept_tmp/runs/accepted/custom.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    metadata = json.load(handle)
metadata["config"]["context"] = "1; touch /tmp/pwned"
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump(metadata, handle)
    handle.write("\n")
PY
generated_custom_bad_context_output="$generated_accept_tmp/bad-context.out"
if LOCAL_LLM_RUNS_DIR="$generated_accept_tmp/runs" "$repo_root/scripts/oc-local" custom reliable --info >"$generated_custom_bad_context_output" 2>&1; then
  printf 'expected accepted metadata context injection to fail\n' >&2
  exit 1
fi
generated_custom_bad_context_contents="$(<"$generated_custom_bad_context_output")"
assert_contains "$generated_custom_bad_context_contents" "invalid accepted metadata"
assert_contains "$generated_custom_bad_context_contents" "config.context must be an integer"
assert_not_contains "$generated_custom_bad_context_contents" "OPENCODE_CONFIG_CONTENT="
cp "$generated_accept_symlink_outside" "$generated_accept_tmp/runs/accepted/custom.json"
rm "$generated_accept_tmp/runs/accepted/custom.json"
ln -s "$generated_accept_symlink_outside" "$generated_accept_tmp/runs/accepted/custom.json"
generated_custom_symlink_output="$generated_accept_tmp/metadata-symlink.out"
if LOCAL_LLM_RUNS_DIR="$generated_accept_tmp/runs" "$repo_root/scripts/oc-local" custom reliable --info >"$generated_custom_symlink_output" 2>&1; then
  printf 'expected symlinked accepted metadata to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$generated_custom_symlink_output")" "refuses symlinked accepted metadata file"
assert_not_contains "$(<"$generated_custom_symlink_output")" "custom-accepted-model"

rm "$generated_accept_tmp/runs/accepted/custom.json"
cp "$generated_accept_symlink_outside" "$generated_accept_tmp/runs/accepted/custom.json"
generated_accept_symlinked_dir_runs="$generated_accept_tmp/symlinked-accepted-runs"
generated_accept_symlinked_dir_outside="$generated_accept_tmp/symlinked-accepted-outside"
mkdir -p "$generated_accept_symlinked_dir_runs" "$generated_accept_symlinked_dir_outside"
cp "$generated_accept_tmp/runs/accepted/custom.json" "$generated_accept_symlinked_dir_outside/custom.json"
ln -s "$generated_accept_symlinked_dir_outside" "$generated_accept_symlinked_dir_runs/accepted"
generated_custom_symlinked_dir_output="$generated_accept_tmp/accepted-dir-symlink.out"
if LOCAL_LLM_RUNS_DIR="$generated_accept_symlinked_dir_runs" "$repo_root/scripts/oc-local" custom reliable --info >"$generated_custom_symlinked_dir_output" 2>&1; then
  printf 'expected symlinked accepted dir to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$generated_custom_symlinked_dir_output")" "refuses symlinked accepted dir"
assert_not_contains "$(<"$generated_custom_symlinked_dir_output")" "custom-accepted-model"

generated_accept_symlinked_root="$generated_accept_tmp/symlinked-root-runs"
ln -s "$generated_accept_tmp/runs" "$generated_accept_symlinked_root"
generated_custom_symlinked_root_output="$generated_accept_tmp/runs-root-symlink.out"
if LOCAL_LLM_RUNS_DIR="$generated_accept_symlinked_root" "$repo_root/scripts/oc-local" custom reliable --info >"$generated_custom_symlinked_root_output" 2>&1; then
  printf 'expected symlinked runs root to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$generated_custom_symlinked_root_output")" "refuses symlinked runs dir"
assert_not_contains "$(<"$generated_custom_symlinked_root_output")" "custom-accepted-model"

printf '{not json}\n' >"$generated_accept_tmp/runs/accepted/custom.json"
generated_custom_corrupt_output="$generated_accept_tmp/corrupt.out"
if LOCAL_LLM_RUNS_DIR="$generated_accept_tmp/runs" "$repo_root/scripts/oc-local" custom reliable --info >"$generated_custom_corrupt_output" 2>&1; then
  printf 'expected corrupt accepted metadata to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$generated_custom_corrupt_output")" "invalid accepted metadata"

cat >"$generated_accept_tmp/runs/accepted/custom.json" <<'JSON'
{
  "family": "custom",
  "alias": "custom-accepted-model",
  "repo": "Example/Custom-GGUF",
  "remote_start": "$(touch /tmp/bad)",
  "launcher_file": "/tmp/generated-state/start42.sh",
  "hf_file": "Custom-Q4_K_M.gguf",
  "profile": "reliable",
  "config": {"ctx": 98304, "batch": 48, "ubatch": 24, "ngl": 123}
}
JSON
generated_custom_unsafe_output="$generated_accept_tmp/unsafe.out"
if LOCAL_LLM_RUNS_DIR="$generated_accept_tmp/runs" "$repo_root/scripts/oc-local" custom reliable --info >"$generated_custom_unsafe_output" 2>&1; then
  printf 'expected unsafe accepted remote_start to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$generated_custom_unsafe_output")" "invalid accepted metadata"

python3 - "$generated_accept_tmp/runs/accepted/custom.json" <<'PY'
import json
import sys

with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump({
        "family": "custom",
        "alias": "custom-accepted-model",
        "repo": "Example/Custom-GGUF",
        "remote_start": "./start42.sh\nbad",
        "launcher_file": "/tmp/generated-state/start42.sh",
        "hf_file": "Custom-Q4_K_M.gguf",
        "profile": "reliable",
        "config": {"ctx": 98304, "batch": 48, "ubatch": 24, "ngl": 123},
    }, handle)
    handle.write("\n")
PY
generated_custom_newline_output="$generated_accept_tmp/newline.out"
if LOCAL_LLM_RUNS_DIR="$generated_accept_tmp/runs" "$repo_root/scripts/oc-local" custom reliable --info >"$generated_custom_newline_output" 2>&1; then
  printf 'expected newline accepted remote_start to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$generated_custom_newline_output")" "invalid accepted metadata"

printf '{not json}\n' >"$generated_accept_tmp/runs/accepted/qwen.json"
generated_qwen_corrupt_output="$generated_accept_tmp/qwen-corrupt.out"
if LOCAL_LLM_RUNS_DIR="$generated_accept_tmp/runs" "$repo_root/scripts/oc-local" qwen reliable --info >"$generated_qwen_corrupt_output" 2>&1; then
  printf 'expected corrupt qwen accepted metadata to fail closed\n' >&2
  exit 1
fi
generated_qwen_corrupt_contents="$(<"$generated_qwen_corrupt_output")"
assert_contains "$generated_qwen_corrupt_contents" "invalid accepted metadata"
assert_not_contains "$generated_qwen_corrupt_contents" "remote_start=./start3.sh reliable"

cat >"$generated_accept_tmp/runs/accepted/qwen.json" <<'JSON'
{
  "family": "qwen",
  "alias": "qwen-accepted-model",
  "repo": "Example/Qwen-GGUF",
  "remote_start": "$(touch /tmp/bad)",
  "hf_file": "Qwen-Q4_K_M.gguf",
  "profile": "reliable",
  "config": {"ctx": 98304, "batch": 48, "ubatch": 24, "ngl": 123}
}
JSON
generated_qwen_unsafe_output="$generated_accept_tmp/qwen-unsafe.out"
if LOCAL_LLM_RUNS_DIR="$generated_accept_tmp/runs" "$repo_root/scripts/oc-local" qwen reliable --info >"$generated_qwen_unsafe_output" 2>&1; then
  printf 'expected unsafe qwen accepted metadata to fail closed\n' >&2
  exit 1
fi
generated_qwen_unsafe_contents="$(<"$generated_qwen_unsafe_output")"
assert_contains "$generated_qwen_unsafe_contents" "invalid accepted metadata"
assert_not_contains "$generated_qwen_unsafe_contents" "remote_start=./start3.sh reliable"

mkdir -p "$generated_accept_tmp/runs/escape"
cat >"$generated_accept_tmp/runs/escape.json" <<'JSON'
{
  "family": "escape",
  "alias": "escaped-model",
  "repo": "Example/Escape-GGUF",
  "remote_start": "./start77.sh",
  "hf_file": "Escape-Q4_K_M.gguf",
  "profile": "reliable",
  "config": {"ctx": 4096, "batch": 1, "ubatch": 1, "ngl": 1}
}
JSON
generated_traversal_output="$generated_accept_tmp/traversal.out"
if LOCAL_LLM_RUNS_DIR="$generated_accept_tmp/runs" "$repo_root/scripts/oc-local" ../escape reliable --info >"$generated_traversal_output" 2>&1; then
  printf 'expected path-traversal accepted family to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$generated_traversal_output")" "invalid model family"
assert_not_contains "$(<"$generated_traversal_output")" "escaped-model"

cat >"$generated_accept_tmp/runs/accepted/qwen.json" <<'JSON'
{
  "family": "qwen",
  "alias": "qwen-accepted-model",
  "model_name": "qwen-accepted-model",
  "repo": "Example/Qwen-GGUF",
  "hf_repo": "Example/Qwen-GGUF",
  "remote_start": "./start43.sh",
  "hf_file": "Qwen-Q4_K_M.gguf",
  "quant": "Qwen-Q4_K_M.gguf",
  "profile": "reliable",
  "config": {"ctx": 65536, "batch": 64, "ubatch": 32, "ngl": 999}
}
JSON

resume_output="$(LOCAL_LLM_RUNS_DIR="$generated_accept_tmp/runs" "$repo_root/scripts/oc-local" qwen reliable --dry-run --lean -s ses_test123)"
assert_contains "$resume_output" "family=qwen"
assert_contains "$resume_output" "remote_start=./start43.sh reliable"
assert_not_contains "$resume_output" "session_id="

resume_long_output="$(LOCAL_LLM_RUNS_DIR="$generated_accept_tmp/runs" "$repo_root/scripts/oc-local" qwen reliable --dry-run --session ses_test456 --lean)"
assert_contains "$resume_long_output" "family=qwen"
assert_contains "$resume_long_output" "remote_start=./start43.sh reliable"
assert_not_contains "$resume_long_output" "session_id="

default_target_host_output="$(LOCAL_LLM_RUNS_DIR="$generated_accept_tmp/runs" OC_LOCAL_REMOTE_HOST=other-host "$repo_root/scripts/oc-local" qwen reliable --info)"
assert_contains "$default_target_host_output" "remote_host=other-host"

remote_dir_info="$(LOCAL_LLM_RUNS_DIR="$generated_accept_tmp/runs" OC_LOCAL_REMOTE_DIR=/srv/llama "$repo_root/scripts/oc-local" qwen reliable --info)"
assert_contains "$remote_dir_info" "remote_dir=/srv/llama"
assert_contains "$remote_dir_info" "remote_host="

default_remote_dir_info="$(LOCAL_LLM_RUNS_DIR="$generated_accept_tmp/runs" "$repo_root/scripts/oc-local" qwen reliable --info)"
assert_contains "$default_remote_dir_info" "remote_dir=$default_llama_dir"
assert_contains "$default_remote_dir_info" "base_url=http://localhost:8080/v1"

oc_local_contents="$(<"$repo_root/scripts/oc-local")"
assert_not_contains "$oc_local_contents" "start3.sh"
assert_not_contains "$oc_local_contents" "unsloth/Qwen3.6-35B-A3B-MTP-GGUF"
empty_runs_tmp="$(mktemp -d)"
empty_accepted_output="$empty_runs_tmp/oc-local-empty-accepted.out"
if LOCAL_LLM_RUNS_DIR="$empty_runs_tmp" "$repo_root/scripts/oc-local" qwen reliable --info >"$empty_accepted_output" 2>&1; then
  printf 'expected oc-local without accepted metadata to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$empty_accepted_output")" "Run model-manager discover, model-manager benchmark, and model-manager accept"

exec_no_session_output="$(LOCAL_LLM_RUNS_DIR="$generated_accept_tmp/runs" OC_LOCAL_PRINT_EXEC=true OC_LOCAL_WAIT_SECONDS=1 "$repo_root/scripts/oc-local" qwen reliable --dry-run --lean)"
assert_not_contains "$exec_no_session_output" "opencode_args=-s"

exec_session_output="$(LOCAL_LLM_RUNS_DIR="$generated_accept_tmp/runs" OC_LOCAL_PRINT_EXEC=true OC_LOCAL_WAIT_SECONDS=1 "$repo_root/scripts/oc-local" qwen reliable --dry-run --lean -s ses_test999)"
assert_contains "$exec_session_output" "family=qwen"
assert_not_contains "$exec_session_output" "session_id="

invalid_output="$probe_tmp/oc-local-invalid.out"
if run_dry nope >"$invalid_output" 2>&1; then
  printf 'expected invalid profile to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$invalid_output")" "Usage:"

invalid_target_output="$probe_tmp/oc-local-invalid-target.out"
if run_info --target remote: qwen reliable >"$invalid_target_output" 2>&1; then
  printf 'expected invalid target to fail\n' >&2
  exit 1
fi
assert_contains "$(<"$invalid_target_output")" "unknown option: --target"

printf 'oc-local dry-run tests passed\n'
