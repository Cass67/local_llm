"""Start/stop/status for per-cluster model instances."""

from __future__ import annotations

import http.client
import time
from copy import deepcopy
from typing import Any

from . import config
from .clusters import (
    ClusterDef,
    list_active,
    remove_active,
    tensor_split_for,
    visible_devices_for,
    write_active,
)
from .gpu_inventory import GpuInfo, detect_gpus
from .runtime import DockerRunner, DockerRunnerConfig


def _runner_for(cluster: ClusterDef) -> DockerRunner:
    return DockerRunner(
        DockerRunnerConfig(
            image=config.runner_image_for_backend(cluster.backend),
            name=cluster.container_name,
            port=cluster.port,
            socket_path=config.DOCKER_SOCKET,
        ),
        models_dir=config.MODELS_CACHE_DIR,
        host_models_dir=config.HOST_MODELS_CACHE_DIR,
    )


def _wait_ready(runner: DockerRunner, port: int, timeout: float = 120.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not runner.is_running():
            return False
        conn: http.client.HTTPConnection | None = None
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
            conn.request("GET", "/v1/models")
            resp = conn.getresponse()
            if resp.status == 200:
                return True
        except OSError:
            pass
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:  # nosec B110
                    pass
        time.sleep(1)
    return False


def _build_launch_metadata(
    accepted: dict[str, Any], cluster: ClusterDef, inventory: list[GpuInfo]
) -> dict[str, Any]:
    """Merge accepted model metadata with cluster GPU placement."""
    meta = deepcopy(accepted)
    cfg = meta.setdefault("config", {})
    if not isinstance(cfg, dict):
        cfg = {}
        meta["config"] = cfg

    cfg["backend"] = cluster.backend
    vd = visible_devices_for(cluster, inventory)
    if vd:
        cfg["visible_devices"] = vd
    n = len(cluster.gpu_pci_ids)
    if n > 1:
        cfg.setdefault("tensor_split", tensor_split_for(n))
        cfg.setdefault("split_mode", "layer")

    return meta


def start(cluster: ClusterDef, accepted: dict[str, Any]) -> None:
    """Launch accepted model on cluster, stopping any prior instance on that cluster."""
    stop(cluster)
    inventory = detect_gpus()
    meta = _build_launch_metadata(accepted, cluster, inventory)
    runner = _runner_for(cluster)
    runner.launch(meta)
    if not _wait_ready(runner, cluster.port):
        logs = "\n".join(runner.logs(40)) or "runner did not become ready"
        raise RuntimeError(logs[-1000:])
    alias = str(accepted.get("alias") or accepted.get("family") or "unknown")
    write_active(
        cluster.id,
        {
            "cluster_id": cluster.id,
            "cluster_name": cluster.name,
            "model": alias,
            "family": str(accepted.get("family", alias)),
            "profile": str(accepted.get("profile", "reliable")),
            "backend": cluster.backend,
            "port": cluster.port,
            "container": cluster.container_name,
            "gpu_pci_ids": cluster.gpu_pci_ids,
        },
    )


def stop(cluster: ClusterDef) -> None:
    """Stop and remove the runner container for this cluster."""
    runner = _runner_for(cluster)
    try:
        runner.stop()
    except Exception:  # nosec B110
        pass
    remove_active(cluster.id)


def is_running(cluster: ClusterDef) -> bool:
    return _runner_for(cluster).is_running()


def runner_url_for_model(model_id: str) -> str | None:
    """Return http://127.0.0.1:PORT/v1 for whichever active cluster hosts model_id."""
    for entry in list_active():
        if entry.get("model") == model_id or entry.get("family") == model_id:
            port = entry.get("port")
            if isinstance(port, int):
                return f"http://127.0.0.1:{port}/v1"
    return None
