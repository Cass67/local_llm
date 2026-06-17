#!/usr/bin/env python3
"""List all GGUF models across the three standard cache roots.

Output: one JSON object per line with keys: repo, path, file, disk_gb, gguf
"""

import json
import pathlib
import subprocess

roots = [
    pathlib.Path.home() / ".cache" / "huggingface" / "hub",
    pathlib.Path.home() / ".cache" / "local_llm" / "models",
    pathlib.Path.home() / ".cache" / "llama.cpp",
]

seen: set[str] = set()
for root in roots:
    if not root.is_dir():
        continue
    for repo_dir in sorted(root.glob("models--*")):
        if not repo_dir.is_dir():
            continue
        repo = repo_dir.name.removeprefix("models--").replace("--", "/", 1)
        if repo in seen:
            continue
        seen.add(repo)
        ggufs = sorted(
            p for p in repo_dir.rglob("*.gguf") if not p.name.lower().startswith("mmproj")
        )
        path = str(ggufs[0] if ggufs else repo_dir)
        try:
            size = int(subprocess.check_output(["du", "-sb", str(repo_dir)], text=True).split()[0])
        except (subprocess.SubprocessError, ValueError, OSError):
            size = 0
        print(
            json.dumps(
                {
                    "repo": repo,
                    "path": path,
                    "file": pathlib.Path(path).name,
                    "disk_gb": f"{size / 1_000_000_000:.1f}" if size else "-",
                    "gguf": "yes" if ggufs else "no",
                }
            )
        )
