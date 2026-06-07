#!/usr/bin/env python3
"""Rank GGUF model candidates against local_llm heterogeneous hybrid hardware."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from typing import Any

# Updated with modern exact bit-per-weight coefficients including extra-large/small block variants
QUANTS: tuple[tuple[str, float], ...] = (
    ("Q8_0", 8.5),
    ("Q6_K_XL", 6.9),
    ("Q6_K", 6.6),
    ("Q5_K_M", 5.5),
    ("Q4_K_M", 4.8),
    ("IQ4_XS", 4.25),
    ("Q3_K_M", 3.75),
    ("Q2_K", 2.75),
)
VRAM_RESERVE = 0.92


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rank GGUF candidates for local_llm heterogeneous hardware"
    )
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
    if params_b <= 45:
        return "target"  # Upgraded to comfortably catch 35B models as prime target
    if params_b >= 70:
        return "huge"
    return "large"


def memory_for(params_b: float, quant_bpp: float, context: int) -> float:
    # GGUF weights size formula: (Parameters * BitsPerPixel / 8 bits) * 1.06 structure overhead
    weights = (params_b * quant_bpp / 8.0) * 1.06
    # Context scaling calculation
    kv_cache = max(0.2, (context / 8192) * (params_b / 10) * 0.18)
    return weights + kv_cache


def choose_quant(params_b: float, vram_gb: float, context: int) -> tuple[str, float]:
    # Match string token mapping safely
    fallback_q, fallback_bpp = QUANTS[-1]
    fallback = (fallback_q, memory_for(params_b, fallback_bpp, context))

    for quant, bpp in QUANTS:
        required = memory_for(params_b, bpp, context)
        if required <= vram_gb:
            return quant, required
    return fallback


def quant_from_filename(filename: str) -> str | None:
    stem = filename.rsplit("/", 1)[-1].removesuffix(".gguf")
    match = re.search(r"((?:UD-)?(?:IQ|TQ|Q)\d(?:_[A-Z0-9_]+)+)", stem, re.IGNORECASE)
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
    if required <= available * 0.90:
        return "good"
    return "marginal"


def parse_hardware(hardware: dict[str, Any]) -> tuple[float, list[dict[str, Any]]]:
    """Parse unified JSON hardware fields to elegantly support standalone or dual setups."""
    gpus = hardware.get("gpus", [])

    # If using legacy flat format, automatically upconvert into structured multi-gpu list
    if not gpus and ("vram_gb" in hardware or "gpu_name" in hardware):
        gpus = [
            {
                "name": hardware.get("gpu_name") or "generic",
                "vram_gb": float(hardware.get("vram_gb") or 20.0),
                "bandwidth": float(hardware.get("bandwidth") or 512.0),
            }
        ]

    total_vram = 0.0
    processed_gpus = []

    for gpu in gpus:
        name = str(gpu.get("name") or "").lower()
        vram = float(gpu.get("vram_gb") or 0.0)

        # Determine exact theoretical bandwidth profile if not explicitly set
        bw = gpu.get("bandwidth")
        if bw is None:
            if "7900" in name:
                bw = 800.0  # High-speed AMD GDDR6 bus
            elif "p40" in name:
                bw = 346.0  # Legacy Nvidia Pascal architecture bus
            elif "4090" in name:
                bw = 1008.0
            elif any(m in name for m in ["apple", "m1", "m2", "m3", "m4"]):
                bw = 400.0
            else:
                bw = 400.0  # Safe modern baseline default

        total_vram += vram
        processed_gpus.append({"name": name, "vram": vram, "bandwidth": float(bw)})

    # Sort descending by speed to prioritize filling faster memory layers first.
    # Example: 7900 XT before P40.
    processed_gpus.sort(key=lambda x: x["bandwidth"], reverse=True)
    return total_vram, processed_gpus


def calculate_mixed_tps(
    params_b: float, quant: str, file_size_gb: float, gpus: list[dict[str, Any]]
) -> float:
    """Calculates weighted effective processing speed across different hardware bounds."""
    if not gpus:
        return 0.1

    # Standardize string token for dict parsing
    base_quant = quant.split("_XL")[0].split("_XS")[0]

    # Extract structural bits-per-weight lookup table
    bpp_dict = dict(QUANTS)
    bpp = bpp_dict.get(quant, bpp_dict.get(base_quant, 5.0))

    remaining_bytes = file_size_gb * 1073741824
    gpu_time_slices = []

    # Walk down the available GPUs (fastest to slowest) to simulate layer loading splits
    for gpu in gpus:
        if remaining_bytes <= 0:
            break
        gpu_capacity_bytes = gpu["vram"] * 1073741824 * VRAM_RESERVE
        bytes_on_this_gpu = min(remaining_bytes, gpu_capacity_bytes)

        # Time taken to fetch weights from this card's VRAM pool
        # Bandwidth is converted from GB/s to Bytes/s
        time_on_gpu = bytes_on_this_gpu / (gpu["bandwidth"] * 1000000000)
        gpu_time_slices.append(time_on_gpu)
        remaining_bytes -= bytes_on_this_gpu

    # System RAM offload spill penalties
    if remaining_bytes > 0:
        time_on_cpu = remaining_bytes / (
            32.0 * 1000000000
        )  # Standard PCIE/DDR system RAM fallback line
        gpu_time_slices.append(time_on_cpu)

    total_layer_fetch_time = sum(gpu_time_slices)
    if total_layer_fetch_time <= 0:
        return 0.1

    # Compute active computational load footprint ratio
    # MoE models execute much faster due to lower active compute weight relative to data size
    raw_tps = (1.0 / total_layer_fetch_time) * (file_size_gb / (params_b * (bpp / 8.0)))
    return max(0.1, raw_tps * 0.85)  # General architectural latency deduction factor


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
    context = 131072

    # Call our clean unified hardware parser
    vram_pool, gpus = parse_hardware(hardware)

    best_file, file_quant, file_required = choose_file(item, vram_pool)
    if file_required is not None:
        quant = file_quant or "unknown"
        required = file_required
    else:
        quant, required = choose_quant(params_for_memory, vram_pool, context)

    fit = fit_level(required, vram_pool)
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
        notes.append(
            f"MoE Architecture Detected: {active_params:g}B active / "
            f"{total_params:g}B total structural framework."
        )

    if len(gpus) > 1:
        notes.append(
            f"Asymmetric Split Engaged: Parallel pooling across {len(gpus)} distinct discrete GPUs."
        )

    if fit == "too_tight":
        notes.append(
            "Warning: Model size footprint overflows target hardware total VRAM cache capabilities."
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
        "estimated_tps": round(calculate_mixed_tps(params_for_speed, quant, required, gpus), 2),
        "memory_required_gb": round(required, 2),
        "memory_available_gb": round(vram_pool, 2),
        "downloads": int(downloads),
        "likes": int(likes),
        "notes": notes,
    }


def param_bucket(params_b: float | None) -> str:
    if params_b is None:
        return "unknown"
    if params_b < 4:
        return "<4B"
    if params_b < 8:
        return "4-8B"
    if params_b < 14:
        return "8-14B"
    if params_b < 22:
        return "14-22B"
    if params_b < 32:
        return "22-32B"
    if params_b < 45:
        return "32-45B"
    if params_b < 70:
        return "45-70B"
    return "70B+"


def quant_bucket(quant: str | None) -> str:
    value = (quant or "unknown").upper()
    if "Q8" in value or "8_" in value:
        return "Q8"
    if "Q6" in value or "6_" in value:
        return "Q6"
    if "Q5" in value or "5_" in value:
        return "Q5"
    if "Q4" in value or "4_" in value:
        return "Q4"
    if "Q3" in value or "IQ3" in value:
        return "Q3"
    if "Q2" in value or "IQ2" in value:
        return "Q2"
    if "FP8" in value or "F8" in value:
        return "FP8"
    return value.split("_", 1)[0]


def family_bucket(repo: str) -> str:
    name = repo.lower().rsplit("/", 1)[-1]
    name = re.sub(r"(?:gguf|q\d[^-]*|iq\d[^-]*|fp8|awq|gptq|uncensored|abliterated)", "", name)
    name = re.sub(r"[-_]+", "-", name).strip("-")
    parts = [
        part
        for part in name.split("-")
        if not re.fullmatch(r"\d+(?:\.\d+)?b|a\d+(?:\.\d+)?b", part)
    ]
    return "-".join(parts[:4]) or repo.lower()


def diversified_candidates(ranked: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    selected_repos: set[str] = set()

    def add_pass(key_func, max_per_key: int) -> None:
        counts: dict[tuple[Any, ...], int] = {}
        for item in ranked:
            if len(selected) >= limit:
                return
            repo = item["repo"]
            if repo in selected_repos:
                continue
            key = key_func(item)
            if counts.get(key, 0) >= max_per_key:
                continue
            selected.append(item)
            selected_repos.add(repo)
            counts[key] = counts.get(key, 0) + 1

    # First pass: strongest diversity across family + parameter + quant buckets.
    add_pass(
        lambda item: (
            family_bucket(str(item["repo"])),
            param_bucket(item.get("params_b")),
            quant_bucket(item.get("best_quant")),
        ),
        1,
    )
    # Second pass: allow another quant per family/param bucket.
    add_pass(
        lambda item: (family_bucket(str(item["repo"])), param_bucket(item.get("params_b"))),
        2,
    )
    # Final pass: fill by score.
    add_pass(lambda item: ("all",), limit)
    return selected[:limit]


def main() -> int:
    args = parse_args()
    hardware = json.loads(args.hardware_json)
    if not isinstance(hardware, dict):
        raise SystemExit("--hardware-json must be a JSON object")

    ranked = [
        candidate for item in load_json_stdin() if (candidate := score_candidate(item, hardware))
    ]
    ranked.sort(
        key=lambda item: (item["score"], item["estimated_tps"], item["downloads"]), reverse=True
    )
    selected = diversified_candidates(ranked, args.limit)

    payload = {
        "query": args.query,
        "hardware": hardware,
        "total_candidates": len(ranked),
        "candidates": selected,
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
            f"tps={candidate['estimated_tps']} | score={candidate['score']:.2f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
