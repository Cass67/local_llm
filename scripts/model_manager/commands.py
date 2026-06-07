"""Commands for model-manager: init, search, install, list, status."""

from __future__ import annotations

import argparse
import json
import subprocess  # noqa: S404 # nosec: B404
from pathlib import Path

from .state import (
    RUNS_DIR,
    delete_accepted,
    get_target,
    has_default,
    list_accepted,
    load_candidates,
    read_config,
    save_candidates,
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
        existing = get_target()
        if existing:
            print(f"already initialized: target={existing}")
            return 0
        print("init requires --target local or remote:<host>")
        return 2

    write_config(target)
    print(f"initialized: target={target}")
    print(f"state={RUNS_DIR}")
    print("next=model-manager search 'coding gguf'")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    """Search for models: discover → score → save candidates → print list.

    Saves results so `install --index N` can pick one.
    """
    query = args.query or "GGUF"
    limit = args.limit or 30

    # 1. Check target
    target = get_target()
    if not target:
        print("not initialized — run: model-manager init --target remote:<host>")
        return 2

    # 2. Discover + score candidates
    print(f"searching: query={query} target={target} limit={limit}")
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
            print(f"search failed: {discovery_result.stderr.strip()}")
            return 1
        scored = json.loads(discovery_result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as e:
        print(f"search error: {e}")
        return 1

    ranked = scored.get("candidates", [])
    if not ranked:
        print("no candidates found")
        return 1

    # 3. Save candidates for install to pick from
    save_candidates(ranked)

    # 4. Print numbered list
    print(f"found {len(ranked)} candidates:")
    for i, c in enumerate(ranked, 1):
        quant = c.get("best_quant", "?")
        print(f"  {i}. {c['repo']} (score={c['score']}, quant={quant})")

    print("\ninstall with: model-manager install --index <N>")
    print("example:     model-manager install --index 2")
    return 0


def install_model(
    index: int,
    profile: str = "balanced",
    ctx: str = "32768",
) -> dict:
    """Install a model: pick candidate → download → benchmark → return result.

    Returns dict with keys: status (ok|error|benchmark_done), family, alias,
    benchmark_file, benchmark_summary, message.
    Callers decide accept/reject/skip based on benchmark_done status.
    """
    # 1. Check target
    target = get_target()
    if not target:
        return {"status": "error", "message": "not initialized"}

    host = target.split(":", 1)[1] if target.startswith("remote:") else None
    if not host:
        return {"status": "error", "message": "install requires remote target"}

    # 2. Load saved candidates
    candidates = load_candidates()
    if not candidates:
        return {"status": "error", "message": "no candidates — run search first"}

    # 3. Pick candidate by index (1-based)
    if index < 1 or index > len(candidates):
        return {"status": "error", "message": f"index {index} out of range (1-{len(candidates)})"}

    chosen = candidates[index - 1]
    chosen_repo = chosen["repo"]
    chosen_quant = chosen.get("best_quant", "unknown")
    chosen_file = chosen.get("best_file", "")

    # 4. Infer family + alias
    family = _infer_family(chosen_repo)
    alias = _infer_alias(chosen_repo)

    # 5. Download model to remote host
    download_ok = _download_on_host(host, chosen_repo, chosen_file)
    if not download_ok:
        return {"status": "error", "message": "download failed"}

    # 6. Run benchmark on remote host
    benchmark_file = _run_benchmark(
        host, chosen_repo, family, alias, profile, chosen_quant, chosen_file, ctx
    )
    if not benchmark_file:
        return {"status": "error", "message": "benchmark failed"}

    # 7. Read benchmark summary
    summary = _read_benchmark_summary(benchmark_file)

    return {
        "status": "benchmark_done",
        "family": family,
        "alias": alias,
        "benchmark_file": benchmark_file,
        "benchmark_summary": summary,
        "message": f"benchmark complete for {family}",
    }


def accept_model(benchmark_file: str, host: str) -> dict:
    """Accept and deploy a model after benchmark.

    Returns dict with status and message.
    """
    family = None
    alias = None

    if not _accept_benchmark(benchmark_file):
        return {"status": "error", "message": "accept failed"}

    if not _deploy_accepted_to_remote(host):
        return {"status": "error", "message": "deploy failed"}

    # Read accepted data to get family/alias
    accepted = list_accepted()
    if accepted:
        family, data = accepted[-1]
        alias = data.get("alias", "?")

    # Set default if none exists
    if not has_default() and family:
        write_accepted("default", {"family": family, "alias": alias})

    return {
        "status": "ok",
        "message": f"accepted: {family}" if family else "accepted",
    }


def cmd_install(args: argparse.Namespace) -> int:
    """Install a model: pick candidate → download → benchmark → ask user → accept/reject.

    Requires `search` to have been run first (saves candidates).
    After each benchmark, stops and asks user what to do.
    """
    index = args.index
    profile = args.profile or "balanced"
    ctx = args.ctx or "32768"

    result = install_model(index, profile, ctx)

    if result["status"] == "error":
        print(f"install failed: {result['message']}")
        return 1

    if result["status"] != "benchmark_done":
        print(result["message"])
        return 0

    # Print benchmark summary
    summary = result.get("benchmark_summary", {})
    print(f"\nbenchmark result: {result['benchmark_file']}")
    if "load_status" in summary:
        print(f"  load_status: {summary['load_status']}")
    if "prompt_tok_s" in summary:
        print(f"  prompt_tok_s: {summary['prompt_tok_s']}")
    if "decode_tok_s" in summary:
        print(f"  decode_tok_s: {summary['decode_tok_s']}")
    if "ctx" in summary:
        print(f"  ctx: {summary['ctx']}")

    # Ask user what to do
    family = result.get("family", "?")
    print(f"\nwhat to do with {family}?")
    print("  a) accept — create launcher and accept this model")
    print("  r) reject — discard, don't install")
    print("  s) skip — keep benchmark, decide later")
    print("  q) quit — stop install process")
    try:
        response = input("> ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\ncancelled")
        return 1

    if response == "a":
        target = get_target() or ""
        host = target.split(":", 1)[1] if target.startswith("remote:") else None
        if host:
            accept_result = accept_model(result["benchmark_file"], host)
            if accept_result["status"] == "ok":
                print(f"accepted: {family}")
                print(f"done: oc-local {family} {profile}")
            else:
                print(f"accept failed: {accept_result['message']}")
                return 1
        else:
            print("cannot accept — no remote host")
            return 1
    elif response == "r":
        print(f"rejected: {family}")
    elif response == "s":
        print(f"skipped: {family} (benchmark saved at {result['benchmark_file']})")
    elif response == "q":
        print("stopping")
        return 0
    else:
        print(f"unknown action: {response}")

    return 0


def _ensure_hf_cli(host: str) -> bool:
    """Ensure hf CLI (huggingface_hub) is installed on remote host."""
    install_cmd = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=5",
        host,
        'export PATH="$HOME/.local/bin:$PATH" && (which hf || pip3 install --quiet --break-system-packages huggingface_hub) && which hf',
    ]
    print("  ensuring hf CLI on remote...")
    try:
        result = subprocess.run(
            install_cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            print(f"  hf install failed: {result.stderr.strip()[:200]}")
            return False
        print("  hf ready")
        return True
    except subprocess.TimeoutExpired:
        print("  hf-cli install timed out")
        return False
    except OSError as e:
        print(f"  hf-cli install error: {e}")
        return False


def _download_on_host(host: str, repo: str, hf_file: str) -> bool:
    """Download model to remote host using hf CLI."""
    # hf CLI caches to ~/.cache/huggingface/hub
    repo_dir = repo.replace("/", "--")
    # Check if requested GGUF already exists on remote. Repo dir alone is not enough:
    # HF cache may contain only refs/metadata.
    if hf_file:
        check_cmd = [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=5",
            host,
            "find ~/.cache/huggingface/hub/models--"
            + repo_dir
            + " -name "
            + repr(hf_file)
            + " \( -type f -o -type l \) -print -quit | grep -q .",
        ]
        result = subprocess.run(check_cmd, capture_output=True, text=True, timeout=15)
        if result.returncode == 0:
            print(f"  model file already cached on {host}: {hf_file}")
            return True

    # Ensure hf exists
    if not _ensure_hf_cli(host):
        print("  cannot download — hf not available")
        return False

    # Clear stale locks; fix .locks dir perms if root-owned
    lock_clear = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=5",
        host,
        "sudo /usr/bin/bash -c 'chmod 1777 /home/cass/.cache/huggingface/hub/.locks' 2>/dev/null; "
        "find ~/.cache/huggingface/hub/.locks -type f -delete 2>/dev/null; "
        "find ~/.cache/huggingface/hub/.locks -type d -empty -delete 2>/dev/null; "
        "true",
    ]
    subprocess.run(lock_clear, capture_output=True, text=True, timeout=15)

    # Download via hf
    include_arg = f" --include {hf_file}" if hf_file else ""
    download_cmd = 'export PATH="$HOME/.local/bin:$PATH" && hf download ' + repo + include_arg
    ssh_cmd = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=5",
        host,
        download_cmd,
    ]
    print(f"  downloading {repo}...")
    try:
        result = subprocess.run(
            ssh_cmd,
            capture_output=True,
            text=True,
            timeout=600,
        )
        if result.returncode != 0:
            print(f"  download error: {result.stderr.strip()}")
            return False
        print("  download complete")
        return True
    except subprocess.TimeoutExpired:
        print("  download timed out after 10 minutes")
        return False
    except OSError as e:
        print(f"  download error: {e}")
        return False


