#!/usr/bin/env python3
"""Proxy the browser UI and expose a safe local LLM model switcher."""

from __future__ import annotations

import html
import http.client
import json
import os
import selectors
import signal
import tempfile
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

LLAMA_DIR = Path(os.environ.get("LLAMA_DIR", "~/llama.cpp")).expanduser()
ACCEPTED_DIR = Path(
    os.environ.get("LOCAL_LLM_ACCEPTED_DIR", str(LLAMA_DIR / "accepted"))
).expanduser()
CURRENT_MODEL_ENV = Path(
    os.environ.get("LLAMA_CURRENT_MODEL_ENV", str(LLAMA_DIR / "current-model.env"))
)
LLAMA_API_BASE = os.environ.get("LLAMA_API_BASE", "http://127.0.0.1:8080").rstrip("/")
WEB_UPSTREAM = (
    os.environ.get("LOCAL_LLM_WEB_UPSTREAM")
    or os.environ.get("OPENWEBUI_BASE_URL")
    or "http://127.0.0.1:3002"
).rstrip("/")
VALID_INJECT_TARGETS = {"opencode", "none"}
SYNC_OPENWEBUI = os.environ.get("LOCAL_LLM_SYNC_OPENWEBUI", "false").lower() == "true"
SWITCH_TIMEOUT_SECONDS = int(os.environ.get("SWITCH_TIMEOUT_SECONDS", "180"))
SWITCHER_HOST = os.environ.get("SWITCHER_HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "3001"))
OPENWEBUI_CONTAINER = os.environ.get("OPENWEBUI_CONTAINER", "open-webui")
OPENWEBUI_DB_PATH = os.environ.get("OPENWEBUI_DB_PATH", "/app/backend/data/webui.db")
SYSTEMCTL_BIN = os.environ.get("SYSTEMCTL_BIN", "/usr/bin/systemctl")
DOCKER_BIN = os.environ.get("DOCKER_BIN", "/usr/bin/docker")
POLL_INTERVAL_SECONDS = 2.0
COPY_CHUNK_SIZE = 64 * 1024
HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}
CSP_HEADERS = {"content-security-policy", "content-security-policy-report-only"}
CACHE_HEADERS = {"cache-control", "etag", "expires", "last-modified", "pragma"}
CACHE_VALIDATION_HEADERS = {
    "if-match",
    "if-modified-since",
    "if-none-match",
    "if-range",
    "if-unmodified-since",
}
PROXY_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"}

switch_lock = threading.Lock()


def validate_inject_target(target: str) -> str:
    normalized = target.strip().lower()
    if normalized not in VALID_INJECT_TARGETS:
        allowed = ", ".join(sorted(VALID_INJECT_TARGETS))
        raise ValueError(f"LOCAL_LLM_INJECT_TARGET must be one of: {allowed}")
    return normalized


INJECT_TARGET = validate_inject_target(os.environ.get("LOCAL_LLM_INJECT_TARGET", "opencode"))


@dataclass(frozen=True)
class Model:
    family: str
    remote_script: str
    alias: str
    label: str
    profile: str = "reliable"
    context: int | None = None
    reasoning: bool = False

    @property
    def id(self) -> str:
        return f"{self.family}:{self.profile}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "family": self.family,
            "profile": self.profile,
            "alias": self.alias,
            "label": self.label,
            "context": self.context,
            "reasoning": self.reasoning,
        }


MODELS: list[Model] = []
MODELS_BY_ID = {model.id: model for model in MODELS}
STANDARD_PROFILES = ("speed", "fastlong", "balanced", "reliable", "tiny")


class ApiError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        self.status = status
        self.detail = detail
        super().__init__(detail)


class CommandError(Exception):
    def __init__(self, args: list[str], returncode: int, stdout: str, stderr: str) -> None:
        self.args_list = args
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        super().__init__(f"command failed with exit code {returncode}: {args[0]}")


