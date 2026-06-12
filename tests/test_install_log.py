from __future__ import annotations

from scripts.model_manager.tui_helpers import append_install_log_line, create_install_log_lines


def test_create_empty_log():
    lines = create_install_log_lines(max_lines=200)
    assert lines == []


def test_append_log_line():
    log = create_install_log_lines(max_lines=5)
    append_install_log_line(log, "start", max_lines=5)
    append_install_log_line(log, "downloading", max_lines=5)
    append_install_log_line(log, "benchmark", max_lines=5)
    assert len(log) == 3
    # times monotonic or equal (fast runs)
    assert log[0]["time"] <= log[1]["time"]
    assert log[1]["text"] == "downloading"


def test_truncate_when_exceed_max():
    log = create_install_log_lines(max_lines=3)
    for t in ("a", "b", "c", "d"):
        append_install_log_line(log, t, max_lines=3)
    assert len(log) == 3
    # oldest dropped
    assert log[0]["text"] == "b"
    assert log[-1]["text"] == "d"