def _run_benchmark(
    host: str, repo: str, family: str, alias: str, profile: str, quant: str, hf_file: str, ctx: str
) -> str | None:
    """Run benchmark on remote host, return path to benchmark result JSON."""
    # Call the bash model-manager benchmark command
    bench_cmd = [
        "model-manager",
        "benchmark",
        "--repo",
        repo,
        "--family",
        family,
        "--alias",
        alias,
        "--profiles",
        profile,
        "--quant",
        quant,
    ]
    if hf_file:
        bench_cmd.extend(["--hf-file", hf_file])
    bench_cmd.extend(["--ctx", ctx])

    print(f"  running: {' '.join(bench_cmd[:8])}...")
    try:
        result = subprocess.run(
            bench_cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )
        # Parse benchmark result file from output
        lines = result.stdout.strip().split("\n")
        for line in lines:
            if line.startswith("result_file="):
                return line.split("=", 1)[1]
        # If benchmark failed, check stderr
        if result.returncode != 0:
            print(f"  benchmark error: {result.stderr.strip()[:200]}")
        return None
    except subprocess.TimeoutExpired:
        print("  benchmark timed out after 5 minutes")
        return None
    except OSError as e:
        print(f"  benchmark error: {e}")
        return None


def _read_benchmark_summary(benchmark_file: str) -> dict:
    """Read key metrics from benchmark result JSON. Returns dict."""
    try:
        with open(benchmark_file) as f:
            data = json.load(f)
        return {
            "load_status": data.get("load_status", "unknown"),
            "prompt_tok_s": data.get("prompt_tok_s"),
            "decode_tok_s": data.get("decode_tok_s"),
            "ctx": data.get("ctx", "?"),
        }
    except (json.JSONDecodeError, OSError):
        return {"load_status": "error", "message": f"could not read {benchmark_file}"}


