"""Cold-start stage reporting for cluster runners.

A big MoE takes minutes to load and the only feedback was a spinner, because
`POST /clusters/{id}/start` does not return until the runner answers /v1/models.
The launch path records its stage here as it goes, and the clusters endpoints
read it back, so the UI can poll for progress while that request is still open.

In-process state on purpose: mgmt runs a single uvicorn worker, the data is
worthless once the process dies, and a file would need cleanup nobody would do.
"""

from __future__ import annotations

import threading
import time
from typing import Any

STAGES = ("stopping", "creating", "loading", "ready", "failed")

_lock = threading.Lock()
_state: dict[str, dict[str, Any]] = {}


def begin(cluster_id: str, model: str, profile: str) -> None:
    with _lock:
        _state[cluster_id] = {
            "stage": "stopping",
            "detail": "",
            "model": model,
            "profile": profile,
            "started_at": time.time(),
            "updated_at": time.time(),
            "error": None,
        }


def set_stage(cluster_id: str, stage: str, detail: str = "") -> None:
    with _lock:
        entry = _state.get(cluster_id)
        if entry is None:
            return
        entry["stage"] = stage
        entry["detail"] = detail
        entry["updated_at"] = time.time()


def finish(cluster_id: str, error: str | None = None) -> None:
    with _lock:
        entry = _state.get(cluster_id)
        if entry is None:
            return
        entry["stage"] = "failed" if error else "ready"
        entry["error"] = error
        entry["updated_at"] = time.time()


def get(cluster_id: str) -> dict[str, Any] | None:
    """Current progress for a cluster, with elapsed seconds filled in.

    A finished entry is kept so the UI can render the outcome of the launch it
    was watching; it is replaced wholesale by the next begin().
    """
    with _lock:
        entry = _state.get(cluster_id)
        if entry is None:
            return None
        return {**entry, "elapsed_s": round(time.time() - entry["started_at"], 1)}


def clear(cluster_id: str) -> None:
    with _lock:
        _state.pop(cluster_id, None)
