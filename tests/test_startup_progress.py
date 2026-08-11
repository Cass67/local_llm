import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "container"))

from backend import startup_progress  # noqa: E402
from backend.active_runners import _wait_ready  # noqa: E402


class FakeRunner:
    """Runner that never answers /v1/models, so _wait_ready polls until timeout."""

    def __init__(self, log_lines):
        self.log_lines = log_lines

    def is_running(self):
        return True

    def logs(self, lines=80):
        return self.log_lines[-lines:]


def test_progress_tracks_stages_and_elapsed():
    startup_progress.clear("c1")
    startup_progress.begin("c1", "qwopus-27b", "rccl")
    assert startup_progress.get("c1")["stage"] == "stopping"

    startup_progress.set_stage("c1", "loading", "load_tensors: 40%")
    entry = startup_progress.get("c1")
    assert entry["stage"] == "loading"
    assert entry["detail"] == "load_tensors: 40%"
    assert entry["model"] == "qwopus-27b"
    assert entry["elapsed_s"] >= 0

    startup_progress.finish("c1")
    assert startup_progress.get("c1")["stage"] == "ready"
    assert startup_progress.get("c1")["error"] is None

    startup_progress.clear("c1")
    assert startup_progress.get("c1") is None


def test_failed_launch_records_the_error():
    startup_progress.begin("c2", "muse-30b", "balanced")
    startup_progress.finish("c2", error="out of memory")
    entry = startup_progress.get("c2")
    assert entry["stage"] == "failed"
    assert entry["error"] == "out of memory"
    startup_progress.clear("c2")


def test_wait_ready_reports_the_newest_log_line():
    seen: list[str] = []
    runner = FakeRunner(["loading model", "load_tensors: buffer size = 12000 MiB", "   "])
    # Timeout below the 1s poll sleep keeps this to a single pass.
    assert _wait_ready(runner, port=1, timeout=0.1, on_poll=seen.append) is False
    # Blank trailing lines are skipped, so the newest real line is reported.
    assert seen == ["load_tensors: buffer size = 12000 MiB"]


def test_updates_survive_a_runner_with_no_logs():
    seen: list[str] = []
    assert _wait_ready(FakeRunner([]), port=1, timeout=0.1, on_poll=seen.append) is False
    assert seen == [""]
