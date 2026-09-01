"""Helpers for ROCm/Vulkan/CUDA accepted-model variants."""

from copy import deepcopy
from typing import Any, Literal

Backend = Literal[
    "rocm",
    "rocmfp4",
    "rocmqwen4exp",
    "rocmqwen4exp2",
    "rocmmain",
    "rocmmainmtp",
    "rocmfork",
    "rocmdflash2",
    "vulkan",
    "cuda",
]
_BACKEND_SUFFIXES = ("-rocmfp4", "-rocm", "-vulkan", "-cuda")
_BACKEND_LABELS = {
    "rocm": "ROCm",
    "rocmfp4": "ROCmFP4",
    "rocmqwen4exp": "ROCmQwen4Exp",
    "rocmqwen4exp2": "ROCmQwen4Exp2",
    "rocmmain": "ROCmMain",
    "rocmmainmtp": "ROCmMainMTP",
    "rocmfork": "ROCmFork",
    "rocmdflash2": "ROCmDFlash2",
    "vulkan": "Vulkan",
    "cuda": "CUDA",
}


def base_variant_id(model_id: str) -> str:
    for suffix in _BACKEND_SUFFIXES:
        if model_id.endswith(suffix):
            return model_id[: -len(suffix)]
    return model_id


def backend_variant_id(model_id: str, backend: Backend) -> str:
    return f"{base_variant_id(model_id)}-{backend}"


def _backend_label(backend: Backend) -> str:
    return _BACKEND_LABELS.get(backend, "ROCm")


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
    for suffix in (" (ROCm)", " (ROCmFP4)", " (Vulkan)", " (CUDA)"):
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
    if backend not in (
        "rocm",
        "rocmfp4",
        "rocmqwen4exp",
        "rocmqwen4exp2",
        "rocmmain",
        "rocmmainmtp",
        "rocmfork",
        "rocmdflash2",
        "vulkan",
        "cuda",
    ):
        backend = "rocm"
    return copy_backend_variant(metadata, backend)  # type: ignore[arg-type]
