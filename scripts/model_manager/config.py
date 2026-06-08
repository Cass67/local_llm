"""Central configuration for model-manager.

Single source of truth for:
- paths/directories
- script locations
- runtime defaults
- profiles

Imported by: state, service, tui.
"""

from __future__ import annotations

import os
from pathlib import Path

# Root directories

SCRIPT_DIR = Path(__file__).resolve().parent.parent

RUNS_DIR = Path(os.environ.get("LOCAL_LLM_RUNS_DIR", "~/.local/share/local_llm/runs")).expanduser()

ACCEPTED_DIR = RUNS_DIR / "accepted"
LAUNCHERS_DIR = RUNS_DIR / "launchers"
CANDIDATES_DIR = RUNS_DIR / "candidates"

CONFIG_FILE = RUNS_DIR / "config.json"
CANDIDATES_FILE = CANDIDATES_DIR / "latest.json"

HF_CACHE_ROOT = Path.home() / ".cache" / "huggingface" / "hub"

# Script paths

MODEL_MANAGER = SCRIPT_DIR / "model-manager.sh"
OC_LOCAL = SCRIPT_DIR / "oc-local"
MODEL_DISCOVERY = SCRIPT_DIR / "model-discovery.sh"
MODEL_FIT = SCRIPT_DIR / "model-fit.py"

SSH_BIN = "/usr/bin/ssh"

# Runtime defaults

DEFAULT_BATCH = 4096
DEFAULT_UBATCH = 256
DEFAULT_CTX = 16384

# Profiles

PROFILES = ("speed", "fastlong", "balanced", "reliable", "tiny")
