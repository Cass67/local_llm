#!/usr/bin/env python3
"""Container entrypoint: mgmt's argv -> the JSON config Maya's serve/server.py reads, then exec.

    maya-runner.py --port P --model-name NAME [--gpus 3,0,1,2] [--sampling JSON] [--server JSON] \
        [--vision-mmproj GGUF --vision-model GGUF] -- <engine args>

The engine args are the profile's `maya_args` (--glm-pack, --expert-profile, --max-context, ...);
DeepSeek-V4.1-Flash's (--pack <model>/maya-ds4, --tp, --dspark, ...) run its own engine, maya-ds4.
The GPUs are --gpus (the profile's `maya_gpus`: the split's ORDER matters, the x4 card first), else
HIP_VISIBLE_DEVICES as mgmt sets it from the cluster. server.py hands the list on to the engine.
--vision-mmproj/--vision-model (the profile's mmproj + maya_vision_model) turn images on through the
image's CPU encoder (HIP has no GPU one).
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
ap.add_argument("--vision-mmproj", default="", help="the GLM mmproj GGUF: images on")
ap.add_argument("--vision-model", default="", help="the vocab GGUF maya-vision tokenizes with")
ap.add_argument("engine_args", nargs=argparse.REMAINDER)
a = ap.parse_args()
args = a.engine_args[1:] if a.engine_args[:1] == ["--"] else a.engine_args
if bool(a.vision_mmproj) != bool(a.vision_model):
    sys.exit("maya-runner: images need both --vision-mmproj and --vision-model")
pack_flag = next((f for f in ("--glm-pack", "--pack") if f in args), None)
if pack_flag is None:
    sys.exit("maya-runner: the engine args need --glm-pack <dir> (GLM) or --pack <dir> (DeepSeek)")
deepseek = pack_flag == "--pack"
if deepseek and a.vision_mmproj:
    sys.exit(
        "maya-runner: images through the CPU encoder are GLM's; DeepSeek's need its pack's vision"
    )

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
# (GLM's; maya-ds4 measures its own picks into the pack's lt-picks.txt)
table = SRC / f"tools/hip/gfx1100-glm-hipblaslt-{hipblaslt_version()}.txt"
if table.is_file() and not deepseek:
    env["MAYA_HIPBLASLT_TUNING"] = str(table)
cfg = {
    "exe": str(SRC / "engine" / ("maya-ds4" if deepseek else "maya")),
    "cwd": str(SRC),
    "tokenizer": str(Path(args[args.index(pack_flag) + 1]) / "tokenizer"),
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
if a.vision_mmproj:
    cfg["vision"] = {
        "exe": str(SRC / "engine" / "maya-vision"),
        "mmproj": a.vision_mmproj,
        "model": a.vision_model,
        "gpu": False,
    }
cfg.update(json.loads(a.server))
# a LAN bind wants a key: the fixed dummy one mgmt sends (RUNNER_API_KEY in backend/config.py)
cfg["api_key"] = "local-llm"
# maya_server's `shared`: defaults for requests that leave them out (max_tokens, ...). server.py
# reads them only from this file, which the web app's "share with other apps" also writes.
shared = cfg.pop("shared", None)
if shared:
    Path("/opt/maya/maya-runner.shared-settings.json").write_text(json.dumps(shared, indent=1))
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
