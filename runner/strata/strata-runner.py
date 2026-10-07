#!/usr/bin/env python3
"""Container entrypoint: mgmt's argv -> the JSON config Strata's serve/server.py reads, then exec.

    strata-runner.py --port P --model-name NAME [--layer-split S] [--sampling JSON] -- <engine args>

The engine args are the profile's `strata_args` (--pack, --native, --max-context, ...). The GPUs
come from HIP_VISIBLE_DEVICES, which mgmt sets from the cluster; server.py hands the same list on.
"""

import argparse
import json
import os
import sys
from pathlib import Path

SRC = Path("/opt/strata/src")
VENV = Path("/opt/strata/venv")

ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, required=True)
ap.add_argument("--model-name", required=True)
ap.add_argument("--layer-split", default="auto")
ap.add_argument("--sampling", default="{}", help="server.py's `sampling` defaults, as JSON")
ap.add_argument("--vision-mmproj", help="the image encoder's mmproj: images on, read on the CPU")
ap.add_argument("--server", default="{}", help="extra server.py run-config keys, as JSON")
ap.add_argument("engine_args", nargs=argparse.REMAINDER)
a = ap.parse_args()
args = a.engine_args[1:] if a.engine_args[:1] == ["--"] else a.engine_args
if "--pack" not in args:
    sys.exit("strata-runner: the engine args need --pack <dir>")

site = next(VENV.glob("lib/python3*/site-packages"))
gpus = [int(g) for g in os.environ.get("HIP_VISIBLE_DEVICES", "").split(",") if g.strip()]
# ROCm from a TheRock tarball (/opt/rocm) or the pip wheels (setup.py's rocm_root: the SDK root's
# lib, then the gfx110X family's libraries)
if Path("/opt/rocm/lib").is_dir():
    ROOT, LIB_DIRS = Path("/opt/rocm"), ["/opt/rocm/lib"]
else:
    ROOT = site / "_rocm_sdk_devel"
    LIB_DIRS = [str(ROOT / "lib"), str(site / "_rocm_sdk_libraries_gfx110X_dgpu/lib")]


def hipblaslt_version():
    """setup.py's hipblaslt_version: 1.4.1 -> 100401, from the header of the engine's ROCm."""
    v = {}
    for h in ROOT.glob("include/hipblaslt/hipblaslt-version.h"):
        for line in h.read_text().splitlines():
            f = line.split()
            # MAJOR/MINOR/PATCH only: ROCm 10's header also has a TWEAK that is a commit hash
            if (
                len(f) == 3
                and f[0] == "#define"
                and f[1]
                in ("HIPBLASLT_VERSION_MAJOR", "HIPBLASLT_VERSION_MINOR", "HIPBLASLT_VERSION_PATCH")
            ):
                v[f[1].rsplit("_", 1)[-1]] = int(f[2])
    return (
        v["MAJOR"] * 100000 + v["MINOR"] * 100 + v["PATCH"]
        if {"MAJOR", "MINOR", "PATCH"} <= v.keys()
        else None
    )


# the tuning table only for the hipBLASLt it was calibrated with (the engine refuses any other)
_t = SRC / f"tools/hip/gfx1100-hipblaslt-{hipblaslt_version()}.txt"
TABLE = str(_t) if _t.is_file() else None
cfg = {
    "exe": str(SRC / "engine" / "strata"),
    "cwd": str(SRC),
    "tokenizer": str(Path(args[args.index("--pack") + 1]) / "tokenizer"),
    "model_name": a.model_name,
    "backend": "hip",
    # the engine's own log (placement, RAM tier, errors) into `docker logs` and mgmt's log view
    "log": "/dev/stdout",
    "args": args,
    # defaults for requests that name no sampling: without them server.py samples greedy
    "sampling": json.loads(a.sampling),
    "env": {"STRATA_HIPBLASLT_TUNING": TABLE} if TABLE else {},
    "lib_dirs": LIB_DIRS,
}
if len(gpus) > 1:
    cfg["gpu"], cfg["layer_split"] = gpus, a.layer_split
elif gpus:
    cfg["gpu"] = gpus[0]

if a.vision_mmproj:
    # setup's CPU encoder settings (VISION["cpu"]); "model" is read for its vocabulary only
    cfg["vision"] = {
        "exe": str(SRC / "engine" / "strata-vision"),
        "mmproj": a.vision_mmproj,
        "model": args[args.index("--native") + 1],
        "max_tokens": 300,
    }
    # and the engine's side, as setup adds it with images: --vision and VISION["cpu"]["reserve_mib"]
    if "--vision" not in args:
        args += ["--vision"]
    if "--vram-reserve-mib" not in args:
        args += ["--vram-reserve-mib", "700"]

# e.g. {"reasoning_loop_recovery": "recover"}: server.py's opt-ins, off unless the profile sets them
cfg.update(json.loads(a.server))

conf = Path("/opt/strata/strata-runner.json")
conf.write_text(json.dumps(cfg, indent=1))
print("strata-runner:", json.dumps(cfg), flush=True)
os.execv(  # noqa: S606  # nosec B606 - replace this process with the server
    str(VENV / "bin/python"),
    [
        str(VENV / "bin/python"),
        str(SRC / "serve/server.py"),
        "--engine",
        "strata",
        "--config",
        str(conf),
        "--port",
        str(a.port),
        # LAN-facing like the llama.cpp runners: the web dashboard at http://ubt26:<port>/. Bound
        # beyond loopback, server.py trusts this PC's name and LAN addresses as Host headers;
        # STRATA_ALLOWED_HOSTS (strata_env) adds others.
        "--host",
        "0.0.0.0",  # noqa: S104  # nosec B104
    ],
)
