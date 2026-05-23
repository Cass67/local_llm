#!/usr/bin/env python3
"""Rank GGUF model candidates against local_llm target hardware."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from typing import Any

QUANTS: tuple[tuple[str, float], ...] = (
    ("Q8_0", 1.0),
    ("Q6_K", 0.75),
    ("Q5_K_M", 0.625),
    ("Q4_K_M", 0.5),
    ("IQ4_XS", 0.47),
    ("Q3_K_M", 0.375),
    ("Q2_K", 0.25),
)
VRAM_RESERVE = 0.92


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rank GGUF candidates for local_llm hardware")
    parser.add_argument("--hardware-json", default="{}", help="hardware facts as JSON")
    parser.add_argument("--limit", type=int, default=8, help="maximum candidates to output")
    parser.add_argument("--query", default="", help="search query used for metadata only")
    parser.add_argument("--json", action="store_true", help="write JSON output")
    return parser.parse_args()


def load_json_stdin() -> list[dict[str, Any]]:
    raw = sys.stdin.read().strip()
    if not raw:
        return []
    data = json.loads(raw)
    if not isinstance(data, list):
        raise SystemExit("expected a JSON array of Hugging Face candidates")
    return [item for item in data if isinstance(item, dict)]


def repo_id(item: dict[str, Any]) -> str:
    return str(item.get("id") or item.get("repo") or item.get("name") or "")


def is_gguf(item: dict[str, Any]) -> bool:
    repo = repo_id(item).lower()
    tags = [str(tag).lower() for tag in item.get("tags", []) if isinstance(tag, str)]
    return repo.endswith("-gguf") or repo.endswith("/gguf") or "gguf" in tags


def infer_params(repo: str) -> tuple[float | None, float | None]:
    text = repo.replace("_", "-")
    moe = re.search(r"(\d+(?:\.\d+)?)B-A(\d+(?:\.\d+)?)B", text, re.IGNORECASE)
    if moe:
        return float(moe.group(1)), float(moe.group(2))
    dense = re.search(r"(?<![A-Za-z0-9])(\d+(?:\.\d+)?)B(?![A-Za-z0-9])", text, re.IGNORECASE)
    if dense:
        return float(dense.group(1)), None
    return None, None


def infer_use_case(repo: str, tags: list[str]) -> str:
    lower = repo.lower()
    tag_text = " ".join(tags).lower()
    if "coder" in lower or "code" in lower or "code" in tag_text:
        return "coding"
    if "reason" in lower or "reasoning" in tag_text or "r1" in lower or "gpt-oss" in lower:
        return "reasoning"
    if "vision" in lower or "vl" in lower or "multimodal" in tag_text:
        return "multimodal"
    return "chat"


def size_class(params_b: float | None) -> str:
    if params_b is None:
        return "unknown"
    if params_b < 10:
        return "small"
    if params_b <= 40:
        return "target"
    if params_b >= 70:
        return "huge"
    return "large"


def memory_for(params_b: float, quant_bpp: float, context: int) -> float:
    weights = params_b * quant_bpp * 1.12
    kv_cache = max(0.2, (context / 8192) * (params_b / 10) * 0.18)
    return weights + kv_cache


def choose_quant(params_b: float, vram_gb: float, context: int) -> tuple[str, float]:
    fallback = (QUANTS[-1][0], memory_for(params_b, QUANTS[-1][1], context))
    for quant, bpp in QUANTS:
        required = memory_for(params_b, bpp, context)
        if required <= vram_gb:
            return quant, required
    return fallback


def quant_from_filename(filename: str) -> str | None:
    stem = filename.rsplit("/", 1)[-1].removesuffix(".gguf")
    match = re.search(r"((?:UD-)?(?:IQ|TQ|Q)\d(?:_[A-Z0-9]+)+)", stem, re.IGNORECASE)
    return match.group(1).upper() if match else None


def gguf_files(item: dict[str, Any]) -> list[dict[str, Any]]:
    raw_files = item.get("gguf_files") or item.get("siblings") or []
    files = []
    for raw in raw_files:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("rfilename") or raw.get("path") or raw.get("name") or "")
        if not name.lower().endswith(".gguf"):
            continue
        size = raw.get("size")
        if not isinstance(size, int | float) or size <= 0:
            continue
        files.append({"name": name, "size": float(size), "quant": quant_from_filename(name)})
    return files


def choose_file(
    item: dict[str, Any], vram_gb: float
) -> tuple[str | None, str | None, float | None]:
    files = gguf_files(item)
    if not files:
        return None, None, None
    fit_limit = vram_gb * VRAM_RESERVE
    files.sort(key=lambda file: file["size"])
    fitting = [file for file in files if file["size"] / 1073741824 <= fit_limit]
    selected = fitting[-1] if fitting else files[0]
    return selected["name"], selected["quant"], selected["size"] / 1073741824


def fit_level(required: float, available: float) -> str:
    if required > available:
        return "too_tight"
    if required <= available * 0.72:
        return "perfect"
    if required <= available * 0.9:
        return "good"
    return "marginal"


def estimate_tps(params_b: float, quant: str, hardware: dict[str, Any]) -> float:
    gpu_name = str(hardware.get("gpu_name") or "").lower()
    if "7900" in gpu_name:
        bandwidth = 800.0
    elif "4090" in gpu_name:
        bandwidth = 1008.0
    elif (
        "apple" in gpu_name
        or "m4" in gpu_name
        or "m3" in gpu_name
        or "m2" in gpu_name
        or "m1" in gpu_name
    ):
        bandwidth = 400.0
    else:
        bandwidth = 512.0
    bpp = dict(QUANTS).get(quant, 0.5)
    return max(0.1, (bandwidth / max(params_b * bpp, 0.1)) * 0.5)


def score_candidate(item: dict[str, Any], hardware: dict[str, Any]) -> dict[str, Any] | None:
    if not is_gguf(item):
        return None
    repo = repo_id(item)
    total_params, active_params = infer_params(repo)
    tags = [str(tag) for tag in item.get("tags", []) if isinstance(tag, str)]
    use_case = infer_use_case(repo, tags)
    cls = size_class(total_params)
    params_for_memory = total_params or 30.0
    params_for_speed = active_params or total_params or 30.0
    context = 65536 if params_for_memory >= 10 else 32768
    vram = float(hardware.get("vram_gb") or 20.0)
    best_file, file_quant, file_required = choose_file(item, vram)
    if file_required is not None:
        quant = file_quant or "unknown"
        required = file_required
    else:
        quant, required = choose_quant(params_for_memory, vram, context)
    fit = fit_level(required, vram)
    downloads = float(item.get("downloads") or 0)
    likes = float(item.get("likes") or 0)

    fit_points = {"perfect": 35.0, "good": 28.0, "marginal": 16.0, "too_tight": -25.0}[fit]
    class_points = {"target": 24.0, "large": 12.0, "small": 4.0, "huge": -24.0, "unknown": -4.0}[
        cls
    ]
    use_points = {"coding": 18.0, "reasoning": 10.0, "chat": 8.0, "multimodal": 7.0}[use_case]
    popularity = min(10.0, math.log10(downloads + 1) * 2.0 + math.log10(likes + 1) * 1.5)
    repo_bonus = 8.0 if repo.lower().startswith(("unsloth/", "bartowski/")) else 0.0
    score = max(0.0, min(100.0, fit_points + class_points + use_points + popularity + repo_bonus))

    notes = []
    if active_params is not None and total_params is not None:
        notes.append(f"MoE-like name: {active_params:g}B active of {total_params:g}B total")
    if fit == "too_tight":
        notes.append(
            "Estimated to exceed target VRAM; benchmark only if there is a specific reason"
        )

    return {
        "repo": repo,
        "params_b": total_params,
        "active_params_b": active_params,
        "context": context,
        "use_case": use_case,
        "size_class": cls,
        "fit_level": fit,
        "run_mode": "gpu" if fit != "too_tight" else "cpu_or_offload",
        "score": round(score, 2),
        "best_quant": quant,
        "best_file": best_file,
        "estimated_tps": round(estimate_tps(params_for_speed, quant, hardware), 2),
        "memory_required_gb": round(required, 2),
        "memory_available_gb": round(vram, 2),
        "downloads": int(downloads),
        "likes": int(likes),
        "notes": notes,
    }


def main() -> int:
    args = parse_args()
    hardware = json.loads(args.hardware_json)
    if not isinstance(hardware, dict):
        raise SystemExit("--hardware-json must be a JSON object")
    ranked = [
        candidate for item in load_json_stdin() if (candidate := score_candidate(item, hardware))
    ]
    ranked.sort(key=lambda item: (item["score"], item["downloads"]), reverse=True)
    payload = {
        "query": args.query,
        "hardware": hardware,
        "total_candidates": len(ranked),
        "candidates": ranked[: args.limit],
    }
    if args.json:
        print(json.dumps(payload, separators=(",", ":")))
        return 0
    for candidate in payload["candidates"]:
        params = "unknown" if candidate["params_b"] is None else f"{candidate['params_b']:g}B"
        print(
            f"{candidate['repo']} | purpose={candidate['use_case']} | "
            f"class={candidate['size_class']} | "
            f"params={params} | fit={candidate['fit_level']} | quant={candidate['best_quant']} | "
            f"score={candidate['score']:.2f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
