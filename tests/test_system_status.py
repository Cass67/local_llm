import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "container"))

from backend.system_status import (  # noqa: E402
    SystemStatusCollector,
    cpu_percent,
    parse_proc_stat,
)

STAT = """cpu  100 0 100 800 0 0 0 0 0 0
cpu0 50 0 50 400 0 0 0 0 0 0
cpu1 50 0 50 400 0 0 0 0 0 0
intr 1 2 3
"""
STAT2 = """cpu  200 0 200 1600 0 0 0 0 0 0
cpu0 100 0 100 800 0 0 0 0 0 0
cpu1 100 0 100 800 0 0 0 0 0 0
intr 1 2 3
"""


def test_parse_proc_stat_skips_non_cpu_lines():
    parsed = parse_proc_stat(STAT)
    assert set(parsed) == {"cpu", "cpu0", "cpu1"}
    assert parsed["cpu"][0] == 100


def test_cpu_percent_delta():
    before = parse_proc_stat(STAT)["cpu"]
    after = parse_proc_stat(STAT2)["cpu"]
    # 200 busy jiffies of 1000 total delta
    assert cpu_percent(before, after) == 20.0
    assert cpu_percent(before, before) is None  # zero delta, not a divide-by-zero


def test_collector_needs_a_baseline_before_reporting_cpu():
    collector = SystemStatusCollector()
    assert collector.sample()["cpu_percent"] is None  # no previous snapshot yet
    second = collector.sample()
    assert second["cpu_percent"] is None or 0.0 <= second["cpu_percent"] <= 100.0
    assert second["mem_total"] is None or second["mem_total"] > 0


if __name__ == "__main__":
    test_parse_proc_stat_skips_non_cpu_lines()
    test_cpu_percent_delta()
    test_collector_needs_a_baseline_before_reporting_cpu()
    print("ok")
