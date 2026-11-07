#!/usr/bin/env python3
"""Attach a shared DS4 vision tower to an existing pack without rewriting weights."""

import argparse
import math
import os
import shutil
from pathlib import Path


def attach(pack, vision, backup, apply=False):  # noqa: C901
    import json

    info = json.loads((vision / "vision.json").read_text())
    geom = info["config"]
    data = vision / "vision.bin"
    size = data.stat().st_size
    meta = pack / "ds4.txt"
    index = pack / "tensors.txt"
    original_meta = meta.read_text()
    original_index = index.read_text()
    settings = dict(line.split(" ", 1) for line in original_meta.splitlines() if " " in line)
    if int(settings["hidden_size"]) != info["tensors"][-1][4][-1]:
        raise ValueError("Vision marker width does not match the language model")
    for name, dtype, offset, nbytes, shape in info["tensors"]:
        bad_size = offset < 0 or offset + nbytes > size or math.prod(shape) * 2 != nbytes
        if dtype != "BF16" or bad_size:
            raise ValueError(f"Invalid vision tensor: {name}")
    names = {t[0] for t in info["tensors"]}
    existing = {line.split()[1] for line in original_index.splitlines() if line.startswith("t ")}
    overlap = names & existing
    if overlap:
        if overlap != names or any(settings.get(k) != str(v) for k, v in geom.items()):
            raise ValueError("Existing vision metadata differs; refusing to replace it")
        print(f"{pack}: vision is already attached")
        return
    if any(k in settings for k in geom):
        raise ValueError("Partial vision geometry; refusing to replace it")
    lines = original_index.splitlines()
    file_id = max(int(line.split()[1]) for line in lines if line.startswith("file ")) + 1
    relative = os.path.relpath(data.resolve(), Path(settings["model_dir"]))
    if " " in relative:
        raise ValueError("Vision path contains spaces")
    first_tensor = next(i for i, line in enumerate(lines) if line.startswith("t "))
    lines.insert(first_tensor, f"file {file_id} {relative}")
    lines.extend(
        f"t {name} {dtype} {file_id} {offset} {nbytes} " + " ".join(map(str, shape))
        for name, dtype, offset, nbytes, shape in info["tensors"]
    )
    new_index = "\n".join(lines) + "\n"
    new_meta = original_meta.rstrip("\n") + "\n" + "".join(f"{k} {v}\n" for k, v in geom.items())
    print(f"{pack}: {len(names)} vision tensors, metadata only, apply={apply}")
    if not apply:
        return
    backup.mkdir(parents=True, mode=0o700, exist_ok=True)
    for original in [meta, index]:
        saved = backup / original.name
        if saved.exists():
            if saved.read_bytes() != original.read_bytes():
                raise ValueError("Backup already exists with different metadata")
        else:
            shutil.copy2(original, saved)
    for path, content in [(index, new_index), (meta, new_meta)]:
        temp = path.with_name(path.name + ".vision-new")
        with temp.open("x") as out:
            out.write(content)
        stat = path.stat()
        temp.chmod(stat.st_mode & 0o777)
        os.chown(temp, stat.st_uid, stat.st_gid)
        temp.replace(path)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pack", required=True, type=Path)
    p.add_argument("--vision", required=True, type=Path)
    p.add_argument("--backup", required=True, type=Path)
    p.add_argument("--apply", action="store_true")
    a = p.parse_args()
    attach(a.pack, a.vision, a.backup, a.apply)
