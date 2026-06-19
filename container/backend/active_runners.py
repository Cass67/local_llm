"""Start/stop/status for per-cluster model instances."""

from __future__ import annotations

import http.client
import json
import logging
import time
from copy import deepcopy
from typing import Any

from . import config
from .clusters import (
    ClusterDef,
    list_active,
    list_clusters,
    list_desired,
    read_active,
    read_desired,
    remove_active,
    remove_desired,
    tensor_split_for,
    visible_devices_for,
    write_active,
    write_desired,
)
from .gpu_inventory import GpuInfo, detect_gpus
from .runtime import DockerRunner, DockerRunnerConfig

# cluster_id → monotonic timestamp of last chat request
_last_request: dict[str, float] = {}


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


def _apply_profile_config(meta: dict[str, Any]) -> None:
    """Overlay named profile config from profiles.json onto meta."""
    family = str(meta.get("family", ""))
    profile_name = str(meta.get("profile", ""))
    if not family or not profile_name:
        return
    try:
        data = json.loads(config.PROFILES_CONFIG.read_text())
    except (OSError, json.JSONDecodeError):
        return
    profile_cfg = data.get("families", {}).get(family, {}).get("profiles", {}).get(profile_name)
    if not isinstance(profile_cfg, dict):
        return
    cfg = meta.setdefault("config", {})
    for key, value in profile_cfg.items():
        if value is None:
            continue
        if key == "context":
            meta["context"] = value
            cfg["ctx"] = value  # runtime reads cfg["ctx"] first
        else:
            cfg[key] = value


def _build_launch_metadata(
    accepted: dict[str, Any], cluster: ClusterDef, inventory: list[GpuInfo]
) -> dict[str, Any]:
    """Merge accepted model metadata with cluster GPU placement."""
    meta = deepcopy(accepted)
    cfg = meta.setdefault("config", {})
    if not isinstance(cfg, dict):
        cfg = {}
        meta["config"] = cfg

    # Apply named profile config (batch, ubatch, ngl, tensor_split, etc.)
    _apply_profile_config(meta)
    cfg = meta["config"]

    cfg["backend"] = cluster.backend
    vd = visible_devices_for(cluster, inventory)
    if vd:
        cfg["visible_devices"] = vd
    n = len(cluster.gpu_pci_ids)
    if n > 1:
        cfg.setdefault("tensor_split", tensor_split_for(n))
        cfg.setdefault("split_mode", "layer")
    else:
        # Single GPU: clear any multi-GPU settings from the accepted metadata
        cfg.pop("tensor_split", None)
        cfg.pop("split_mode", None)

    return meta


def start(cluster: ClusterDef, accepted: dict[str, Any]) -> None:
    """Launch accepted model on cluster, stopping any prior instance on that cluster."""
    stop(cluster)
    inventory = detect_gpus()
    meta = _build_launch_metadata(accepted, cluster, inventory)
    visible = meta.get("config", {}).get("visible_devices", "")
    logging.info(
        "start: cluster=%s model=%s backend=%s port=%d gpus=%s visible=%s",
        cluster.name,
        accepted.get("alias") or accepted.get("family") or "?",
        cluster.backend,
        cluster.port,
        ",".join(cluster.gpu_pci_ids),
        visible,
    )
    runner = _runner_for(cluster)
    runner.launch(meta)
    if not _wait_ready(runner, cluster.port):
        logs = "\n".join(runner.logs(40)) or "runner did not become ready"
        raise RuntimeError(logs[-1000:])
    alias = str(accepted.get("alias") or accepted.get("family") or "unknown")
    state = {
        "cluster_id": cluster.id,
        "cluster_name": cluster.name,
        "model": alias,
        "family": str(accepted.get("family", alias)),
        "label": accepted.get("label") or None,
        "profile": str(accepted.get("profile", "reliable")),
        "backend": cluster.backend,
        "port": cluster.port,
        "container": cluster.container_name,
        "gpu_pci_ids": cluster.gpu_pci_ids,
    }
    write_active(cluster.id, state)
    write_desired(cluster.id, state)


def stop(cluster: ClusterDef) -> None:
    """Stop and remove the runner container for this cluster."""
    runner = _runner_for(cluster)
    try:
        runner.stop()
    except Exception:  # nosec B110
        pass
    remove_active(cluster.id)
    remove_desired(cluster.id)


def restore_desired(resolve_accepted) -> list[str]:
    """Restart desired cluster models after Docker/host reboot."""
    restored: list[str] = []
    clusters = {c.id: c for c in list_clusters()}
    for entry in list_desired():
        cluster_id = str(entry.get("cluster_id") or "")
        cluster = clusters.get(cluster_id)
        family = str(entry.get("family") or entry.get("model") or "")
        if not cluster or not family or is_running(cluster):
            continue
        try:
            accepted = resolve_accepted(family)
            accepted["profile"] = str(entry.get("profile") or accepted.get("profile") or "reliable")
            start(cluster, accepted)
            restored.append(cluster_id)
        except Exception as exc:
            logging.warning("restore %s failed: %s", cluster_id, exc)
            continue
    return restored


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


def touch(cluster_id: str) -> None:
    """Record that cluster_id just handled a request."""
    _last_request[cluster_id] = time.monotonic()


def idle_check(timeout_s: float) -> None:
    """Stop any running cluster that has been idle longer than timeout_s."""
    now = time.monotonic()
    for cluster in list_clusters():
        active = read_active(cluster.id)
        if not active:
            continue
        last = _last_request.get(cluster.id)
        if last is None:
            # No request recorded since startup — seed from now so we don't
            # immediately evict a model the user just manually started.
            _last_request[cluster.id] = now
            continue
        if now - last >= timeout_s:
            logging.info("idle_check: cluster=%s idle=%.0fs — stopping", cluster.name, now - last)
            # ponytail: keep desired so the model reloads on next request
            runner = _runner_for(cluster)
            try:
                runner.stop()
            except Exception:  # nosec B110
                pass
            remove_active(cluster.id)


def ensure_running(cluster: ClusterDef, resolve_accepted) -> None:
    """Start cluster if it is desired but not currently running."""
    if is_running(cluster):
        return
    desired = read_desired(cluster.id)
    if not desired:
        return
    family = str(desired.get("family") or desired.get("model") or "")
    if not family:
        return
    logging.info("ensure_running: auto-reloading cluster=%s model=%s", cluster.name, family)
    accepted = resolve_accepted(family)
    accepted["profile"] = str(desired.get("profile") or accepted.get("profile") or "reliable")
    start(cluster, accepted)
