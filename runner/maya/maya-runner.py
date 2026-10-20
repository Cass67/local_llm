#!/usr/bin/env python3
"""Container entrypoint: mgmt's argv -> the JSON config Maya's serve/server.py reads, then exec.

    maya-runner.py --port P --model-name NAME [--gpus 3,0,1,2] [--sampling JSON] [--server JSON] \
        -- <engine args>

The engine args are the profile's `maya_args` (--glm-pack, --expert-profile, --max-context, ...).
The GPUs are --gpus (the profile's `maya_gpus`: the split's ORDER matters, the x4 card first), else
HIP_VISIBLE_DEVICES as mgmt sets it from the cluster. server.py hands the list on to the engine.
"""

import argparse
import json
import os
import sys
from pathlib import Path

SRC = Path("/opt/maya/src")
VENV = Path("/opt/maya/venv")
ROCM = Path("/opt/rocm")

ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, required=True)
ap.add_argument("--model-name", required=True)
ap.add_argument("--gpus", default="", help="KFD indices in split order, e.g. 3,0,1,2")
ap.add_argument("--sampling", default="{}", help="server.py's `sampling` defaults, as JSON")
ap.add_argument("--server", default="{}", help="extra server.py run-config keys, as JSON")
ap.add_argument("engine_args", nargs=argparse.REMAINDER)
a = ap.parse_args()
args = a.engine_args[1:] if a.engine_args[:1] == ["--"] else a.engine_args
if "--glm-pack" not in args:
    sys.exit("maya-runner: the engine args need --glm-pack <dir>")

gpus = [
    int(g) for g in (a.gpus or os.environ.get("HIP_VISIBLE_DEVICES", "")).split(",") if g.strip()
]
# the engine renumbers from the list server.py exports; an outer one would remap it first
os.environ.pop("HIP_VISIBLE_DEVICES", None)


def hipblaslt_version():
    """maya.py's hipblaslt_version: 1.4.1 -> 100401, from the header of the engine's ROCm."""
    v = {}
    for line in (ROCM / "include/hipblaslt/hipblaslt-version.h").read_text().splitlines():
        f = line.split()
        if (
            len(f) == 3
            and f[0] == "#define"
            and f[1].rsplit("_", 1)[-1] in ("MAJOR", "MINOR", "PATCH")
        ):
            v[f[1].rsplit("_", 1)[-1]] = int(f[2])
    return v["MAJOR"] * 100000 + v["MINOR"] * 100 + v["PATCH"]


env = {}
# the engine accepts a table only for its own hipBLASLt; others fall back to plain hipBLAS
table = SRC / f"tools/hip/gfx1100-glm-hipblaslt-{hipblaslt_version()}.txt"
if table.is_file():
    env["MAYA_HIPBLASLT_TUNING"] = str(table)
cfg = {
    "exe": str(SRC / "engine" / "maya"),
    "cwd": str(SRC),
    "tokenizer": str(Path(args[args.index("--glm-pack") + 1]) / "tokenizer"),
    "model_name": a.model_name,
    "backend": "hip",
    # the engine's own log (placement, tiers, glm stat lines) into `docker logs` and mgmt's log view
    "log": "/dev/stdout",
    "args": args,
    # defaults for requests that name no sampling: without them server.py samples greedy
    "sampling": json.loads(a.sampling),
    "env": env,
    "lib_dirs": [str(ROCM / "lib")],
    "gpu": gpus if len(gpus) > 1 else (gpus[0] if gpus else 0),
}
cfg.update(json.loads(a.server))
# a LAN bind wants a key: the fixed dummy one mgmt sends (RUNNER_API_KEY in backend/config.py)
cfg["api_key"] = "local-llm"

conf = Path("/opt/maya/maya-runner.json")
conf.write_text(json.dumps(cfg, indent=1))
print("maya-runner:", json.dumps(cfg), flush=True)
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
        "--host",
        "0.0.0.0",  # noqa: S104  # nosec B104
    ],
)