class ThreadingHTTPServerReuse(ThreadingHTTPServer):
    allow_reuse_address = True


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def launcher_metadata(path: Path) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return metadata
    for line in text.splitlines():
        if line.startswith("# local_llm_") and "=" in line:
            key, value = line[2:].split("=", 1)
            metadata[key.removeprefix("local_llm_")] = value.strip()
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("ctx="):
            try:
                metadata["context"] = int(stripped.split("=", 1)[1].strip().strip('"'))
            except ValueError:
                pass
            break
    metadata["reasoning"] = "--reasoning on" in text
    profiles = []
    for profile in STANDARD_PROFILES:
        if profile in text:
            profiles.append(profile)
    metadata["profiles"] = profiles or ["reliable"]
    return metadata


def format_context(context: int | None) -> str:
    if not context:
        return "?ctx"
    if context >= 1000:
        return f"{round(context / 1000):.0f}k"
    return str(context)


def accepted_model_from_json(path: Path, current_values: dict[str, str]) -> Model | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    remote_script = data.get("remote_start")
    if not isinstance(remote_script, str) or not remote_script.startswith("./"):
        return None
    family = data.get("family") or path.stem
    alias = data.get("alias") or data.get("model_name") or family
    if not isinstance(family, str) or not isinstance(alias, str):
        return None
    config_obj = data.get("config")
    config: dict[str, Any] = config_obj if isinstance(config_obj, dict) else {}
    context_value = config.get("ctx") or config.get("context")
    try:
        context = int(context_value) if context_value else None
    except (TypeError, ValueError):
        context = None
    reasoning = bool(config.get("reasoning", data.get("reasoning", False)))
    profile_obj = data.get("profile")
    profile = profile_obj if isinstance(profile_obj, str) else "reliable"
    current_profile = current_values.get("REMOTE_PROFILE")
    if current_values.get("REMOTE_SCRIPT") == remote_script and current_profile:
        profile = current_profile
    suffix = f"{profile} · {format_context(context)}"
    if reasoning:
        suffix += " · reasoning"
    return Model(
        family=family,
        remote_script=remote_script,
        alias=alias,
        label=f"{alias} ({suffix})",
        profile=profile,
        context=context,
        reasoning=reasoning,
    )


def load_models() -> list[Model]:
    current_values = parse_env_file(CURRENT_MODEL_ENV)
    accepted_models: list[Model] = []
    if ACCEPTED_DIR.is_dir() and not ACCEPTED_DIR.is_symlink():
        for path in sorted(ACCEPTED_DIR.glob("*.json")):
            if path.name == "default.json":
                continue
            model = accepted_model_from_json(path, current_values)
            if model:
                accepted_models.append(model)
    if accepted_models:
        return accepted_models

    discovered: list[Model] = []
    seen: set[str] = set()
    for path in sorted(LLAMA_DIR.glob("start*.sh")):
        if ".bak-" in path.name or not path.is_file():
            continue
        metadata = launcher_metadata(path)
        family = metadata.get("family") or path.stem
        alias = metadata.get("alias") or family
        context = metadata.get("context")
        reasoning = bool(metadata.get("reasoning"))
        remote_script = "./" + path.name
        current_profile = current_values.get("REMOTE_PROFILE")
        profile = (
            current_profile
            if current_values.get("REMOTE_SCRIPT") == remote_script and current_profile
            else "reliable"
        )
        model_id = f"{family}:{profile}"
        if model_id in seen:
            continue
        seen.add(model_id)
        suffix = f"{profile} · {format_context(context)}"
        if reasoning:
            suffix += " · reasoning"
        discovered.append(
            Model(
                family=family,
                remote_script=remote_script,
                alias=alias,
                label=f"{alias} ({suffix})",
                profile=profile,
                context=context if isinstance(context, int) else None,
                reasoning=reasoning,
            )
        )
    if discovered:
        return discovered
    return MODELS


def models_by_id() -> dict[str, Model]:
    models = load_models()
    return {model.id: model for model in models}


def model_from_env(values: dict[str, str]) -> Model | None:
    remote_script = values.get("REMOTE_SCRIPT")
    remote_profile = values.get("REMOTE_PROFILE")
    for model in load_models():
        if model.remote_script == remote_script and model.profile == remote_profile:
            return model
    return None


def write_current_model(model: Model) -> None:
    CURRENT_MODEL_ENV.parent.mkdir(parents=True, exist_ok=True)
    content = f"REMOTE_SCRIPT={model.remote_script}\nREMOTE_PROFILE={model.profile}\n"
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=CURRENT_MODEL_ENV.parent, delete=False
    ) as tmp:
        tmp.write(content)
        tmp.flush()
        os.fsync(tmp.fileno())
        temp_name = tmp.name
    os.replace(temp_name, CURRENT_MODEL_ENV)


