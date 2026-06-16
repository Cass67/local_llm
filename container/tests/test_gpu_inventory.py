"""Tests for GPU inventory detection."""

from unittest.mock import patch
from pathlib import Path

from backend.gpu_inventory import (
    GpuInfo,
    _rocminfo_indices,
    _nvidia_smi_indices,
    _vulkaninfo_devices,
    _match_vulkan,
    detect_gpus,
)


def _make_pci_dev(
    root: Path,
    pci_id: str,
    vendor_id: str,
    device_id: str,
    pci_class: str = "0x030000",
    vram_bytes: int | None = None,
) -> None:
    dev = root / pci_id
    dev.mkdir(parents=True)
    (dev / "class").write_text(pci_class)
    (dev / "vendor").write_text(f"0x{vendor_id}")
    (dev / "device").write_text(f"0x{device_id}")
    if vram_bytes is not None:
        (dev / "mem_info_vram_total").write_text(str(vram_bytes))


def test_sysfs_gpus_finds_amd_and_nvidia(tmp_path):
    pci_root = tmp_path / "pci"
    pci_root.mkdir()
    _make_pci_dev(pci_root, "0000:03:00.0", "1002", "744c", vram_bytes=20 * 1024**3)
    _make_pci_dev(pci_root, "0000:04:00.0", "1002", "744c", vram_bytes=20 * 1024**3)
    _make_pci_dev(pci_root, "0000:05:00.0", "10de", "1b38")
    _make_pci_dev(pci_root, "0000:00:1f.0", "8086", "a3a3", pci_class="0x060100")  # non-display

    with patch(
        "backend.gpu_inventory.Path",
        side_effect=lambda p: tmp_path / "pci" if p == "/sys/bus/pci/devices" else Path(p),
    ):
        with patch("backend.gpu_inventory._sysfs_gpus") as mock_sysfs:
            mock_sysfs.return_value = [
                {
                    "pci_id": "0000:03:00.0",
                    "vendor_id": "1002",
                    "device_id": "744c",
                    "vendor": "amd",
                    "vram_mb": 20 * 1024,
                },
                {
                    "pci_id": "0000:04:00.0",
                    "vendor_id": "1002",
                    "device_id": "744c",
                    "vendor": "amd",
                    "vram_mb": 20 * 1024,
                },
                {
                    "pci_id": "0000:05:00.0",
                    "vendor_id": "10de",
                    "device_id": "1b38",
                    "vendor": "nvidia",
                    "vram_mb": None,
                },
            ]
            devs = mock_sysfs()
    assert len(devs) == 3
    assert devs[0]["vendor"] == "amd"
    assert devs[2]["vendor"] == "nvidia"


def test_rocminfo_indices_parses_pci_bus():
    rocminfo_output = """\
*******
Agent 1
*******
  Name:                    gfx1100
  Marketing Name:          AMD Radeon RX 7900 XT
  PCI Bus:                 0000:03:00.0

*******
Agent 2
*******
  Name:                    gfx1100
  Marketing Name:          AMD Radeon RX 7900 XT
  PCI Bus:                 0000:04:00.0
"""
    with patch("backend.gpu_inventory._run", return_value=rocminfo_output):
        result = _rocminfo_indices()
    assert result == {"0000:03:00.0": 0, "0000:04:00.0": 1}


def test_nvidia_smi_indices_parses_csv():
    smi_output = "0, 00000000:05:00.0, Tesla P40, 24576\n"
    with patch("backend.gpu_inventory._run", return_value=smi_output):
        result = _nvidia_smi_indices()
    assert "05:00.0" in result
    idx, name, vram = result["05:00.0"]
    assert idx == 0
    assert "P40" in name
    assert vram == 24576


def test_vulkaninfo_devices_parses_summary():
    summary = """\
GPU0:
  apiVersion         = 1.3.0
  driverVersion      = 2.0.300.0
  vendorID           = 0x1002
  deviceID           = 0x744c
  deviceType         = PHYSICAL_DEVICE_TYPE_DISCRETE_GPU
  deviceName         = AMD Radeon RX 7900 XT
GPU1:
  vendorID           = 0x10de
  deviceID           = 0x1b38
  deviceName         = Tesla P40
"""
    with patch("backend.gpu_inventory._run", return_value=summary):
        devs = _vulkaninfo_devices()
    assert len(devs) == 2
    assert devs[0]["name"] == "AMD Radeon RX 7900 XT"
    assert devs[1]["name"] == "Tesla P40"


def test_match_vulkan_maps_by_vendor_device_id():
    sysfs = [
        {"pci_id": "0000:03:00.0", "vendor_id": "1002", "device_id": "744c"},
        {"pci_id": "0000:04:00.0", "vendor_id": "1002", "device_id": "744c"},
        {"pci_id": "0000:05:00.0", "vendor_id": "10de", "device_id": "1b38"},
    ]
    vulkan = [
        {"vendor_id": "0x1002", "device_id": "0x744c", "name": "RX 7900 XT"},
        {"vendor_id": "0x1002", "device_id": "0x744c", "name": "RX 7900 XT"},
        {"vendor_id": "0x10de", "device_id": "0x1b38", "name": "Tesla P40"},
    ]
    result = _match_vulkan(sysfs, vulkan)
    assert result["0000:03:00.0"] == 0
    assert result["0000:04:00.0"] == 1
    assert result["0000:05:00.0"] == 2


def test_detect_gpus_combines_sources():
    sysfs_devs = [
        {
            "pci_id": "0000:03:00.0",
            "vendor_id": "1002",
            "device_id": "744c",
            "vendor": "amd",
            "vram_mb": 20480,
        },
        {
            "pci_id": "0000:04:00.0",
            "vendor_id": "1002",
            "device_id": "744c",
            "vendor": "amd",
            "vram_mb": 20480,
        },
    ]
    with (
        patch("backend.gpu_inventory._sysfs_gpus", return_value=sysfs_devs),
        patch("backend.gpu_inventory._sysfs_amd_vram", return_value={}),
        patch(
            "backend.gpu_inventory._rocminfo_indices",
            return_value={"0000:03:00.0": 0, "0000:04:00.0": 1},
        ),
        patch("backend.gpu_inventory._nvidia_smi_indices", return_value={}),
        patch(
            "backend.gpu_inventory._vulkaninfo_devices",
            return_value=[
                {"vendor_id": "0x1002", "device_id": "0x744c", "name": "RX 7900 XT"},
                {"vendor_id": "0x1002", "device_id": "0x744c", "name": "RX 7900 XT"},
            ],
        ),
    ):
        gpus = detect_gpus()

    assert len(gpus) == 2
    assert all(isinstance(g, GpuInfo) for g in gpus)
    assert gpus[0].rocm_index == 0
    assert gpus[1].rocm_index == 1
    assert gpus[0].vulkan_index == 0
    assert gpus[1].vulkan_index == 1
    assert gpus[0].cuda_index is None
    assert gpus[0].vram_mb == 20480
