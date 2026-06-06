"""Commands for model-manager: init, install, list, status."""

from __future__ import annotations

import argparse
import json
import subprocess  # noqa: S404 # nosec: B404
from pathlib import Path

from .state import (
    ACCEPTED_DIR,
    RUNS_DIR,
    delete_accepted,
    get_target,
    has_default,
    list_accepted,
    read_config,
    write_accepted,
    write_config,
)

# Resolve sibling scripts
SCRIPT_DIR = Path(__file__).resolve().parent.parent
MODEL_DISCOVERY = SCRIPT_DIR / "model-discovery.sh"

# Profile names recognized by oc-local
PROFILES = ("speed", "fastlong", "balanced", "reliable", "tiny")


def cmd_init(args: argparse.Namespace) -> int:
    """Initialize model-manager state with a target."""
    target = args.target
    if not target:
        # Try to read from existing config
        existing = get_target()
        if existing:
            print(f"already initialized: target={existing}")
            return 0
        print("init requires --target local or remote:<host>")
        return 2

    write_config(target)
    print(f"initialized: target={target}")
    print(f"state={RUNS_DIR}")
    print("next=model-manager install 'coding gguf'")
    return 0


def cmd_install(args: argparse.Namespace) -> int:
    """Install a model: discover → score → download → accept.

    Replaces the 5-step pipeline (discover, select, benchmark, accept, deploy).
    """
    query = args.query or "GGUF"
    family = args.family
    profile = args.profile or "balanced"
    limit = args.limit or 5
    ctx = args.ctx or "32768"

    # 1. Check target
    target = get_target()
    if not target:
        print("not initialized — run: model-manager init --target remote:<host>")
        return 2

    # 2. Discover + score candidates (model-discovery.sh does both)
    print(f"discovering: query={query} target={target} limit={limit}")
    host = target.split(":", 1)[1] if target.startswith("remote:") else None

    if host:
        discovery_cmd = [
            str(MODEL_DISCOVERY),
            "--host",
            host,
            "--query",
            query,
            "--limit",
            str(limit),
            "--json",
        ]
    else:
        discovery_cmd = [
            str(MODEL_DISCOVERY),
            "--local",
            "--query",
            query,
            "--limit",
            str(limit),
            "--json",
        ]

    try:
        discovery_result = subprocess.run(  # noqa: S603 # nosec: B603
            discovery_cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if discovery_result.returncode != 0:
            print(f"discovery failed: {discovery_result.stderr.strip()}")
            return 1
        scored = json.loads(discovery_result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as e:
        print(f"discovery error: {e}")
        return 1

    ranked = scored.get("candidates", [])
    if not ranked:
        print("no candidates found")
        return 1

    print(f"found {len(ranked)} candidates")

    # 3. Pick best candidate
    best = ranked[0]
    chosen_repo = best["repo"]
    chosen_quant = best.get("best_quant", "unknown")
    chosen_file = best.get("best_file", "")

    if family:
        # User specified family — use it
        pass
    else:
        # Infer family from repo
        family = _infer_family(chosen_repo)

    alias = _infer_alias(chosen_repo)

    print(f"best: {chosen_repo} (score={best['score']}, quant={chosen_quant})")
    print(f"family={family} profile={profile}")

    # 5. Write accepted metadata
    launcher_file = f"start_{family}_{profile}.sh"

    metadata = {
        "repo": chosen_repo,
        "hf_repo": chosen_repo,
        "family": family,
        "alias": alias,
        "model_name": alias,
        "remote_start": f"./{launcher_file}",
        "launcher_file": launcher_file,
        "hf_file": chosen_file,
        "quant": chosen_quant,
        "profile": profile,
        "config": {
            "ctx": int(ctx),
            "batch": 2048,
            "ubatch": 512,
            "ngl": 99,
        },
        "target": target,
    }

    write_accepted(family, metadata)
    print(f"accepted: {family} -> {ACCEPTED_DIR}/{family}.json")

    # 6. Write default if no default exists
    if not has_default():
        write_accepted("default", {"family": family, "alias": alias})
        print(f"default set: {family}")

    print(f"done: oc-local {family} {profile}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    """List accepted models."""
    accepted = list_accepted()
    if not accepted:
        print("no accepted models")
        return 0

    print(f"accepted models ({len(accepted)}):")
    for family, data in accepted:
        alias = data.get("alias", "?")
        quant = data.get("quant", "?")
        profile = data.get("profile", "?")
        ctx = data.get("config", {}).get("ctx", "?")
        print(f"  {family}: {alias} ({quant}, profile={profile}, ctx={ctx})")

    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Show model-manager status."""
    config = read_config()
    target = config.get("target", "?") if config else "not set"

    accepted = list_accepted()
    default_ok = has_default()

    print(f"target: {target}")
    print(f"state: {RUNS_DIR}")
    print(f"accepted: {len(accepted)}")
    print(f"default: {'yes' if default_ok else 'no'}")

    if accepted:
        for family, data in accepted:
            alias = data.get("alias", "?")
            print(f"  {family}: {alias}")

    return 0


def cmd_delete(args: argparse.Namespace) -> int:
    """Delete an accepted model family."""
    family = args.family
    if not family:
        print("delete requires --family")
        return 2

    if delete_accepted(family):
        print(f"deleted: {family}")
    else:
        print(f"not found: {family}")
    return 0


# ---- Helpers ----


def _infer_family(repo: str) -> str:
    """Infer family name from HuggingFace repo ID."""
    # Use last path component, strip -gguf suffix
    name = repo.rsplit("/", 1)[-1]
    name = name.replace("-gguf", "").replace("_", "-")
    # Take first meaningful part
    parts = name.split("-")
    # Keep first 2-3 parts for readability
    family = "-".join(parts[:3]).lower()
    # Ensure safe
    family = "".join(c for c in family if c.isalnum() or c in "._-")
    return family or "model"


def _infer_alias(repo: str) -> str:
    """Infer alias from HuggingFace repo ID."""
    name = repo.rsplit("/", 1)[-1]
    name = name.replace("-gguf", "").replace("_", "-")
    return name.lower()