def launcher_path(model: Model) -> Path:
    return LLAMA_DIR / model.remote_script.removeprefix("./")


def verify_launcher(model: Model) -> None:
    path = launcher_path(model)
    if not path.exists():
        raise ApiError(409, f"launcher for {model.id} is missing: {path}")
    if not path.is_file() or not os.access(path, os.X_OK):
        raise ApiError(409, f"launcher for {model.id} is not executable: {path}")


def http_json_get(base_url: str, path: str) -> dict[str, Any]:
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise OSError("base URL must be http or https")

    connection_cls = (
        http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    )
    connection = connection_cls(parsed.hostname, parsed.port, timeout=5)
    try:
        connection.request("GET", path, headers={"Accept": "application/json"})
        response = connection.getresponse()
        return json.loads(response.read().decode("utf-8"))
    finally:
        connection.close()


def read_from_selector(selector: selectors.BaseSelector) -> tuple[dict[int, bytes], bool]:
    chunks: dict[int, bytes] = {}
    for key, _events in selector.select(timeout=0.05):
        chunk = os.read(key.fd, COPY_CHUNK_SIZE)
        if chunk:
            chunks[key.fd] = chunk
        else:
            selector.unregister(key.fd)
            os.close(key.fd)
    return chunks, bool(selector.get_map())


def run_command(args: list[str], timeout_seconds: float = 15) -> str:
    executable = args[0]
    if not executable.startswith("/"):
        raise ValueError(f"command path must be absolute: {executable}")

    stdout_read, stdout_write = os.pipe()
    stderr_read, stderr_write = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(stdout_read)
        os.close(stderr_read)
        os.dup2(stdout_write, 1)
        os.dup2(stderr_write, 2)
        os.close(stdout_write)
        os.close(stderr_write)
        os.execv(executable, args)  # nosec B606 -- controlled exec replacement

    os.close(stdout_write)
    os.close(stderr_write)
    os.set_blocking(stdout_read, False)
    os.set_blocking(stderr_read, False)

    output = {stdout_read: [], stderr_read: []}
    deadline = time.monotonic() + timeout_seconds
    with selectors.DefaultSelector() as selector:
        selector.register(stdout_read, selectors.EVENT_READ)
        selector.register(stderr_read, selectors.EVENT_READ)
        returncode: int | None = None
        while returncode is None or selector.get_map():
            for fd, chunk in read_from_selector(selector)[0].items():
                output[fd].append(chunk)
            if returncode is None:
                waited_pid, status = os.waitpid(pid, os.WNOHANG)
                if waited_pid:
                    returncode = os.waitstatus_to_exitcode(status)
            if returncode is None and time.monotonic() > deadline:
                os.kill(pid, signal.SIGKILL)
                _waited_pid, status = os.waitpid(pid, 0)
                returncode = os.waitstatus_to_exitcode(status)

    stdout = b"".join(output[stdout_read]).decode("utf-8", errors="replace")
    stderr = b"".join(output[stderr_read]).decode("utf-8", errors="replace")
    if returncode:
        raise CommandError(args, returncode, stdout, stderr)
    return stdout


def get_live_models() -> dict[str, Any]:
    try:
        body = http_json_get(LLAMA_API_BASE, "/v1/models")
    except (OSError, json.JSONDecodeError) as exc:
        return {"available": False, "error": str(exc)}

    aliases = []
    for item in body.get("data", []):
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            aliases.append(item["id"])
    return {"available": True, "aliases": aliases, "raw": body}


def wait_for_alias(alias: str, timeout_seconds: int) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        live = get_live_models()
        if live.get("available") and alias in live.get("aliases", []):
            return True
        time.sleep(POLL_INTERVAL_SECONDS)
    return False


def restart_llama_server() -> None:
    run_command([SYSTEMCTL_BIN, "--user", "restart", "llama-server.service"])


