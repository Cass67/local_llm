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
ap.add_argument("engine_args", nargs=argparse.REMAINDER)
a = ap.parse_args()
args = a.engine_args[1:] if a.engine_args[:1] == ["--"] else a.engine_args
if "--pack" not in args:
    sys.exit("strata-runner: the engine args need --pack <dir>")

site = next(VENV.glob("lib/python3*/site-packages"))
gpus = [int(g) for g in os.environ.get("HIP_VISIBLE_DEVICES", "").split(",") if g.strip()]
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
    "env": {"STRATA_HIPBLASLT_TUNING": str(SRC / "tools/hip/gfx1100-hipblaslt-100200.txt")},
    # setup.py's rocm_root: the SDK root's lib first, then the gfx110X family's libraries
    "lib_dirs": [
        str(site / "_rocm_sdk_devel/lib"),
        str(site / "_rocm_sdk_libraries_gfx110X_dgpu/lib"),
    ],
}
if len(gpus) > 1:
    cfg["gpu"], cfg["layer_split"] = gpus, a.layer_split
elif gpus:
    cfg["gpu"] = gpus[0]

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
    ],
)