def _accept_benchmark(benchmark_file: str) -> bool:
    """Accept benchmark via bash pipeline."""
    accept_cmd = ["model-manager", "accept", benchmark_file]
    try:
        result = subprocess.run(
            accept_cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.stdout:
            print(result.stdout.strip())
        if result.returncode != 0:
            print(f"  accept error: {result.stderr.strip()[:500]}")
            return False
        return True
    except (subprocess.TimeoutExpired, OSError) as e:
        print(f"  accept error: {e}")
        return False


def _deploy_accepted_to_remote(host: str) -> bool:
    """Copy accepted launcher state to remote after install."""
    deploy_cmd = ["model-manager", "deploy", "--target", f"remote:{host}", "--yes"]
    print(f"deploying launchers to {host}...")
    try:
        result = subprocess.run(
            deploy_cmd,
            capture_output=True,
            text=True,
            timeout=180,
        )
        if result.stdout:
            print(result.stdout.strip())
        if result.returncode != 0:
            print(f"  deploy error: {result.stderr.strip()[:500]}")
            return False
        return True
    except (subprocess.TimeoutExpired, OSError) as e:
        print(f"  deploy error: {e}")
        return False


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
    name = repo.rsplit("/", 1)[-1]
    name = name.replace("-gguf", "").replace("_", "-")
    parts = name.split("-")
    family = "-".join(parts[:3]).lower()
    family = "".join(c for c in family if c.isalnum() or c in "._-")
    return family or "model"


def _infer_alias(repo: str) -> str:
    """Infer alias from HuggingFace repo ID."""
    name = repo.rsplit("/", 1)[-1]
    name = name.replace("-gguf", "").replace("_", "-")
    return name.lower()