def sync_openwebui_selected_model(alias: str) -> dict[str, Any]:
    script = r'''
import json
import sqlite3
import sys
import time

db_path, alias = sys.argv[1:]
connection = sqlite3.connect(db_path)
cursor = connection.cursor()
updated = 0
now = int(time.time())
admin_row = cursor.execute(
    "select id from user where role='admin' order by created_at limit 1"
).fetchone()
owner_id = admin_row[0] if admin_row else cursor.execute(
    "select id from user order by created_at limit 1"
).fetchone()[0]

cursor.execute(
    """
    insert into model
        (id, user_id, base_model_id, name, meta, params, created_at, updated_at, is_active)
    values (?, ?, null, ?, ?, ?, ?, ?, 1)
    on conflict(id) do update set
        name=excluded.name,
        updated_at=excluded.updated_at,
        is_active=1
    """,
    (alias, owner_id, alias, json.dumps({}), json.dumps({}), now, now),
)
model_rows = cursor.rowcount

for user_id, settings_text in cursor.execute("select id, settings from user").fetchall():
    if not settings_text or settings_text == "null":
        settings = {}
    else:
        try:
            settings = json.loads(settings_text)
        except json.JSONDecodeError:
            continue
    try:
        settings = dict(settings)
    except (TypeError, ValueError):
        settings = {}
    ui = settings.get("ui")
    if not isinstance(ui, dict):
        ui = {}
        settings["ui"] = ui
    ui["models"] = [alias]
    cursor.execute(
        "update user set settings=?, updated_at=? where id=?",
        (json.dumps(settings), now, user_id),
    )
    grant_id = f"model:{alias}:user:{user_id}:read"
    cursor.execute(
        """
        insert or ignore into access_grant
            (id, resource_type, resource_id, principal_type, principal_id, permission,
             created_at)
        values (?, 'model', ?, 'user', ?, 'read', ?)
        """,
        (grant_id, alias, user_id, now),
    )
    updated += 1

connection.commit()
print(json.dumps({"updated": updated, "model_rows": model_rows, "alias": alias}))
'''
    try:
        output = run_command(
            [
                DOCKER_BIN,
                "exec",
                OPENWEBUI_CONTAINER,
                "python3",
                "-c",
                script,
                OPENWEBUI_DB_PATH,
                alias,
            ]
        )
        result = json.loads(output.strip() or "{}")
        return result if isinstance(result, dict) else {"updated": 0}
    except (OSError, CommandError, json.JSONDecodeError) as exc:
        return {"updated": 0, "error": str(exc)}


def switch_to_model(model_id: object) -> dict[str, Any]:
    by_id = models_by_id()
    if not isinstance(model_id, str) or model_id not in by_id:
        raise ApiError(400, "model id is not allowed")
    model = by_id[model_id]
    with switch_lock:
        verify_launcher(model)
        write_current_model(model)
        try:
            restart_llama_server()
        except CommandError as exc:
            detail = exc.stderr.strip() or exc.stdout.strip() or str(exc)
            raise ApiError(502, f"restart failed: {detail}") from exc
        if not wait_for_alias(model.alias, SWITCH_TIMEOUT_SECONDS):
            raise ApiError(504, f"timed out waiting for llama-server alias {model.alias}")
        openwebui_sync = sync_openwebui_selected_model(model.alias) if SYNC_OPENWEBUI else None
    payload = {
        "ok": True,
        "model": model.as_dict(),
        "reload_recommended": True,
    }
    if openwebui_sync is not None:
        payload["openwebui"] = openwebui_sync
    return payload


def current_model_payload() -> dict[str, Any]:
    values = parse_env_file(CURRENT_MODEL_ENV)
    model = model_from_env(values)
    live = get_live_models()
    live_aliases = live.get("aliases", []) if live.get("available") else []
    return {
        "model": model.as_dict() if model else None,
        "env": {
            "path": str(CURRENT_MODEL_ENV),
            "remote_script": values.get("REMOTE_SCRIPT"),
            "remote_profile": values.get("REMOTE_PROFILE"),
        },
        "live": live,
        "matches_live": bool(model and model.alias in live_aliases),
    }


