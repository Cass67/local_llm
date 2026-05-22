#!/usr/bin/env python3
"""Proxy Open WebUI and expose a safe local LLM model switcher."""

from __future__ import annotations

import html
import http.client
import json
import os
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


LLAMA_DIR = Path(os.environ.get("LLAMA_DIR", "/home/cass/llama.cpp"))
CURRENT_MODEL_ENV = Path(
    os.environ.get("LLAMA_CURRENT_MODEL_ENV", str(LLAMA_DIR / "current-model.env"))
)
LLAMA_API_BASE = os.environ.get("LLAMA_API_BASE", "http://127.0.0.1:8080").rstrip("/")
OPENWEBUI_BASE_URL = os.environ.get(
    "OPENWEBUI_BASE_URL", "http://127.0.0.1:3002"
).rstrip("/")
SWITCH_TIMEOUT_SECONDS = int(os.environ.get("SWITCH_TIMEOUT_SECONDS", "180"))
SWITCHER_HOST = os.environ.get("SWITCHER_HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "3001"))
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
PROXY_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"}

switch_lock = threading.Lock()


@dataclass(frozen=True)
class Model:
    family: str
    remote_script: str
    alias: str
    label: str
    profile: str = "reliable"

    @property
    def id(self) -> str:
        return f"{self.family}:{self.profile}"

    def as_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "family": self.family,
            "profile": self.profile,
            "alias": self.alias,
            "label": self.label,
        }


MODELS = [
    Model("qwen", "./start3.sh", "qwen3.6-35b-a3b-mtp", "Qwen 3.6 35B A3B MTP"),
    Model(
        "qwen-hauhau",
        "./start11.sh",
        "qwen3.6-35b-a3b-hauhau",
        "Qwen 3.6 35B Hauhau",
    ),
    Model(
        "qwen-27b-hauhau",
        "./start12.sh",
        "qwen3.6-27b-hauhau",
        "Qwen 3.6 27B Hauhau",
    ),
    Model(
        "gemma-hauhau",
        "./start14.sh",
        "gemma4-26b-a4b-hauhau",
        "Gemma 4 26B A4B Hauhau",
    ),
    Model("qwen-27b", "./start8.sh", "qwen3.6-27b-mtp", "Qwen 3.6 27B MTP"),
    Model(
        "qwen-coder",
        "./start2.sh",
        "qwen3-coder-30b-a3b-instruct",
        "Qwen Coder 30B A3B",
    ),
    Model("gemma", "./start4.sh", "gemma-4-31b-it", "Gemma 4 31B IT"),
    Model(
        "gemma-vision",
        "./start5.sh",
        "gemma-4-31b-it-vision",
        "Gemma 4 31B Vision",
    ),
    Model("gpt-oss", "./start6.sh", "gpt-oss-20b", "GPT OSS 20B"),
    Model(
        "deepseek-r1",
        "./start7.sh",
        "deepseek-r1-distill-qwen-32b",
        "DeepSeek R1 Distill Qwen 32B",
    ),
    Model(
        "qwen-opus",
        "./start9.sh",
        "qwen3.6-27b-opus-mtp",
        "Qwen 3.6 27B Opus MTP",
    ),
    Model(
        "qwen-heretic",
        "./start10.sh",
        "qwen3.6-27b-heretic-mtp",
        "Qwen 3.6 27B Heretic MTP",
    ),
]
MODELS_BY_ID = {model.id: model for model in MODELS}


class ApiError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        self.status = status
        self.detail = detail
        super().__init__(detail)


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


def model_from_env(values: dict[str, str]) -> Model | None:
    remote_script = values.get("REMOTE_SCRIPT")
    remote_profile = values.get("REMOTE_PROFILE")
    for model in MODELS:
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


def get_live_models() -> dict[str, Any]:
    try:
        request = Request(f"{LLAMA_API_BASE}/v1/models", headers={"Accept": "application/json"})
        with urlopen(request, timeout=5) as response:
            body = json.loads(response.read().decode("utf-8"))
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
    subprocess.run(
        ["systemctl", "--user", "restart", "llama-server.service"],
        check=True,
        text=True,
        capture_output=True,
    )


def switch_to_model(model_id: object) -> dict[str, Any]:
    if not isinstance(model_id, str) or model_id not in MODELS_BY_ID:
        raise ApiError(400, "model id is not allowed")
    model = MODELS_BY_ID[model_id]
    with switch_lock:
        verify_launcher(model)
        write_current_model(model)
        try:
            restart_llama_server()
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr.strip() or exc.stdout.strip() or str(exc)
            raise ApiError(502, f"restart failed: {detail}") from exc
        if not wait_for_alias(model.alias, SWITCH_TIMEOUT_SECONDS):
            raise ApiError(504, f"timed out waiting for llama-server alias {model.alias}")
    return {"ok": True, "model": model.as_dict()}


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
        if header_name(name) not in HOP_BY_HOP_HEADERS
        and header_name(name) != "content-length"
    ]


