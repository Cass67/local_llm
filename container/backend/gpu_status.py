"""GPU status: DRM fdinfo-based per-runner engine occupancy.

Live attribution of GPU compute to each runner container using cumulative
per-client engine nanoseconds from /proc/1/fdinfo inside the container.
Deltas between samples give real per-GPU busy% plus aggregate GPU-equivalents
figure that distinguishes serialized layer-split from concurrent tensor-split.

Extracted from lltop/lltop; shared with mgmt API (/api/gpu-status).
"""

from __future__ import annotations

import json
import socket
import subprocess  # noqa: S404 # nosec B404
import time
from dataclasses import dataclass, field
from typing import Any

FDINFO_PROBE = r'tr "\0" " " < /proc/1/cmdline; echo; cat /proc/1/fdinfo/* 2>/dev/null'


def _docker_request(socket_path: str, method: str, path: str) -> bytes:
    """Make a raw HTTP/1.0 request to the Docker socket."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.settimeout(2.0)
        sock.connect(socket_path)
        request = f"{method} {path} HTTP/1.0\r\nHost: localhost\r\n\r\n"
        sock.sendall(request.encode())
        chunks: list[bytes] = []
        while True:
            try:
                chunk = sock.recv(65536)
            except OSError:
                break
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        sock.close()
    raw = b"".join(chunks)
    if b"\r\n\r\n" in raw:
        return raw.split(b"\r\n\r\n", 1)[1]
    return raw


def _run_cmd(args: list[str], timeout: float = 3.0) -> str:
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)  # noqa: S603 # nosec B603
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _kib_to_bytes(value: str | None) -> int:
    if not value:
        return 0
    parts = value.split()
    return int(parts[0]) * 1024 if parts and parts[0].isdigit() else 0


def parse_fdinfo(text: str) -> dict[str, dict[str, Any]]:
    """Aggregate DRM fdinfo records per PCI device, deduped by client id."""
    devices: dict[str, dict[str, Any]] = {}
    seen: set[tuple[str, str]] = set()

    def flush(record: dict[str, str]) -> None:
        pdev = record.get("drm-pdev")
        if not pdev:
            return
        key = (pdev, record.get("drm-client-id", ""))
        if key in seen:
            return
        seen.add(key)
        device = devices.setdefault(pdev, {"engines": {}, "vram": 0, "clients": 0})
        device["clients"] += 1
        device["vram"] += _kib_to_bytes(record.get("drm-memory-vram"))
        for name, value in record.items():
            if not name.startswith("drm-engine-"):
                continue
            parts = value.split()
            if not parts or not parts[0].isdigit():
                continue
            engine = name[len("drm-engine-") :]
            device["engines"][engine] = device["engines"].get(engine, 0) + int(parts[0])

    record: dict[str, str] = {}
    for line in text.splitlines():
        key, sep, value = line.partition(":")
        if not sep:
            continue
        key = key.strip()
        if key == "pos":
            flush(record)
            record = {}
        record[key] = value.strip()
    flush(record)
    return devices


def parse_split_config(cmdline: str) -> dict[str, str | None]:
    """Extract --split-mode / --tensor-split from llama-server cmdline."""
    args = cmdline.split()

    def flag(*names: str) -> str | None:
        for name in names:
            if name in args:
                idx = args.index(name)
                if idx + 1 < len(args):
                    return args[idx + 1]
        return None

    return {
        "split_mode": flag("--split-mode", "-sm") or "layer",
        "tensor_split": flag("--tensor-split", "-ts"),
        "ngl": flag("-ngl", "--n-gpu-layers", "--gpu-layers"),
        "parallel": flag("--parallel", "-np"),
    }


@dataclass
class EngineTracker:
    """Track per-GPU engine nanosecond deltas across samples."""

    previous: dict[str, tuple[dict[str, int], float]] = field(default_factory=dict)

    def update(
        self, devices: dict[str, dict[str, Any]], now: float | None = None
    ) -> dict[str, dict[str, Any]]:
        sample_time = time.monotonic() if now is None else now
        current: dict[str, tuple[dict[str, int], float]] = {}
        result: dict[str, dict[str, Any]] = {}

        for pdev, data in devices.items():
            engines: dict[str, int] = dict(data["engines"])
            current[pdev] = (engines, sample_time)
            entry: dict[str, Any] = {
                "vram": data["vram"],
                "clients": data["clients"],
                "busy": None,
                "engine_busy": {},
            }
            previous = self.previous.get(pdev)

            # No drm-engine-* counters at all means driver never exported engine time
            # (ROCm/HIP submits via KFD). That is unknown occupancy, not zero.
            if previous and engines:
                prev_engines, prev_time = previous
                elapsed = sample_time - prev_time
                if elapsed > 0:
                    per_engine: dict[str, float] = {}
                    for eng_name, ns in engines.items():
                        delta_ns = ns - prev_engines.get(eng_name, ns)
                        if delta_ns > 0:
                            pct = (delta_ns / (elapsed * 1e9)) * 100.0
                            per_engine[eng_name] = max(0.0, min(pct, 100.0))
                    entry["engine_busy"] = per_engine
                    total = sum(per_engine.values())
                    entry["busy"] = max(0.0, min(total, 100.0))

            result[pdev] = entry

        self.previous = current
        return result


def parallelism_verdict(busy_values: list[float], split_mode: str | None) -> str:
    """Classify multi-GPU behaviour from aggregate engine occupancy."""
    count = len(busy_values)
    aggregate = sum(busy_values) / 100.0
    if count < 2 or aggregate < 0.05:
        return ""
    if aggregate <= 1.15:
        mode_tag = f" ({split_mode})" if split_mode else ""
        return f"serialized: 1 GPU of work over {count}{mode_tag}"
    if aggregate >= count * 0.75:
        return "concurrent"
    return "partial overlap"


def collect_container_engines(
    container_name: str, docker_socket_path: str = "/var/run/docker.sock"
) -> dict[str, Any]:
    """Run FDINFO_PROBE inside a runner container and parse result."""
    output = _run_cmd(["docker", "exec", container_name, "sh", "-c", FDINFO_PROBE])
    if not output:
        return {}
    cmdline, _, fdinfo_text = output.partition("\n")
    devices = parse_fdinfo(fdinfo_text)
    if not devices:
        return {}
    return {"split": parse_split_config(cmdline), "devices": devices}


def docker_container_running(container_name: str, docker_socket_path: str) -> bool:
    """Check if a container is running via Docker socket."""
    raw = _docker_request(docker_socket_path, "GET", f"/containers/{container_name}/json")
    if not raw:
        return False
    try:
        data = json.loads(raw)
        state = data.get("State") if isinstance(data, dict) else None
        return bool(isinstance(state, dict) and state.get("Running"))
    except (json.JSONDecodeError, AttributeError):
        return False


def format_bytes(value: int | float | None) -> str:
    """Format bytes into human-readable string."""
    if value is None or value == 0:
        return "0 B"
    size = float(abs(value))
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    unit = units[0]
    for u in units:
        if abs(size) < 1024.0 or u == units[-1]:
            break
        size /= 1024.0
        unit = u
    return f"{size:.1f} {unit}"


@dataclass
class GpuStatusCollector:
    """Per-container engine trackers, reused across samples."""

    docker_socket_path: str
    trackers: dict[str, EngineTracker] = field(default_factory=dict)

    def sample_runner(
        self, container_name: str, gpu_pci_ids: list[str], initial_warmup: bool = True
    ) -> dict[str, Any]:
        """Sample one runner's engine metrics. Returns {} if not running or no fdinfo."""
        if not docker_container_running(container_name, self.docker_socket_path):
            return {}

        engines = collect_container_engines(container_name, self.docker_socket_path)
        if not engines:
            return {}

        tracker = self.trackers.setdefault(container_name, EngineTracker())
        measured = tracker.update(engines["devices"])

        # First frame has no baseline — take a short second sample for initial data.
        if all(entry.get("busy") is None for entry in measured.values()):
            if initial_warmup:
                time.sleep(0.25)
                second = collect_container_engines(container_name, self.docker_socket_path)
                if second:
                    measured = tracker.update(second["devices"])

        # Aggregate across GPUs this runner uses
        busy_values: list[float] = []
        gpu_details: dict[str, dict[str, Any]] = {}
        for pdev in sorted(measured):
            entry = measured[pdev]
            if entry.get("busy") is not None:
                busy_values.append(float(entry["busy"]))
            gpu_details[pdev] = {
                "engine_busy": round(entry.get("busy") or 0, 1),
                "per_engine": {k: round(v, 1) for k, v in entry.get("engine_busy", {}).items()},
                "vram_bytes": entry.get("vram", 0),
                "vram_human": format_bytes(entry.get("vram")),
                "clients": entry.get("clients", 0),
            }

        split = engines["split"]
        verdict = parallelism_verdict(busy_values, split.get("split_mode")) if busy_values else ""
        aggregate = sum(busy_values) / 100.0 if busy_values else None

        return {
            "container": container_name,
            "split_config": {k: v for k, v in split.items() if v is not None},
            "gpus": gpu_details,
            "aggregate_gpu_equiv": round(aggregate, 2) if aggregate is not None else None,
            "gpu_count": len(gpu_pci_ids),
            "verdict": verdict,
        }

    def sample_all(
        self, runners: list[dict[str, Any]], initial_warmup: bool = False
    ) -> list[dict[str, Any]]:
        """Sample all running runners. Each runner dict must have 'container' and 'gpu_pci_ids'."""
        results = []
        for runner in runners:
            container = runner.get("container")
            pci_ids = runner.get("gpu_pci_ids", [])
            if not container:
                continue
            sample = self.sample_runner(container, pci_ids, initial_warmup=initial_warmup)
            if sample:
                cluster_name = runner.get("cluster_name") or runner.get("cluster_id", "")
                results.append(
                    {
                        "cluster_id": runner.get("cluster_id"),
                        "cluster_name": cluster_name,
                        **sample,
                    }
                )
        return results
