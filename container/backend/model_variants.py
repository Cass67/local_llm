"""Helpers for ROCm/Vulkan accepted-model variants."""

from copy import deepcopy
from typing import Any, Literal

Backend = Literal["rocm", "vulkan"]
_BACKEND_SUFFIXES = ("-rocm", "-vulkan")


def base_variant_id(model_id: str) -> str:
    for suffix in _BACKEND_SUFFIXES:
        if model_id.endswith(suffix):
            return model_id[: -len(suffix)]
    return model_id


def backend_variant_id(model_id: str, backend: Backend) -> str:
    return f"{base_variant_id(model_id)}-{backend}"


def _backend_label(backend: Backend) -> str:
    return "ROCm" if backend == "rocm" else "Vulkan"


def _source_id(metadata: dict[str, Any]) -> str:
    return str(
        metadata.get("family") or metadata.get("alias") or metadata.get("model_name") or "model"
    )


def copy_backend_variant(metadata: dict[str, Any], backend: Backend) -> dict[str, Any]:
    copied = deepcopy(metadata)
    variant_id = backend_variant_id(_source_id(metadata), backend)
    copied["family"] = variant_id
    copied["alias"] = variant_id
    copied["backend"] = backend
    name = str(metadata.get("model_name") or base_variant_id(_source_id(metadata)))
    for suffix in (" (ROCm)", " (Vulkan)"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    copied["model_name"] = f"{name} ({_backend_label(backend)})"
    cfg = copied.setdefault("config", {})
    if not isinstance(cfg, dict):
        cfg = {}
        copied["config"] = cfg
    cfg["backend"] = backend
    return copied


def migrate_backend_variant(metadata: dict[str, Any]) -> dict[str, Any]:
    config_value = metadata.get("config")
    cfg: dict[str, Any] = config_value if isinstance(config_value, dict) else {}
    backend = str(metadata.get("backend") or cfg.get("backend") or "rocm")
    if backend not in ("rocm", "vulkan"):
        backend = "rocm"
    return copy_backend_variant(metadata, backend)  # type: ignore[arg-type]