def injected_html_headers(headers: list[tuple[str, str]]) -> list[tuple[str, str]]:
    blocked = HOP_BY_HOP_HEADERS | CSP_HEADERS | {"content-length", "content-encoding"}
    return [(name, value) for name, value in headers if header_name(name) not in blocked]


def inject_widget(body: bytes, content_type: str) -> bytes:
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
    if "</body>" in lower_text:
        index = lower_text.rfind("</body>")
        text = text[:index] + snippet + text[index:]
    else:
        text += snippet
    return text.encode(charset)


def widget_snippet() -> str:
    return r'''
<div id="local-llm-switcher" style="position:fixed;right:16px;bottom:16px;z-index:2147483647;background:#111827;color:#f9fafb;border:1px solid #374151;border-radius:12px;padding:10px 12px;font:13px system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;box-shadow:0 12px 36px rgba(0,0,0,.35);display:flex;gap:8px;align-items:center;max-width:calc(100vw - 32px)">
  <label for="local-llm-switcher-select" style="font-weight:600;white-space:nowrap">Local LLM</label>
  <select id="local-llm-switcher-select" style="max-width:260px;background:#1f2937;color:#f9fafb;border:1px solid #4b5563;border-radius:8px;padding:5px"></select>
  <span id="local-llm-switcher-status" style="color:#d1d5db;white-space:nowrap">loading</span>
</div>
<script>
(() => {
  const root = document.getElementById('local-llm-switcher');
  const select = document.getElementById('local-llm-switcher-select');
  const status = document.getElementById('local-llm-switcher-status');
  if (!root || !select || !status) return;
  const setStatus = (text) => { status.textContent = text; };
  const load = async () => {
    try {
      const [modelsRes, currentRes] = await Promise.all([
        fetch('/api/local-llm/models'),
        fetch('/api/local-llm/current'),
      ]);
      if (!modelsRes.ok || !currentRes.ok) throw new Error('API unavailable');
      const modelsBody = await modelsRes.json();
      const currentBody = await currentRes.json();
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
      setStatus('ready');
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
'''


def fallback_html() -> bytes:
    options = "\n".join(
        f'<option value="{html.escape(model.id)}">{html.escape(model.label)}</option>'
        for model in MODELS
    )
    return f"""<!doctype html>
<html>
<head><meta charset="utf-8"><title>Local LLM Switcher</title></head>
<body>
  <h1>Local LLM Switcher</h1>
  <p>This fallback page uses the same local switcher APIs as the Open WebUI widget.</p>
  <select id="fallback-model">{options}</select>
  <button id="fallback-switch">Switch</button>
  <pre id="fallback-status">loading</pre>
  <script>
  const status = document.getElementById('fallback-status');
  const select = document.getElementById('fallback-model');
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
    status.textContent = await response.text();
  }});
  refresh();
  </script>
</body>
</html>""".encode("utf-8")


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
                self.send_json(200, {"models": [model.as_dict() for model in MODELS]})
            elif self.command == "GET" and path == "/api/local-llm/current":
                self.send_json(200, current_model_payload())
            elif self.command == "POST" and path == "/api/local-llm/switch":
                payload = read_json_body(self)
                model_id = payload.get("id") if isinstance(payload, dict) else None
                self.send_json(200, switch_to_model(model_id))
            elif self.command == "GET" and path == "/_switcher":
                self.send_bytes(200, fallback_html(), "text/html; charset=utf-8")
            elif self.command in PROXY_METHODS:
                self.proxy_openwebui()
            else:
                self.send_json(405, {"detail": "method not allowed"})
        except ApiError as exc:
            self.send_json(exc.status, {"detail": exc.detail})
        except Exception as exc:  # pragma: no cover - safety net for service logs.
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

    def proxy_openwebui(self) -> None:
        upstream = urlsplit(OPENWEBUI_BASE_URL)
        if upstream.scheme not in {"http", "https"}:
            self.send_json(502, {"detail": "OPENWEBUI_BASE_URL must be http or https"})
            return

        path = self.path if self.path.startswith("/") else f"/{self.path}"
        headers = self.proxy_request_headers(upstream.netloc)
        body = self.read_request_body()
        connection_cls = http.client.HTTPSConnection if upstream.scheme == "https" else http.client.HTTPConnection
        connection = connection_cls(upstream.hostname, upstream.port, timeout=60)
        try:
            connection.request(self.command, path, body=body, headers=headers)
            response = connection.getresponse()
            self.send_proxied_response(response)
        except OSError as exc:
            self.send_json(502, {"detail": f"Open WebUI proxy failed: {exc}"})
        finally:
            connection.close()

    def proxy_request_headers(self, host: str) -> dict[str, str]:
        headers: dict[str, str] = {}
        for name, value in self.headers.items():
            lower = header_name(name)
            if lower in HOP_BY_HOP_HEADERS or lower == "host":
                continue
            if lower == "accept-encoding":
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
        is_html = self.command != "HEAD" and "text/html" in content_type.lower()

        if is_html:
            body = inject_widget(response.read(), content_type)
            self.send_response(response.status, response.reason)
            for name, value in injected_html_headers(headers):
                self.send_header(name, value)
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
