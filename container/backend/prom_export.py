"""Prometheus exposition for the GPU/system sample mgmt already collects.

llama-server's own /metrics covers inference (tok/s, KV cache, queues) but knows
nothing about the cards underneath it. Grafana needs both on one time axis to
answer the only question that matters when a run is slow: was the GPU busy?

Reads the sample the 2s gpu-status loop leaves in memory — no extra polling.
"""

from __future__ import annotations

import re
from typing import Any

_CLOCK = re.compile(r"([\d.]+)\s*mhz", re.IGNORECASE)


def _clock_mhz(value: Any) -> float | None:
    if not isinstance(value, str):
        return None
    m = _CLOCK.search(value)
    return float(m.group(1)) if m else None


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _line(name: str, labels: dict[str, str], value: float | None) -> str | None:
    if value is None:
        return None
    if labels:
        rendered = ",".join(f'{k}="{_escape(str(v))}"' for k, v in labels.items() if v)
        return f"{name}{{{rendered}}} {value}"
    return f"{name} {value}"


# (metric suffix, sample key, help text, type)
_DEVICE_METRICS = (
    ("busy_percent", "gpu_busy_percent", "GPU busy percentage", "gauge"),
    ("mem_busy_percent", "mem_busy_percent", "Memory controller busy percentage", "gauge"),
    ("vram_used_bytes", "vram_used", "VRAM in use", "gauge"),
    ("vram_total_bytes", "vram_total", "VRAM total", "gauge"),
    ("temp_celsius", "temp_c", "Edge temperature", "gauge"),
    ("junction_temp_celsius", "junction_temp_c", "Junction (hotspot) temperature", "gauge"),
    ("power_watts", "power_w", "Board power draw", "gauge"),
    ("power_cap_watts", "power_cap_w", "Board power cap", "gauge"),
    ("fan_rpm", "fan_rpm", "Fan speed", "gauge"),
    ("fan_percent", "fan_pct", "Fan duty cycle", "gauge"),
)

_SYSTEM_METRICS = (
    ("cpu_percent", "cpu_percent", "Host CPU utilisation"),
    ("mem_used_bytes", "mem_used", "Host memory in use"),
    ("mem_total_bytes", "mem_total", "Host memory total"),
    ("swap_used_bytes", "swap_used", "Host swap in use"),
    ("swap_total_bytes", "swap_total", "Host swap total"),
    ("cpu_temp_celsius", "cpu_temp_c", "Host CPU package temperature"),
)


def render(sample: dict[str, Any] | None) -> str:
    """Render the latest gpu-status sample as Prometheus text exposition."""
    if not sample:
        return "# no sample yet\n"

    lines: list[str] = []

    def emit(name: str, help_text: str, kind: str, rows: list[str | None]) -> None:
        present = [row for row in rows if row]
        if not present:
            return
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} {kind}")
        lines.extend(present)

    devices = sample.get("devices") or []
    for suffix, key, help_text, kind in _DEVICE_METRICS:
        name = f"llm_gpu_{suffix}"
        emit(
            name,
            help_text,
            kind,
            [
                _line(
                    name,
                    {
                        "pci": dev.get("pci_id", ""),
                        "vendor": dev.get("vendor", ""),
                        "board": dev.get("board", ""),
                    },
                    dev.get(key),
                )
                for dev in devices
            ],
        )

    for suffix, key, help_text in (
        ("sclk_mhz", "sclk", "Core clock"),
        ("mclk_mhz", "mclk", "Memory clock"),
    ):
        name = f"llm_gpu_{suffix}"
        emit(
            name,
            help_text,
            "gauge",
            [
                _line(name, {"pci": dev.get("pci_id", "")}, _clock_mhz(dev.get(key)))
                for dev in devices
            ],
        )

    runners = sample.get("runners") or []
    emit(
        "llm_runner_gpu_equiv",
        "Concurrent GPU-equivalents of work (1.0 on N cards means serialized)",
        "gauge",
        [
            _line(
                "llm_runner_gpu_equiv",
                {
                    "cluster": r.get("cluster_name", ""),
                    "split_mode": r.get("split_config", {}).get("split_mode", ""),
                },
                r.get("aggregate_gpu_equiv"),
            )
            for r in runners
        ],
    )
    emit(
        "llm_runner_engine_busy_percent",
        "Per-GPU engine occupancy attributed to this runner via DRM fdinfo",
        "gauge",
        [
            _line(
                "llm_runner_engine_busy_percent",
                {"cluster": r.get("cluster_name", ""), "pci": pci},
                gpu.get("engine_busy"),
            )
            for r in runners
            for pci, gpu in (r.get("gpus") or {}).items()
        ],
    )
    emit(
        "llm_runner_vram_bytes",
        "VRAM attributed to this runner's DRM clients",
        "gauge",
        [
            _line(
                "llm_runner_vram_bytes",
                {"cluster": r.get("cluster_name", ""), "pci": pci},
                gpu.get("vram_bytes"),
            )
            for r in runners
            for pci, gpu in (r.get("gpus") or {}).items()
        ],
    )

    system = sample.get("system") or {}
    for suffix, key, help_text in _SYSTEM_METRICS:
        name = f"llm_system_{suffix}"
        emit(name, help_text, "gauge", [_line(name, {}, system.get(key))])

    cores = system.get("cpu_cores") or []
    emit(
        "llm_system_cpu_core_percent",
        "Per-core CPU utilisation",
        "gauge",
        [_line("llm_system_cpu_core_percent", {"core": str(i)}, v) for i, v in enumerate(cores)],
    )
    fans = system.get("fan_rpms") or []
    emit(
        "llm_system_fan_rpm",
        "Chassis fan speeds",
        "gauge",
        [_line("llm_system_fan_rpm", {"fan": str(i)}, v) for i, v in enumerate(fans)],
    )

    return "\n".join(lines) + "\n"
