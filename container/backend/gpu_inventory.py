"""GPU inventory detection: enumerate physical GPUs with per-backend device indices."""

from __future__ import annotations

import re
import subprocess  # noqa: S404 # nosec B404
from dataclasses import dataclass
from pathlib import Path


@dataclass
class GpuInfo:
    pci_id: str
    vendor: str  # "amd" | "nvidia" | "intel" | "unknown"
    model_name: str
    vram_mb: int | None
    rocm_index: int | None = None
    cuda_index: int | None = None
    vulkan_index: int | None = None


_VENDOR_IDS = {
    "1002": "amd",
    "10de": "nvidia",
    "8086": "intel",
}

_PCI_CLASS_DISPLAY = {"0300", "0302"}
_NVIDIA_VRAM_FALLBACK_MB = {
    "1b38": 24576,  # Tesla P40, 24 GB (ECC off) as reported by nvidia-smi
}


def _sysfs_gpus() -> list[dict]:
    """Return physical display-class PCI devices from /sys/bus/pci/devices."""
    devices = []
    pci_root = Path("/sys/bus/pci/devices")
    if not pci_root.exists():
        return devices
    for dev in sorted(pci_root.iterdir()):
        class_file = dev / "class"
        vendor_file = dev / "vendor"
        device_id_file = dev / "device"
        if not (class_file.exists() and vendor_file.exists()):
            continue
        try:
            pci_class = class_file.read_text().strip().lower()
        except OSError:
            continue
        if not any(pci_class.startswith(f"0x{c}") for c in _PCI_CLASS_DISPLAY):
            continue
        try:
            raw_vendor = vendor_file.read_text().strip().lower().lstrip("0x")
            raw_device = (
                device_id_file.read_text().strip().lower().lstrip("0x")
                if device_id_file.exists()
                else ""
            )
        except OSError:
            continue
        vram_mb = _sysfs_vram(dev)
        devices.append(
            {
                "pci_id": dev.name,
                "vendor_id": raw_vendor,
                "device_id": raw_device,
                "vendor": _VENDOR_IDS.get(raw_vendor, "unknown"),
                "vram_mb": vram_mb,
            }
        )
    return devices


def _sysfs_vram(dev_path: Path) -> int | None:
    vram_file = dev_path / "mem_info_vram_total"
    if not vram_file.exists():
        # also try via drm symlink
        for drm in (dev_path / "drm").iterdir() if (dev_path / "drm").exists() else []:
            f = drm / "device" / "mem_info_vram_total"
            if f.exists():
                vram_file = f
                break
    if not vram_file.exists():
        # try /sys/class/drm/cardN/device/mem_info_vram_total by PCI bus match
        return None
    try:
        return int(vram_file.read_text().strip()) // (1024 * 1024)
    except (OSError, ValueError):
        return None


def _run(cmd: list[str], timeout: int = 5) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)  # noqa: S603 # nosec B603
        return r.stdout if r.returncode == 0 else ""
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return ""


def _rocminfo_indices() -> dict[str, int]:
    """Map PCI bus id → ROCm agent index. Requires rocminfo to be installed."""
    out = _run(["rocminfo"])
    indices: dict[str, int] = {}
    current_idx: int | None = None
    current_pci: str | None = None
    for line in out.splitlines():
        m = re.match(r"\s*Agent\s+(\d+)", line)
        if m:
            current_idx = int(m.group(1)) - 1  # 0-based
            current_pci = None
            continue
        m = re.search(
            r"PCI Bus:\s*([0-9A-Fa-f]{4}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}\.[0-9A-Fa-f])",
            line,
            re.IGNORECASE,
        )
        if m and current_idx is not None:
            current_pci = m.group(1).lower()
            indices[current_pci] = current_idx  # pyright: ignore[reportArgumentType]
    return indices


def _lspci_name(pci_id: str) -> str | None:
    out = _run(["lspci", "-s", pci_id])
    match = re.search(
        r"(?:\]|controller):\s*(.+?)(?:\s*\[[0-9a-fA-F]{4}:[0-9a-fA-F]{4}\])?(?:\s*\(rev|$)", out
    )
    return match.group(1).strip() if match else None


def _nvidia_smi_indices() -> dict[str, tuple[int, str, int | None]]:
    """Map PCI bus id → (CUDA index, name, vram_mb) via nvidia-smi."""
    out = _run(
        [
            "nvidia-smi",
            "--query-gpu=index,pci.bus_id,name,memory.total",
            "--format=csv,noheader,nounits",
        ]
    )
    result: dict[str, tuple[int, str, int | None]] = {}
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4:
            continue
        try:
            idx = int(parts[0])
        except ValueError:
            continue
        # nvidia pci.bus_id format: 00000000:03:00.0 — strip the domain prefix
        pci_raw = parts[1].strip().lower()
        # normalise to domain:bus:slot.func
        pci_short = re.sub(r"^[0-9a-f]{8}:", "", pci_raw)  # drop leading domain
        name = parts[2].strip()
        try:
            vram_mb = int(parts[3].strip())
        except ValueError:
            vram_mb = None
        result[pci_short] = (idx, name, vram_mb)
    return result


