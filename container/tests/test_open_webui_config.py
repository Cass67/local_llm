"""Tests for Open WebUI chat app routing/config."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "container" / "docker-compose.yml"
CADDYFILE = ROOT / "scripts" / "Caddyfile.local-llm"


def test_compose_runs_management_api_on_host_network():
    compose = yaml.safe_load(COMPOSE.read_text())
    service = compose["services"]["local-llm"]

    assert service["container_name"] == "local-llm-mgmt"
    assert service["network_mode"] == "host"
    assert "ports" not in service
    assert "RUNNER_URL=http://host.docker.internal:8080/v1" not in service["environment"]


def test_compose_defines_open_webui_chat_service():
    compose = yaml.safe_load(COMPOSE.read_text())
    service = compose["services"]["open-webui"]

    assert service["container_name"] == "open-webui"
    assert service["network_mode"] == "host"
    assert any("/app/backend/data" in mount for mount in service["volumes"])
    env = service["environment"]
    assert "OPENAI_API_BASE_URL=http://127.0.0.1:3100/v1" in env
    assert "WEBUI_AUTH=False" in env
    assert "WEBUI_URL=/chat/" in env
    assert "LOCAL_LLM_BACK_URL=/ui/" in env
    assert "ENABLE_EVALUATION_ARENA_MODELS=False" in env


def test_caddy_routes_chat_to_open_webui_and_ui_to_management():
    caddy = CADDYFILE.read_text()

    assert "handle /chat*" in caddy
    assert "← Back to local_llm" in caddy
    assert 'href=\\"/ui/\\"' in caddy
    assert 'iframe src=\\"/\\"' in caddy
    assert "100dvh" in caddy
    assert "safe-area-inset-bottom" in caddy
    assert "handle / {" in caddy
    assert "handle /static/*" in caddy
    assert "handle /_app/*" in caddy
    assert "handle /api/*" in caddy
    assert "handle /ws/socket.io*" in caddy
    assert caddy.index("handle /ws/socket.io*") < caddy.index("handle /ws/*")
    assert "reverse_proxy 127.0.0.1:3101" in caddy
    assert "handle /ui/*" in caddy
    assert "handle /api/local-llm/*" in caddy
    assert "handle /v1/*" in caddy
    assert "handle /api/models*" not in caddy
    assert "handle /api/search*" not in caddy
    assert "reverse_proxy 127.0.0.1:3100" in caddy
    assert "Fallback: Open WebUI client-side routes" in caddy
