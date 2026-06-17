from __future__ import annotations

import subprocess

from scripts.model_manager import commands
from scripts.model_manager.config import SCRIPT_DIR


class DummyResult:
    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def test_run_benchmark_uses_repo_model_manager_and_remote_target(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return DummyResult(stdout="result_file=/tmp/bench.json\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = commands._run_benchmark(
        "ubt26",
        "repo/model",
        "family",
        "alias",
        "balanced",
        "Q4_K_M",
        "model.gguf",
        "131072",
    )

    assert result == "/tmp/bench.json"
    cmd, kwargs = calls[0]
    expected_manager = str(SCRIPT_DIR / "model-manager.sh")
    assert cmd[0] == expected_manager
    assert "model-manager" not in cmd[:1]
    assert cmd[:2] == [expected_manager, "benchmark"]
    assert ["--target", "remote:ubt26"] == cmd[2:4]
    assert kwargs["timeout"] >= 900


def test_deploy_uses_repo_model_manager(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return DummyResult(stdout="ok\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert commands._deploy_accepted_to_remote("ubt26") is True

    expected_manager = str(SCRIPT_DIR / "model-manager.sh")
    assert calls[0][0][:2] == [expected_manager, "deploy"]
    assert ["--target", "remote:ubt26"] == calls[0][0][2:4]