def _vulkaninfo_devices() -> list[dict]:
    """Return list of {vendor_id, device_id, name} in Vulkan enumeration order."""
    out = _run(["vulkaninfo", "--summary"], timeout=10)
    devices = []
    cur: dict | None = None
    for line in out.splitlines():
        if re.match(r"\s*GPU\d+:", line):
            if cur:
                devices.append(cur)
            cur = {}
            continue
        if cur is None:
            continue
        for key, pat in (
            ("name", r"deviceName\s*=\s*(.+)"),
            ("vendor_id", r"vendorID\s*=\s*(0x[0-9a-fA-F]+)"),
            ("device_id", r"deviceID\s*=\s*(0x[0-9a-fA-F]+)"),
        ):
            m = re.search(pat, line)
            if m:
                cur[key] = m.group(1).strip()
    if cur:
        devices.append(cur)
    return devices


def _match_vulkan(
    sysfs_devs: list[dict], vulkan_devs: list[dict]
) -> tuple[dict[str, int], dict[str, str]]:
    """Map PCI id → (Vulkan device index, device name), matched by vendor:device id pair."""
    vk_index: dict[str, int] = {}
    vk_names: dict[str, str] = {}
    vk_pairs: list[tuple[str, str]] = []
    for v in vulkan_devs:
        vid = v.get("vendor_id", "").lower().lstrip("0x").zfill(4)
        did = v.get("device_id", "").lower().lstrip("0x").zfill(4)
        vk_pairs.append((vid, did))

    # Track how many times each pair has been used (for duplicate cards)
    used: dict[tuple[str, str], int] = {}
    for sysfs in sysfs_devs:
        pair = (sysfs["vendor_id"].zfill(4), sysfs["device_id"].zfill(4))
        use_count = used.get(pair, 0)
        found = 0
        for vk_idx, vk_pair in enumerate(vk_pairs):
            if vk_pair == pair:
                if found == use_count:
                    vk_index[sysfs["pci_id"]] = vk_idx
                    vk_names[sysfs["pci_id"]] = vulkan_devs[vk_idx].get("name", "")
                    break
                found += 1
        used[pair] = use_count + 1
    return vk_index, vk_names


def _sysfs_amd_vram() -> dict[str, int]:
    """Read VRAM from /sys/class/drm/cardN directly, keyed by PCI symlink target."""
    result: dict[str, int] = {}
    drm_root = Path("/sys/class/drm")
    if not drm_root.exists():
        return result
    for entry in sorted(drm_root.iterdir()):
        if not re.match(r"^card\d+$", entry.name):
            continue
        vram_file = entry / "device" / "mem_info_vram_total"
        if not vram_file.exists():
            continue
        try:
            pci_link = (entry / "device").resolve()
            vram_bytes = int(vram_file.read_text().strip())
            result[pci_link.name] = vram_bytes // (1024 * 1024)
        except (OSError, ValueError):
            continue
    return result


def detect_gpus() -> list[GpuInfo]:  # noqa: C901
    """Enumerate physical GPUs with per-backend device indices."""
    sysfs = _sysfs_gpus()
    # Fill in VRAM from /sys/class/drm symlinks where sysfs_gpus didn't find it
    drm_vram = _sysfs_amd_vram()
    for dev in sysfs:
        if dev["vram_mb"] is None and dev["pci_id"] in drm_vram:
            dev["vram_mb"] = drm_vram[dev["pci_id"]]

    rocm_map = _rocminfo_indices()
    nvidia_map = _nvidia_smi_indices()
    vulkan_devs = _vulkaninfo_devices()
    vk_map, vk_names = _match_vulkan(sysfs, vulkan_devs)

    # Track per-vendor enumeration index for ROCm fallback (when rocminfo absent)
    amd_count = 0
    nvidia_count = 0

    gpus: list[GpuInfo] = []
    for dev in sysfs:
        pci = dev["pci_id"]
        vendor = dev["vendor"]
        vram_mb = dev["vram_mb"]
        name = "Unknown GPU"
        rocm_idx: int | None = None
        cuda_idx: int | None = None

        if vendor == "amd":
            rocm_idx = rocm_map.get(pci, amd_count)
            amd_count += 1
        elif vendor == "nvidia":
            nvidia_entry = None
            # Match by the short PCI bus part (drop domain prefix from pci_id)
            pci_short = re.sub(r"^[0-9a-f]{4}:", "", pci)
            for raw_pci, entry in nvidia_map.items():
                if raw_pci.endswith(pci_short) or pci_short.endswith(raw_pci):
                    nvidia_entry = entry
                    break
            if nvidia_entry:
                cuda_idx, name, nvram = nvidia_entry
                if vram_mb is None and nvram is not None:
                    vram_mb = nvram
            else:
                cuda_idx = nvidia_count
                name = _lspci_name(pci) or name
                if vram_mb is None:
                    vram_mb = _NVIDIA_VRAM_FALLBACK_MB.get(dev["device_id"])
            nvidia_count += 1

        vk_idx = vk_map.get(pci)
        # Use vulkaninfo name when available (works even without rocminfo)
        vk_name = vk_names.get(pci, "")
        if vk_name:
            name = vk_name
        elif vendor == "amd" and name == "Unknown GPU":
            name = f"AMD GPU (PCI {pci})"
        elif vendor == "nvidia" and name == "Unknown GPU":
            name = f"NVIDIA GPU (PCI {pci})"

        gpus.append(
            GpuInfo(
                pci_id=pci,
                vendor=vendor,
                model_name=name,
                vram_mb=vram_mb,
                rocm_index=rocm_idx,
                cuda_index=cuda_idx,
                vulkan_index=vk_idx,
            )
        )

    return gpus
