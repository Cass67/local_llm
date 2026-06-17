from __future__ import annotations

import time
from typing import Any


def create_install_log_lines(max_lines: int = 200) -> list[dict[str, Any]]:
    return []


def append_install_log_line(log: list[dict[str, Any]], text: str, max_lines: int = 200) -> None:
    log.append({"time": time.time(), "text": text})
    if len(log) > max_lines:
        log[:] = log[-max_lines:]


def _safe_score(c: dict[str, Any]) -> float:
    v = c.get("score", 0)
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def sort_candidates(
    candidates: list[dict[str, Any]],
    mode: str,
) -> list[dict[str, Any]]:
    """Sort candidates by score, repo, or quant."""
    if mode == "score":
        return sorted(candidates, key=_safe_score, reverse=True)
    if mode == "repo":
        return sorted(candidates, key=lambda c: c.get("repo", "").lower())
    if mode == "quant":
        return sorted(candidates, key=lambda c: c.get("best_quant", ""))
    return candidates


def filter_candidates(
    candidates: list[dict[str, Any]],
    text: str,
) -> list[dict[str, Any]]:
    """Filter candidates by substring in repo, score, or quant."""
    text = (text or "").strip()
    if not text:
        return candidates
    lower = text.lower()
    return [
        c
        for c in candidates
        if any(
            lower in str(c.get(k, "")).lower() for k in ("repo", "score", "best_quant", "best_file")
        )
    ]


def paginate_candidates(
    candidates: list[dict[str, Any]],
    page: int,
    per_page: int,
) -> tuple[int, int, list[dict[str, Any]]]:
    """Return (page, total_pages, page_items), clamping page if out of range."""
    if page < 1:
        page = 1
    total = len(candidates)
    total_pages = max(1, (total + per_page - 1) // per_page) if total else 1
    if page > total_pages:
        page = total_pages
    start = (page - 1) * per_page
    end = start + per_page
    return page, total_pages, candidates[start:end]
