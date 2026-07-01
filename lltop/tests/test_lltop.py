import importlib.util
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "lltop"


def load_lltop():
    if not SCRIPT.exists():
        raise AssertionError(f"missing executable script: {SCRIPT}")
    loader = SourceFileLoader("lltop_script", str(SCRIPT))
    spec = importlib.util.spec_from_loader("lltop_script", loader)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LltopTests(unittest.TestCase):
    def sample_snapshot(self):
        return {
            "hostname": "ubt26",
            "time": "12:34:56",
            "state_dir": "/home/cass/.local/share/local_llm",
            "gpu": {
                "gpus": [
                    {
                        "vendor": "AMD",
                        "name": "Radeon RX 7900 XT",
                        "path": "/sys/class/drm/card2/device",
                        "pci_id": "0000:03:00.0",
                        "gpu_busy_percent": 37,
                        "mem_busy_percent": 12,
                        "vram_used": 10729029632,
                        "vram_total": 21458059264,
                        "temp_c": 46.0,
                        "junction_temp_c": 52.0,
                        "power_w": 10.0,
                        "fan_pct": 30,
                        "fan_rpm": 900,
                        "sclk": "S: 2475Mhz *",
                        "mclk": "1: 1249Mhz *",
                    }
                ],
            },
            "runners": [
                {
                    "cluster_id": "abc123",
                    "cluster_name": "amd-dual",
                    "model": "Qwen3-30B-A3B-Q4",
                    "family": "qwen3-30b",
                    "label": None,
                    "backend": "rocm",
                    "port": 8080,
                    "container": "local-llm-runner-cluster-amd-dual-abc123",
                    "gpu_pci_ids": ["0000:03:00.0", "0000:04:00.0"],
                    "running": True,
                    "api": {
                        "health": "ok",
                        "models": "Qwen3-30B-A3B-Q4",
                        "tps": {"live_tps": 45.2, "active_slots": 1, "total_slots": 1},
                    },
                }
            ],
            "system": {"load": "1.00 0.75 0.50", "mem": "Mem: 1 2 3"},
            "logs": ["[amd-dual]", "main: server is listening", "slot 0 idle"],
        }

    def test_format_bytes_uses_binary_units(self):
        lltop = load_lltop()

        self.assertEqual(lltop.format_bytes(0), "0.0 B")
        self.assertEqual(lltop.format_bytes(1024), "1.0 KiB")
        self.assertEqual(lltop.format_bytes(21458059264), "20.0 GiB")

    def test_bar_clamps_percent_and_fills_width(self):
        lltop = load_lltop()

        self.assertEqual(lltop.bar(-10, 10), "[----------]")
        self.assertEqual(lltop.bar(50, 10), "[#####-----]")
        self.assertEqual(lltop.bar(150, 10), "[##########]")

    def test_meter_style_thresholds(self):
        lltop = load_lltop()

        self.assertEqual(lltop.meter_style(10), "good")
        self.assertEqual(lltop.meter_style(74), "good")
        self.assertEqual(lltop.meter_style(75), "warn")
        self.assertEqual(lltop.meter_style(89), "warn")
        self.assertEqual(lltop.meter_style(90), "bad")
        self.assertEqual(lltop.meter_style(None), "muted")

    def test_muted_palette_uses_readable_color(self):
        lltop = load_lltop()

        muted = lltop.style_palette()["muted"]

        self.assertEqual(muted["foreground"], "cyan")
        self.assertFalse(muted["dim"])

    def test_summarize_iostat_compacts_long_device_row(self):
        lltop = load_lltop()
        row = "nvme0n1 8.04 610.05 5.11 38.87 0.15 75.92 9.43 778.72 16.79 64.03 9.77 82.57 0.00 0.00 0.00 0.00 0.00 0.00 0.00 0.00 0.00 0.00"

        summary = lltop.summarize_iostat(row)

        self.assertEqual(
            summary, "nvme0n1 r/s 8.04 w/s 9.43 read 610.05 KiB/s write 778.72 KiB/s util 0.00%"
        )

    def test_summarize_vmstat_uses_correct_cpu_columns(self):
        lltop = load_lltop()
        row = "1 0 830536 17758792 63748 39660764 0 0 0 124 4957 5259 1 2 97 0 0 0"

        summary = lltop.summarize_vmstat(row)

        self.assertEqual(summary, "r 1 b 0 free 17758792 KiB in 4957 cs 5259 cpu 1u/2s/97i")

    def test_compact_free_row_removes_padding(self):
        lltop = load_lltop()
        row = "Mem:            61Gi       8.2Gi       7.0Gi       123Mi        46Gi        53Gi"

        self.assertEqual(lltop.compact_free_row(row), "Mem: 61Gi 8.2Gi 7.0Gi 123Mi 46Gi 53Gi")

    def test_cpu_percentages_from_proc_stat_samples(self):
        lltop = load_lltop()
        before = {
            "cpu0": [100, 0, 100, 800, 0, 0, 0, 0, 0, 0],
            "cpu1": [200, 0, 100, 700, 0, 0, 0, 0, 0, 0],
        }
        after = {
            "cpu0": [150, 0, 150, 900, 0, 0, 0, 0, 0, 0],
            "cpu1": [220, 0, 120, 860, 0, 0, 0, 0, 0, 0],
        }

        self.assertEqual(lltop.cpu_percentages(before, after), [("0", 50), ("1", 20)])

    def test_parse_slots_extracts_decoded_counts(self):
        lltop = load_lltop()
        body = '[{"id":0,"is_processing":true,"id_task":7,"next_token":[{"n_decoded":42}]},{"id":1,"is_processing":false,"id_task":8,"next_token":[{"n_decoded":3}]}]'

        self.assertEqual(
            lltop.parse_slots(body),
            [
                {"id": 0, "task": 7, "is_processing": True, "decoded": 42},
                {"id": 1, "task": 8, "is_processing": False, "decoded": 3},
            ],
        )

    def test_tps_tracker_computes_live_decode_rate(self):
        lltop = load_lltop()
        tracker = lltop.TpsTracker()

        first = [{"id": 0, "task": 7, "is_processing": True, "decoded": 10}]
        second = [{"id": 0, "task": 7, "is_processing": True, "decoded": 70}]

        self.assertIsNone(tracker.update(first, now=100.0)["live_tps"])
        self.assertEqual(
            tracker.update(second, now=103.0),
            {"live_tps": 20.0, "active_slots": 1, "total_slots": 1},
        )

    def test_collect_gpu_reads_all_amd_sysfs_devices(self):
        lltop = load_lltop()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            intel = root / "card1" / "device"
            amd = root / "card2" / "device"
            amd2 = root / "card3" / "device"
            intel.mkdir(parents=True)
            amd.mkdir(parents=True)
            amd2.mkdir(parents=True)
            (intel / "vendor").write_text("0x8086\n")
            (amd / "vendor").write_text("0x1002\n")
            (amd2 / "vendor").write_text("0x1002\n")
            (amd / "gpu_busy_percent").write_text("37\n")
            (amd / "mem_busy_percent").write_text("12\n")
            (amd / "mem_info_vram_total").write_text("21458059264\n")
            (amd / "mem_info_vram_used").write_text("10729029632\n")
            (amd2 / "gpu_busy_percent").write_text("5\n")
            (amd2 / "mem_busy_percent").write_text("2\n")
            (amd2 / "mem_info_vram_total").write_text("8589934592\n")
            (amd2 / "mem_info_vram_used").write_text("1073741824\n")
            hwmon = amd / "hwmon" / "hwmon4"
            hwmon.mkdir(parents=True)
            (hwmon / "temp1_input").write_text("46000\n")
            (hwmon / "temp2_input").write_text("52000\n")
            (hwmon / "power1_average").write_text("10000000\n")
            (hwmon / "fan1_input").write_text("900\n")
            (hwmon / "pwm1").write_text("77\n")  # ~30%

            gpu = lltop.collect_gpu(root)

        self.assertEqual(len(gpu["gpus"]), 2)
        self.assertEqual(gpu["gpus"][0]["path"], str(amd))
        self.assertEqual(gpu["gpus"][0]["vendor"], "AMD")
        self.assertEqual(gpu["gpus"][0]["gpu_busy_percent"], 37)
        self.assertEqual(gpu["gpus"][0]["mem_busy_percent"], 12)
        self.assertEqual(gpu["gpus"][0]["vram_used"], 10729029632)
        self.assertEqual(gpu["gpus"][0]["vram_total"], 21458059264)
        self.assertEqual(gpu["gpus"][0]["temp_c"], 46.0)
        self.assertEqual(gpu["gpus"][0]["junction_temp_c"], 52.0)
        self.assertEqual(gpu["gpus"][0]["power_w"], 10.0)
        self.assertEqual(gpu["gpus"][0]["fan_rpm"], 900)
        self.assertEqual(gpu["gpus"][1]["path"], str(amd2))
        self.assertEqual(gpu["gpus"][1]["gpu_busy_percent"], 5)

    def test_collect_nvidia_gpus_parses_nvidia_smi_csv(self):
        lltop = load_lltop()
        original_run_command = lltop.run_command
        try:
            # 11 fields: name, pci.bus_id, util.gpu, util.mem, mem.used, mem.total,
            #            temp, power, clocks.sm, clocks.mem, fan.speed
            lltop.run_command = lambda *_a, **_kw: (
                "Tesla P40, 00000000:03:00.0, 83, 21, 1024, 22919, 62, 94.50, 1328, 3615, 45"
            )

            gpus = lltop.collect_nvidia_gpus()
        finally:
            lltop.run_command = original_run_command

        self.assertEqual(len(gpus), 1)
        gpu = gpus[0]
        self.assertEqual(gpu["vendor"], "NVIDIA")
        self.assertEqual(gpu["name"], "Tesla P40")
        self.assertEqual(gpu["pci_id"], "03:00.0")
        self.assertEqual(gpu["gpu_busy_percent"], 83)
        self.assertEqual(gpu["mem_busy_percent"], 21)
        self.assertEqual(gpu["vram_used"], 1073741824)
        self.assertEqual(gpu["vram_total"], 24032313344)
        self.assertEqual(gpu["temp_c"], 62.0)
        self.assertEqual(gpu["power_w"], 94.5)
        self.assertEqual(gpu["fan_pct"], 45)
        self.assertEqual(gpu["sclk"], "1328 MHz")
        self.assertEqual(gpu["mclk"], "3615 MHz")

    def test_render_snapshot_contains_gpu_runners_and_logs(self):
        lltop = load_lltop()
        snapshot = self.sample_snapshot()

        output = lltop.render_snapshot(snapshot, width=120, height=32)

        self.assertIn("lltop ubt26 12:34:56", output)
        self.assertIn("GPU", output)
        self.assertIn("37%", output)
        self.assertIn("10.0 GiB / 20.0 GiB", output)
        self.assertIn("Runners", output)
        self.assertIn("Qwen3-30B-A3B-Q4", output)
        self.assertIn("rocm", output)
        self.assertIn("amd-dual", output)
        self.assertIn("Logs", output)
        self.assertIn("slot 0 idle", output)

    def test_render_snapshot_shows_amd_and_nvidia_gpus(self):
        lltop = load_lltop()
        snapshot = self.sample_snapshot()
        snapshot["gpu"]["gpus"].append(
            {
                "vendor": "NVIDIA",
                "name": "Tesla P40",
                "index": 0,
                "pci_id": "0000:06:00.0",
                "gpu_busy_percent": 83,
                "mem_busy_percent": 21,
                "vram_used": 1073741824,
                "vram_total": 24032313344,
                "temp_c": 62.0,
                "power_w": 94.5,
                "fan_pct": 45,
                "sclk": "1328 MHz",
                "mclk": "3615 MHz",
            }
        )

        output = lltop.render_snapshot(snapshot, width=120, height=40)

        self.assertIn("AMD", output)
        self.assertIn("NVIDIA Tesla P40", output)
        self.assertIn("83%", output)
        self.assertIn("1.0 GiB / 22.4 GiB", output)

    def test_runner_panel_shows_token_throughput(self):
        lltop = load_lltop()
        snapshot = self.sample_snapshot()

        output = lltop.render_snapshot(snapshot, width=120, height=32)

        self.assertIn("tokens/sec: live 45.2", output)
        self.assertIn("slots 1/1", output)

    def test_runner_panel_shows_stopped_when_not_running(self):
        lltop = load_lltop()
        snapshot = self.sample_snapshot()
        snapshot["runners"][0]["running"] = False
        snapshot["runners"][0]["api"] = {"health": "stopped", "models": "n/a", "tps": {}}

        output = lltop.render_snapshot(snapshot, width=120, height=32)

        self.assertIn("stopped", output)

    def test_render_snapshot_shows_gpu_cluster_assignment(self):
        lltop = load_lltop()
        snapshot = self.sample_snapshot()
        # GPU pci_id 0000:03:00.0 is in the amd-dual cluster's gpu_pci_ids
        snapshot["runners"][0]["gpu_pci_ids"] = ["0000:03:00.0"]

        output = lltop.render_snapshot(snapshot, width=120, height=32)

        # GPU line should mention the cluster
        self.assertIn("amd-dual", output)

    def test_render_snapshot_uses_ascii_panels(self):
        lltop = load_lltop()

        output = lltop.render_snapshot(self.sample_snapshot(), width=120, height=32)

        self.assertIn("+-- GPU ", output)
        self.assertIn("+-- Runners ", output)
        self.assertIn("+-- System ", output)
        self.assertIn("+-- Logs ", output)

    def test_render_snapshot_keeps_logs_visible_when_height_is_limited(self):
        lltop = load_lltop()
        snapshot = self.sample_snapshot()
        snapshot["logs"] = [f"line {index}" for index in range(20)]

        output = lltop.render_snapshot(snapshot, width=120, height=18)

        self.assertIn("+-- Logs ", output)
        self.assertIn("line 19", output)

    def test_render_snapshot_shows_no_runners_placeholder(self):
        lltop = load_lltop()
        snapshot = self.sample_snapshot()
        snapshot["runners"] = []

        output = lltop.render_snapshot(snapshot, width=120, height=32)

        self.assertIn("no active runners", output)

    def test_gpu_cluster_label_matches_by_pci_id(self):
        lltop = load_lltop()
        runners = [
            {"cluster_name": "amd-dual", "gpu_pci_ids": ["0000:03:00.0", "0000:04:00.0"]},
            {"cluster_name": "nvidia-p40", "gpu_pci_ids": ["0000:06:00.0"]},
        ]

        label = lltop._gpu_cluster_label("0000:03:00.0", runners)
        self.assertEqual(label, " [amd-dual]")

        label2 = lltop._gpu_cluster_label("0000:06:00.0", runners)
        self.assertEqual(label2, " [nvidia-p40]")

        label3 = lltop._gpu_cluster_label("0000:99:00.0", runners)
        self.assertEqual(label3, "")

    def test_docker_decode_log_bytes_strips_multiplex_headers(self):
        lltop = load_lltop()
        # Simulate Docker log frame: stream=1 (stdout), size=12
        msg = b"hello world\n"
        header = b"\x01\x00\x00\x00" + len(msg).to_bytes(4, "big")
        raw = header + msg

        result = lltop._decode_docker_log_bytes(raw)

        self.assertEqual(result, "hello world\n")

    def test_docker_decode_log_bytes_fallback_for_raw_text(self):
        lltop = load_lltop()
        raw = b"plain text without headers\n"

        result = lltop._decode_docker_log_bytes(raw)

        self.assertEqual(result, "plain text without headers\n")

    def test_system_panel_shows_cpu_cores_and_memory_headers(self):
        lltop = load_lltop()
        snapshot = self.sample_snapshot()
        snapshot["system"]["cpu_cores"] = [("0", 50), ("1", 20)]
        snapshot["system"]["swap"] = "Swap: 8.0Gi 811Mi 7.2Gi"

        output = lltop.render_snapshot(snapshot, width=100, height=40)

        self.assertIn("CPU cores:", output)
        self.assertIn("00 [#####-----] 50%", output)
        self.assertIn("01 [##--------] 20%", output)
        self.assertIn("Memory columns: total used free shared buff/cache available", output)
        self.assertIn("Swap columns: total used free", output)

    def test_join_columns_places_blocks_side_by_side(self):
        lltop = load_lltop()

        output = lltop.join_columns(["left", "cpu"], ["right", "mem"], left_width=8, gap=" | ")

        self.assertEqual(output, ["left     | right", "cpu      | mem"])

    def test_wide_system_panel_uses_side_by_side_subpanels(self):
        lltop = load_lltop()
        snapshot = self.sample_snapshot()
        snapshot["system"].update(
            {
                "cpu_cores": [(str(index), 10 * index) for index in range(4)],
                "mem": "Mem:            61Gi       8.2Gi       7.0Gi       123Mi        46Gi        53Gi",
                "swap": "Swap: 8.0Gi 811Mi 7.2Gi",
                "vmstat": "r 1 b 0 free 1 KiB in 2 cs 3 cpu 4u/5s/91i",
                "iostat": "nvme0n1 r/s 1 w/s 2 read 3 KiB/s write 4 KiB/s util 5%",
            }
        )

        output = lltop.render_snapshot(snapshot, width=140, height=50)

        self.assertIn("+-- CPU ", output)
        self.assertIn("+-- Memory / IO ", output)
        system_header_line = next(line for line in output.splitlines() if "+-- CPU " in line)
        self.assertIn("+-- Memory / IO ", system_header_line)
        self.assertIn("Mem: 61Gi 8.2Gi 7.0Gi 123Mi 46Gi 53Gi", output)

    def test_narrow_system_panel_uses_stacked_layout(self):
        lltop = load_lltop()
        snapshot = self.sample_snapshot()
        snapshot["system"]["cpu_cores"] = [("0", 50), ("1", 20)]

        output = lltop.render_snapshot(snapshot, width=100, height=40)

        self.assertIn("+-- System ", output)
        self.assertNotIn("+-- Memory / IO ", output)

    def test_amd_gpu_shows_fan_and_junction_temp(self):
        lltop = load_lltop()
        snapshot = self.sample_snapshot()

        output = lltop.render_snapshot(snapshot, width=120, height=32)

        self.assertIn("junction", output)
        self.assertIn("Fan 30%", output)
        self.assertIn("900 RPM", output)

    def test_read_json_dir_returns_empty_for_missing_dir(self):
        lltop = load_lltop()

        result = lltop._read_json_dir(Path("/nonexistent/path"))

        self.assertEqual(result, [])

    def test_read_json_dir_reads_json_files(self):
        lltop = load_lltop()

        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "a.json").write_text('{"x": 1}')
            (d / "b.json").write_text('{"x": 2}')
            (d / "c.txt").write_text("ignored")

            result = lltop._read_json_dir(d)

        self.assertEqual(len(result), 2)
        self.assertEqual({r["x"] for r in result}, {1, 2})


if __name__ == "__main__":
    unittest.main()