def read_json_body(handler: BaseHTTPRequestHandler) -> Any:
    length = int(handler.headers.get("Content-Length", "0") or "0")
    try:
        return json.loads(handler.rfile.read(length).decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ApiError(400, "invalid JSON") from exc


def json_bytes(payload: object) -> bytes:
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def header_name(name: str) -> str:
    return name.lower()


def proxy_response_headers(headers: list[tuple[str, str]]) -> list[tuple[str, str]]:
    return [
        (name, value)
        for name, value in headers
        if header_name(name) not in HOP_BY_HOP_HEADERS and header_name(name) != "content-length"
    ]


def injected_html_headers(headers: list[tuple[str, str]]) -> list[tuple[str, str]]:
    blocked = (
        HOP_BY_HOP_HEADERS
        | CSP_HEADERS
        | CACHE_HEADERS
        | {
            "content-length",
            "content-encoding",
        }
    )
    return [(name, value) for name, value in headers if header_name(name) not in blocked]


def should_rewrite_html_response(method: str, content_type: str, target: str) -> bool:
    return (
        method != "HEAD"
        and validate_inject_target(target) == "opencode"
        and "text/html" in content_type.lower()
    )


def inject_switcher_widget(body: bytes, content_type: str, target: str) -> bytes:
    if validate_inject_target(target) == "none" or "text/html" not in content_type.lower():
        return body

    charset = "utf-8"
    for part in content_type.split(";"):
        part = part.strip()
        if part.lower().startswith("charset="):
            charset = part.split("=", 1)[1]
    try:
        text = body.decode(charset)
    except UnicodeDecodeError:
        text = body.decode("utf-8", errors="replace")
        charset = "utf-8"

    snippet = widget_snippet()
    lower_text = text.lower()
    if "local-llm-switcher" in lower_text:
        return body
    if "</body>" in lower_text:
        index = lower_text.rfind("</body>")
        text = text[:index] + snippet + text[index:]
    else:
        text += snippet
    return text.encode(charset)


def inject_widget(body: bytes, content_type: str) -> bytes:
    return inject_switcher_widget(body, content_type, INJECT_TARGET)


def widget_snippet() -> str:
    return r"""
<style>
  #local-llm-switcher {
    position: fixed;
    right: 16px;
    bottom: max(96px, env(safe-area-inset-bottom));
    z-index: 2147483647;
    font: 13px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  }
  #local-llm-switcher-toggle {
    background: #111827;
    color: #f9fafb;
    border: 1px solid #374151;
    border-radius: 999px;
    padding: 8px 10px;
    box-shadow: 0 12px 36px rgba(0, 0, 0, .35);
    cursor: pointer;
  }
  #local-llm-switcher-panel {
    position: absolute;
    right: 0;
    bottom: calc(100% + 8px);
    background: #111827;
    color: #f9fafb;
    border: 1px solid #374151;
    border-radius: 12px;
    padding: 10px 12px;
    box-shadow: 0 12px 36px rgba(0, 0, 0, .35);
    display: flex;
    gap: 8px;
    align-items: center;
    width: max-content;
    max-width: min(360px, calc(100vw - 32px));
  }
  #local-llm-switcher:not(.is-open) #local-llm-switcher-panel {
    display: none;
  }
  #local-llm-switcher label,
  #local-llm-switcher-status {
    white-space: nowrap;
  }
  #local-llm-switcher label {
    font-weight: 600;
  }
  #local-llm-switcher-select {
    max-width: 260px;
    background: #1f2937;
    color: #f9fafb;
    border: 1px solid #4b5563;
    border-radius: 8px;
    padding: 5px;
  }
  #local-llm-switcher-status {
    color: #d1d5db;
  }
  @media (max-width: 640px) {
    #local-llm-switcher {
      right: 8px;
      bottom: max(96px, env(safe-area-inset-bottom));
    }
    #local-llm-switcher-panel {
      width: min(72vw, 320px);
      max-width: calc(100vw - 16px);
    }
    #local-llm-switcher-select {
      flex: 1;
      min-width: 0;
      max-width: none;
    }
    #local-llm-switcher-status {
      display: none;
    }
  }
  @media (hover: none), (pointer: coarse), (max-width: 900px) {
    #local-llm-switcher {
      right: 8px;
      bottom: max(96px, env(safe-area-inset-bottom));
    }
    #local-llm-switcher-panel {
      width: min(72vw, 320px);
      max-width: calc(100vw - 16px);
    }
    #local-llm-switcher-select {
      flex: 1;
      min-width: 0;
      max-width: none;
    }
    #local-llm-switcher-status {
      display: none;
    }
  }
</style>
<div id="local-llm-switcher">
  <button id="local-llm-switcher-toggle" type="button" aria-expanded="false"
    aria-label="Local LLM switcher">LLM</button>
  <div id="local-llm-switcher-panel">
    <label for="local-llm-switcher-select">Local LLM</label>
    <select id="local-llm-switcher-select"></select>
    <span id="local-llm-switcher-status">loading</span>
  </div>
</div>
<script>
(() => {
  const root = document.getElementById('local-llm-switcher');
  const toggle = document.getElementById('local-llm-switcher-toggle');
  const select = document.getElementById('local-llm-switcher-select');
  const status = document.getElementById('local-llm-switcher-status');
  if (!root || !toggle || !select || !status) return;
  toggle.addEventListener('click', () => {
    const isOpen = root.classList.toggle('is-open');
    toggle.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
  });
  const setStatus = (text) => { status.textContent = text; };
  const goToNewChat = (alias) => {
    window.location.href = '/?local_llm_model=' + encodeURIComponent(alias) + '&t=' + Date.now();
  };
  const load = async () => {
    try {
      const [modelsRes, currentRes] = await Promise.all([
        fetch('/api/local-llm/models'),
        fetch('/api/local-llm/current'),
      ]);
      if (!modelsRes.ok || !currentRes.ok) throw new Error('API unavailable');
      const modelsBody = await modelsRes.json();
      const currentBody = await currentRes.json();
      if (!modelsBody.models.length) {
        select.replaceChildren(new Option('No local models configured', ''));
        select.disabled = true;
        setStatus('no models');
        return;
      }
      select.replaceChildren(...modelsBody.models.map((model) => {
        const option = document.createElement('option');
        option.value = model.id;
        option.textContent = model.label;
        return option;
      }));
      if (currentBody.model) select.value = currentBody.model.id;
      setStatus(currentBody.live && currentBody.live.available ? 'ready' : 'status unknown');
    } catch (error) {
      setStatus('offline');
    }
  };
  select.addEventListener('change', async () => {
    const id = select.value;
    select.disabled = true;
    setStatus('switching');
    try {
      const response = await fetch('/api/local-llm/switch', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({id}),
      });
      if (!response.ok) throw new Error(await response.text());
      const body = await response.json();
      const alias = body.model && body.model.alias ? body.model.alias : id;
      setStatus('ready: ' + alias);
      goToNewChat(alias);
    } catch (error) {
      setStatus('switch failed');
      await load();
    } finally {
      select.disabled = false;
    }
  });
  load();
})();
</script>
"""


def fallback_html() -> bytes:
    models = load_models()
    if models:
        options = "\n".join(
            f'<option value="{html.escape(model.id)}">{html.escape(model.label)}</option>'
            for model in models
        )
    else:
        options = '<option value="">No local models configured</option>'
    return f"""<!doctype html>
<html>
<head><meta charset="utf-8"><title>Local LLM Switcher</title></head>
<body>
  <h1>Local LLM Switcher</h1>
  <p>This fallback page uses the same local switcher APIs as the browser UI widget.</p>
  <select id="fallback-model">{options}</select>
  <button id="fallback-switch">Switch</button>
  <pre id="fallback-status">loading</pre>
  <script>
  const status = document.getElementById('fallback-status');
  const select = document.getElementById('fallback-model');
  function goToNewChat(alias) {{
    window.location.href = '/?local_llm_model=' + encodeURIComponent(alias) + '&t=' + Date.now();
  }}
  async function refresh() {{
    const response = await fetch('/api/local-llm/current');
    const body = await response.json();
    if (body.model) select.value = body.model.id;
    status.textContent = JSON.stringify(body, null, 2);
  }}
  document.getElementById('fallback-switch').addEventListener('click', async () => {{
    status.textContent = 'switching...';
    const response = await fetch('/api/local-llm/switch', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{id: select.value}}),
    }});
    const text = await response.text();
    status.textContent = text;
    try {{
      const body = JSON.parse(text);
      const alias = body.model && body.model.alias ? body.model.alias : select.value;
      goToNewChat(alias);
    }} catch (error) {{}}
  }});
  refresh();
  </script>
</body>
</html>""".encode()


class SwitcherHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def do_GET(self) -> None:
        self.route()

    def do_POST(self) -> None:
        self.route()

    def do_PUT(self) -> None:
        self.route()

    def do_PATCH(self) -> None:
        self.route()

    def do_DELETE(self) -> None:
        self.route()

    def do_OPTIONS(self) -> None:
        self.route()

    def do_HEAD(self) -> None:
        self.route()

    def route(self) -> None:
        path = urlsplit(self.path).path
        try:
            if self.command == "GET" and path == "/api/local-llm/models":
                self.send_json(200, {"models": [model.as_dict() for model in load_models()]})
            elif self.command == "GET" and path == "/api/local-llm/current":
                self.send_json(200, current_model_payload())
            elif self.command == "POST" and path == "/api/local-llm/switch":
                payload = read_json_body(self)
                model_id = payload.get("id") if isinstance(payload, dict) else None
                self.send_json(200, switch_to_model(model_id))
            elif self.command == "GET" and path == "/_switcher":
                self.send_bytes(200, fallback_html(), "text/html; charset=utf-8")
            elif self.command in PROXY_METHODS:
                self.proxy_web_upstream()
            else:
                self.send_json(405, {"detail": "method not allowed"})
        except ApiError as exc:
            self.send_json(exc.status, {"detail": exc.detail})
        except (
            CommandError,
            OSError,
            ValueError,
            http.client.HTTPException,
            json.JSONDecodeError,
        ) as exc:
            self.send_json(500, {"detail": str(exc)})

    def send_json(self, status: int, payload: object) -> None:
        self.send_bytes(status, json_bytes(payload), "application/json")

    def send_bytes(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)
        self.close_connection = True

    def proxy_web_upstream(self) -> None:
        upstream = urlsplit(WEB_UPSTREAM)
        if upstream.scheme not in {"http", "https"} or not upstream.hostname:
            self.send_json(502, {"detail": "LOCAL_LLM_WEB_UPSTREAM must be http or https"})
            return

        path = self.path if self.path.startswith("/") else f"/{self.path}"
        headers = self.proxy_request_headers(upstream.netloc)
        body = self.read_request_body()
        connection_cls = (
            http.client.HTTPSConnection
            if upstream.scheme == "https"
            else http.client.HTTPConnection
        )
        connection = connection_cls(upstream.hostname, upstream.port, timeout=60)
        try:
            connection.request(self.command, path, body=body, headers=headers)
            response = connection.getresponse()
            self.send_proxied_response(response)
        except OSError as exc:
            self.send_json(502, {"detail": f"web upstream proxy failed: {exc}"})
        finally:
            connection.close()

    def proxy_request_headers(self, host: str) -> dict[str, str]:
        headers: dict[str, str] = {}
        for name, value in self.headers.items():
            lower = header_name(name)
            if lower in HOP_BY_HOP_HEADERS or lower == "host":
                continue
            if lower == "accept-encoding" or lower in CACHE_VALIDATION_HEADERS:
                continue
            headers[name] = value
        headers["Host"] = host
        headers["Accept-Encoding"] = "identity"
        return headers

    def read_request_body(self) -> bytes | None:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return None
        return self.rfile.read(length)

    def send_proxied_response(self, response: http.client.HTTPResponse) -> None:
        headers = response.getheaders()
        content_type = response.getheader("Content-Type", "") or ""
        is_html = should_rewrite_html_response(self.command, content_type, INJECT_TARGET)

        if is_html:
            body = inject_widget(response.read(), content_type)
            self.send_response(response.status, response.reason)
            for name, value in injected_html_headers(headers):
                self.send_header(name, value)
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            self.close_connection = True
            return

        self.send_response(response.status, response.reason)
        for name, value in proxy_response_headers(headers):
            self.send_header(name, value)
        self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            while True:
                chunk = response.read(COPY_CHUNK_SIZE)
                if not chunk:
                    break
                self.wfile.write(chunk)
        self.close_connection = True


def main() -> None:
    server = ThreadingHTTPServerReuse((SWITCHER_HOST, PORT), SwitcherHandler)
    print(f"local-llm-switcher listening on http://{SWITCHER_HOST}:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
