"""Host system metrics: CPU, memory, load, thermals.

Read straight from /proc and /sys, which are the host's inside the mgmt
container (host network/PID namespace, /sys bind-mounted by Docker).
Companion to gpu_status.py; same numbers lltop's System panel shows.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROC_STAT = Path("/proc/stat")
PROC_MEMINFO = Path("/proc/meminfo")
HWMON_ROOT = Path("/sys/class/hwmon")

_CPU_LINE = re.compile(r"cpu\d*$")


def parse_proc_stat(text: str) -> dict[str, list[int]]:
    """Parse cpu/cpuN jiffy counters out of /proc/stat."""
    samples: dict[str, list[int]] = {}
    for line in text.splitlines():
        parts = line.split()
        if not parts or not _CPU_LINE.fullmatch(parts[0]):
            continue
        try:
            samples[parts[0]] = [int(v) for v in parts[1:]]
        except ValueError:
            continue
    return samples


def cpu_percent(before: list[int], after: list[int]) -> float | None:
    """Busy% from two jiffy snapshots. idle = fields 3 (idle) + 4 (iowait)."""
    if len(before) < 5 or len(after) < 5:
        return None
    total_delta = sum(after) - sum(before)
    if total_delta <= 0:
        return None
    idle_delta = (after[3] + after[4]) - (before[3] + before[4])
    return max(0.0, min(100.0, (total_delta - idle_delta) / total_delta * 100.0))


def read_meminfo() -> dict[str, int]:
    """MemTotal/MemAvailable/Swap* in bytes."""
    wanted = {"MemTotal", "MemAvailable", "SwapTotal", "SwapFree"}
    result: dict[str, int] = {}
    try:
        for line in PROC_MEMINFO.read_text().splitlines():
            key, _, rest = line.partition(":")
            if key not in wanted:
                continue
            parts = rest.split()
            if parts and parts[0].isdigit():
                result[key] = int(parts[0]) * 1024
    except OSError:
        return {}
    return result


def _hwmon_int(path: Path) -> int | None:
    try:
        return int(path.read_text().strip(), 0)
    except (OSError, ValueError):
        return None


def collect_thermal() -> dict[str, Any]:
    """CPU package temp, chassis fan RPMs, PSU draw — whichever chips are present."""
    result: dict[str, Any] = {}
    if not HWMON_ROOT.exists():
        return result
    for hwmon in sorted(HWMON_ROOT.iterdir()):
        try:
            name = (hwmon / "name").read_text().strip()
        except OSError:
            continue
        if name == "coretemp":
            raw = _hwmon_int(hwmon / "temp1_input")
            if raw is not None:
                result["cpu_temp_c"] = raw / 1000.0
        elif name == "it8622":
            fans = [
                rpm
                for i in range(1, 6)
                if (rpm := _hwmon_int(hwmon / f"fan{i}_input")) is not None and rpm > 0
            ]
            if fans:
                result.setdefault("fan_rpms", []).extend(fans)
        elif name == "corsairpsu":
            watts = _hwmon_int(hwmon / "power1_input")
            if watts is not None:
                result["psu_power_w"] = watts / 1_000_000.0
    return result


@dataclass
class SystemStatusCollector:
    """Holds the previous /proc/stat snapshot so CPU% is a real interval delta."""

    previous: dict[str, list[int]] = field(default_factory=dict)

    def sample(self) -> dict[str, Any]:
        try:
            current = parse_proc_stat(PROC_STAT.read_text())
        except OSError:
            current = {}

        total = None
        cores: list[float] = []
        if self.previous and current:
            if "cpu" in current and "cpu" in self.previous:
                total = cpu_percent(self.previous["cpu"], current["cpu"])
            for name in sorted((n for n in current if n != "cpu"), key=lambda n: int(n[3:] or 0)):
                if name in self.previous:
                    pct = cpu_percent(self.previous[name], current[name])
                    if pct is not None:
                        cores.append(round(pct, 1))
        self.previous = current

        mem = read_meminfo()
        mem_total = mem.get("MemTotal")
        mem_avail = mem.get("MemAvailable")
        swap_total = mem.get("SwapTotal")
        swap_free = mem.get("SwapFree")

        try:
            load = list(os.getloadavg())
        except OSError:
            load = []

        return {
            "ts": time.time(),
            "cpu_percent": round(total, 1) if total is not None else None,
            "cpu_cores": cores,
            "cpu_count": len(current) - 1 if current else None,
            "load": [round(v, 2) for v in load],
            "mem_total": mem_total,
            "mem_used": (mem_total - mem_avail)
            if mem_total is not None and mem_avail is not None
            else None,
            "swap_total": swap_total,
            "swap_used": (swap_total - swap_free)
            if swap_total is not None and swap_free is not None
            else None,
            **collect_thermal(),
        }
