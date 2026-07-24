"""GPU cluster definitions: user-declared groups of GPUs that each host one model."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from . import config
from .gpu_inventory import GpuInfo

# rocmfp4: same AMD/HIP device wiring as rocm, but the runner image is built from
# the ROCmFPX fork (ROCmFP4 weight quants + MTP self-speculation).
# laguna: Vulkan device wiring (portable across AMD+NVIDIA), image built from
# poolside's llama.cpp fork for Laguna models + DFlash speculative decoding.
_VALID_BACKENDS = {"rocm", "rocmfp4", "vulkan", "cuda", "laguna"}
_SINGLE_VENDOR_BACKENDS = {"rocm": "amd", "rocmfp4": "amd", "cuda": "nvidia"}

# Base port for cluster-allocated runner ports (8080 + cluster slot)
_PORT_BASE = config.LLAMA_SERVER_PORT
_CONTAINER_PREFIX = "local-llm-runner-cluster"


def clusters_dir() -> Path:
    d = config.RUNS_DIR / "clusters"
    d.mkdir(parents=True, exist_ok=True)
    return d


def active_dir() -> Path:
    d = config.RUNS_DIR / "active"
    d.mkdir(parents=True, exist_ok=True)
    return d


def desired_dir() -> Path:
    d = config.RUNS_DIR / "desired"
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass
class ClusterDef:
    id: str
    name: str
    gpu_pci_ids: list[str]
    backend: str
    port: int
    container_name: str


def _sanitize_name(name: str) -> str:
    """Produce a docker-safe container name suffix from a user-provided name."""
    return re.sub(r"[^a-zA-Z0-9_.-]", "-", name).strip("-")[:40]


def _allocate_port(existing_ports: set[int]) -> int:
    """Find the next free port above PORT_BASE not already in use by a cluster."""
    import socket as _socket

    for offset in range(100):
        port = _PORT_BASE + offset
        if port in existing_ports:
            continue
        with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as s:
            s.settimeout(0.2)
            try:
                s.connect(("127.0.0.1", port))
            except OSError:
                return port  # port is free
    raise RuntimeError("no free port found in range")


def list_clusters() -> list[ClusterDef]:
    clusters = []
    for f in sorted(clusters_dir().glob("*.json")):
        try:
            data = json.loads(f.read_text())
            clusters.append(ClusterDef(**data))
        except (OSError, json.JSONDecodeError, TypeError):
            continue
    return clusters


def get_cluster(cluster_id: str) -> ClusterDef | None:
    path = clusters_dir() / f"{cluster_id}.json"
    if not path.exists() or path.is_symlink():
        return None
    try:
        return ClusterDef(**json.loads(path.read_text()))
    except (OSError, json.JSONDecodeError, TypeError):
        return None


def _validate_cluster(
    name: str, gpu_pci_ids: list[str], backend: str, inventory: list[GpuInfo]
) -> None:
    if backend not in _VALID_BACKENDS:
        raise ValueError(f"backend must be one of: {', '.join(sorted(_VALID_BACKENDS))}")
    if not gpu_pci_ids:
        raise ValueError("cluster must include at least one GPU")

    required_vendor = _SINGLE_VENDOR_BACKENDS.get(backend)
    if required_vendor:
        inv_map = {g.pci_id: g.vendor for g in inventory}
        for pci in gpu_pci_ids:
            vendor = inv_map.get(pci, "unknown")
            if vendor != required_vendor:
                raise ValueError(
                    f"backend '{backend}' requires {required_vendor} GPUs; "
                    f"GPU {pci} has vendor '{vendor}'"
                )


def create_cluster(
    name: str, gpu_pci_ids: list[str], backend: str, inventory: list[GpuInfo]
) -> ClusterDef:
    _validate_cluster(name, gpu_pci_ids, backend, inventory)
    existing = list_clusters()
    existing_ports = {c.port for c in existing}
    port = _allocate_port(existing_ports)
    cluster_id = str(uuid.uuid4())[:8]
    safe = _sanitize_name(name)
    container_name = f"{_CONTAINER_PREFIX}-{safe}-{cluster_id}"
    cluster = ClusterDef(
        id=cluster_id,
        name=name,
        gpu_pci_ids=list(gpu_pci_ids),
        backend=backend,
        port=port,
        container_name=container_name,
    )
    path = clusters_dir() / f"{cluster_id}.json"
    path.write_text(json.dumps(asdict(cluster), indent=2, sort_keys=True) + "\n")
    return cluster


def delete_cluster(cluster_id: str) -> None:
    """Delete cluster def. Caller must stop any running instance first."""
    path = clusters_dir() / f"{cluster_id}.json"
    if path.exists():
        path.unlink()


def visible_devices_for(cluster: ClusterDef, inventory: list[GpuInfo]) -> str:
    """Return comma-separated backend device indices for this cluster."""
    inv_map = {g.pci_id: g for g in inventory}
    cluster_vendors = {inv_map[p].vendor for p in cluster.gpu_pci_ids if p in inv_map}
    is_mixed = cluster.backend == "mixed_vulkan" or (
        cluster.backend == "laguna" and {"amd", "nvidia"} <= cluster_vendors
    )
    if is_mixed:
        # Container enumerates NVIDIA (via nvidia_egl ICD) before AMD (via radeon ICD).
        # Assign sequential indices: NVIDIA cards first, then AMD by rocm_index.
        nvidia = sorted(
            [g for g in inventory if g.pci_id in set(cluster.gpu_pci_ids) and g.vendor == "nvidia"],
            key=lambda g: g.cuda_index or 0,
        )
        amd = sorted(
            [g for g in inventory if g.pci_id in set(cluster.gpu_pci_ids) and g.vendor == "amd"],
            key=lambda g: g.rocm_index or 0,
        )
        return ",".join(str(i) for i in range(len(nvidia) + len(amd)))
    indices: list[int] = []
    for pci in cluster.gpu_pci_ids:
        gpu = inv_map.get(pci)
        if gpu is None:
            continue
        if cluster.backend in ("rocm", "rocmfp4"):
            idx = gpu.rocm_index
        elif cluster.backend == "cuda":
            idx = gpu.cuda_index
        else:  # vulkan / laguna
            idx = gpu.vulkan_index
        if idx is not None:
            indices.append(idx)
    return ",".join(str(i) for i in indices)


def tensor_split_for(n: int) -> str:
    """Equal tensor split across n GPUs: '1,1,...'"""
    return ",".join(["1"] * n)


def read_active(cluster_id: str) -> dict[str, Any] | None:
    path = active_dir() / f"{cluster_id}.json"
    if not path.exists() or path.is_symlink():
        return None
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def write_active(cluster_id: str, data: dict[str, Any]) -> None:
    path = active_dir() / f"{cluster_id}.json"
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def remove_active(cluster_id: str) -> None:
    path = active_dir() / f"{cluster_id}.json"
    if path.exists():
        path.unlink()


def read_desired(cluster_id: str) -> dict[str, Any] | None:
    path = desired_dir() / f"{cluster_id}.json"
    if not path.exists() or path.is_symlink():
        return None
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def write_desired(cluster_id: str, data: dict[str, Any]) -> None:
    path = desired_dir() / f"{cluster_id}.json"
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def remove_desired(cluster_id: str) -> None:
    path = desired_dir() / f"{cluster_id}.json"
    if path.exists():
        path.unlink()


def list_desired() -> list[dict[str, Any]]:
    result = []
    for f in sorted(desired_dir().glob("*.json")):
        try:
            data = json.loads(f.read_text())
            if isinstance(data, dict):
                result.append(data)
        except (OSError, json.JSONDecodeError):
            continue
    return result


def list_active() -> list[dict[str, Any]]:
    result = []
    for f in sorted(active_dir().glob("*.json")):
        try:
            data = json.loads(f.read_text())
            if isinstance(data, dict):
                result.append(data)
        except (OSError, json.JSONDecodeError):
            continue
    return result
