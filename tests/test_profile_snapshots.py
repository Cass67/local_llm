import json
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "container"))

from backend import config  # noqa: E402
from backend.routes import profiles  # noqa: E402


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROFILES_CONFIG", tmp_path / "profiles.json")
    monkeypatch.setattr(config, "PROFILE_SNAPSHOTS_DIR", tmp_path / "profile-snapshots")
    return tmp_path


def _fam(name):
    return {"families": {name: {"default": "balanced", "profiles": {"balanced": {"ngl": 999}}}}}


def test_save_snapshots_previous_contents_not_the_new_ones(state):
    config.save_profiles(_fam("before"), "first")
    config.save_profiles(_fam("after"), "second")

    snaps = sorted(config.PROFILE_SNAPSHOTS_DIR.glob("*.json"))
    # First save had nothing to snapshot; second preserved the pre-edit state.
    assert len(snaps) == 1
    assert "before" in json.loads(snaps[0].read_text())["families"]
    assert "after" in json.loads(config.PROFILES_CONFIG.read_text())["families"]
    assert snaps[0].stem.endswith("_second")


def test_pruning_keeps_newest_n(state, monkeypatch):
    monkeypatch.setattr(config, "PROFILE_SNAPSHOTS_KEEP", 3)
    for i in range(6):
        config.save_profiles(_fam(f"gen{i}"), f"edit{i}")

    snaps = sorted(config.PROFILE_SNAPSHOTS_DIR.glob("*.json"))
    assert len(snaps) == 3
    # Oldest dropped, newest kept — snapshot taken at save i holds the state from save i-1.
    kept = [next(iter(json.loads(p.read_text())["families"])) for p in snaps]
    assert kept == ["gen2", "gen3", "gen4"]


def test_restore_is_itself_undoable(state):
    config.save_profiles(_fam("original"), "setup")
    config.save_profiles(_fam("mistake"), "oops")  # snapshots "original"

    snap_id = sorted(config.PROFILE_SNAPSHOTS_DIR.glob("*.json"))[0].stem
    data = json.loads(profiles._snapshot_path(snap_id).read_text())
    profiles._save(data, f"pre-restore-{snap_id[:15]}")

    assert list(json.loads(config.PROFILES_CONFIG.read_text())["families"]) == ["original"]
    # The bad state was preserved on the way out, so the restore can be walked back.
    pre = list(config.PROFILE_SNAPSHOTS_DIR.glob("*pre-restore*.json"))
    assert len(pre) == 1
    assert list(json.loads(pre[0].read_text())["families"]) == ["mistake"]


def test_snapshot_path_rejects_traversal(state):
    config.save_profiles(_fam("x"), "a")
    config.save_profiles(_fam("y"), "b")
    (state / "secret.json").write_text('{"families": {}}')

    with pytest.raises(HTTPException) as exc:
        profiles._snapshot_path("../secret")
    assert exc.value.status_code == 404


def test_label_is_slugified(state):
    config.save_profiles(_fam("a"), "x")
    config.save_profiles(_fam("b"), "edit/Qwen3.6 27B::rccl!!")

    snap = sorted(config.PROFILE_SNAPSHOTS_DIR.glob("*.json"))[0]
    assert snap.stem.endswith("_edit-qwen3-6-27b-rccl")
