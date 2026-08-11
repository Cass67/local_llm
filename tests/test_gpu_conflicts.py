import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "container"))

import pytest  # noqa: E402
from backend import active_runners  # noqa: E402
from backend.clusters import ClusterDef  # noqa: E402


def _cluster(cid, name, pci, port):
    return ClusterDef(
        id=cid,
        name=name,
        gpu_pci_ids=pci,
        backend="rocm",
        port=port,
        container_name=f"local-llm-runner-{cid}",
    )


THREE = _cluster("a", "7900sr", ["0000:03:00.0", "0000:06:00.0", "0000:09:00.0"], 8080)
SUBSET = _cluster("b", "7900srccl", ["0000:03:00.0", "0000:06:00.0"], 8086)
SEPARATE = _cluster("c", "7900", ["0000:04:00.0"], 8081)


@pytest.fixture
def stopped(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(active_runners, "list_clusters", lambda: [THREE, SUBSET, SEPARATE])
    monkeypatch.setattr(active_runners, "is_running", lambda c: c.id != "b")
    monkeypatch.setattr(active_runners, "stop", lambda c: calls.append(c.id))
    monkeypatch.setattr(active_runners.startup_progress, "clear", lambda _id: None)
    return calls


def test_stops_overlapping_cluster(stopped):
    # Starting the 2-card subset must free the 3-card cluster holding those cards.
    active_runners._stop_gpu_conflicts(SUBSET)
    assert stopped == ["a"]


def test_leaves_disjoint_cluster_alone(stopped):
    # 7900 is on a different card entirely, so it keeps running.
    active_runners._stop_gpu_conflicts(SEPARATE)
    assert stopped == []


def test_never_stops_itself(stopped):
    # THREE is "running", but starting it must not stop it -- start() already
    # calls stop(cluster) for that, and stopping twice would be a wasted restart.
    active_runners._stop_gpu_conflicts(THREE)
    assert "a" not in stopped
