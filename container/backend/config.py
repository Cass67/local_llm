import os
from pathlib import Path

STATE_DIR = Path(os.environ.get("LOCAL_LLM_STATE_DIR", "/state"))
LLAMA_CPP_DIR = Path(os.environ.get("LLAMA_CPP_DIR", "/llama.cpp"))
MODELS_CACHE_DIR = Path(os.environ.get("MODELS_CACHE_DIR", "/models"))
LLAMA_SWAP_CONFIG = Path(os.environ.get("LLAMA_SWAP_CONFIG", "/llama-swap/config.yaml"))
DOCKER_SOCKET = Path(os.environ.get("DOCKER_SOCKET", "/var/run/docker.sock"))
LLAMA_SERVER_PORT = int(os.environ.get("LLAMA_SERVER_PORT", "8080"))
LLAMA_SWAP_URL = os.environ.get("LLAMA_SWAP_URL", f"http://127.0.0.1:{LLAMA_SERVER_PORT}").rstrip(
    "/"
)
VERSION = "0.1.0"

RUNS_DIR = STATE_DIR / "runs"
ACCEPTED_DIR = RUNS_DIR / "accepted"
LAUNCHERS_DIR = RUNS_DIR / "launchers"
SCRIPTS_DIR = Path(os.environ.get("SCRIPTS_DIR", "/scripts"))
