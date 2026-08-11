"""Wall-power sampling for a measurement window.

Two sources, both already exposed on this host: total draw from the PSU's hwmon
chip (corsairpsu) and per-GPU draw from the amdgpu hwmon. The PSU figure is the
honest one for perf-per-watt — it includes the CPU, fans, and conversion losses
the GPU sensors do not see.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from .gpu_status import collect_amd_gpu_metrics
from .system_status import collect_thermal


def read_psu_watts() -> float | None:
    value = collect_thermal().get("psu_power_w")
    return float(value) if isinstance(value, (int, float)) else None


def read_gpu_watts() -> float | None:
    """Summed draw of every AMD GPU on the host, or None if unreadable."""
    try:
        metrics = collect_amd_gpu_metrics()
    except Exception:  # noqa: BLE001
        return None
    total = 0.0
    seen = False
    for entry in metrics.values():
        watts = entry.get("power_w")
        if isinstance(watts, (int, float)):
            total += float(watts)
            seen = True
    return total if seen else None


@dataclass
class PowerSampler:
    """Background sampler over a measurement window. No-op when no sensors exist."""

    interval_s: float = 1.0
    psu_samples: list[float] = field(default_factory=list)
    gpu_samples: list[float] = field(default_factory=list)
    _stop: threading.Event = field(default_factory=threading.Event)
    _thread: threading.Thread | None = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            psu = read_psu_watts()
            if psu is not None:
                self.psu_samples.append(psu)
            gpu = read_gpu_watts()
            if gpu is not None:
                self.gpu_samples.append(gpu)
            self._stop.wait(self.interval_s)

    def __enter__(self) -> PowerSampler:
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.interval_s * 2)

    def result(self) -> dict[str, Any]:
        def stats(samples: list[float], prefix: str) -> dict[str, Any]:
            if not samples:
                return {f"{prefix}_avg_w": None, f"{prefix}_peak_w": None}
            return {
                f"{prefix}_avg_w": round(sum(samples) / len(samples), 1),
                f"{prefix}_peak_w": round(max(samples), 1),
            }

        return {
            **stats(self.psu_samples, "psu"),
            **stats(self.gpu_samples, "gpu"),
            "samples": len(self.psu_samples) or len(self.gpu_samples),
        }


def tokens_per_watt(tps: float | None, watts: float | None) -> float | None:
    """Decode tok/s per watt of wall draw — the number that ranks configs by efficiency."""
    if not tps or not watts or watts <= 0:
        return None
    return round(tps / watts, 4)


def measure_idle_watts(settle_s: float = 3.0, samples: int = 3) -> dict[str, Any]:
    """Baseline draw, so a sweep can report marginal watts rather than whole-host draw."""
    time.sleep(settle_s)
    sampler = PowerSampler(interval_s=0.5)
    with sampler:
        time.sleep(max(samples * 0.5, 0.5))
    return sampler.result()
