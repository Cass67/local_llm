import asyncio
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


def _write(path, families):
    path.write_text(json.dumps({"families": families}))


def test_diff_reports_only_what_changed(state):
    before = {
        "fam-a": {"default": "dflash", "profiles": {"dflash": {"ngl": 999, "spec_type": "x"}}},
        "fam-b": {"default": "rccl", "profiles": {"rccl": {"ubatch": 512}}},
    }
    _write(config.PROFILES_CONFIG, before)
    snap_id = config.snapshot_profiles("before")

    after = {
        # spec_type dropped, ubatch added — the real dflash regression shape.
        "fam-a": {"default": "dflash", "profiles": {"dflash": {"ngl": 999, "ubatch": 256}}},
        # untouched, must not appear
        "fam-b": before["fam-b"],
        "fam-c": {"default": "new", "profiles": {"new": {}}},
    }
    _write(config.PROFILES_CONFIG, after)

    changes = asyncio.run(profiles.diff_snapshot(snap_id))["changes"]
    by_name = {(c["family"], c["profile"]): c for c in changes}

    assert ("fam-b", "rccl") not in by_name
    assert by_name[("fam-a", "dflash")]["status"] == "changed"
    assert by_name[("fam-a", "dflash")]["keys"] == ["spec_type", "ubatch"]
    assert by_name[("fam-c", "new")]["status"] == "added-since"


def test_scoped_restore_touches_only_that_profile(state, monkeypatch):
    monkeypatch.setattr(profiles.active_runners, "restart_running_for_profile", lambda f, p: [])
    _write(
        config.PROFILES_CONFIG,
        {
            "fam": {
                "default": "dflash",
                "profiles": {"dflash": {"spec_type": "draft-dflash"}, "rccl": {"ubatch": 512}},
            }
        },
    )
    snap_id = config.snapshot_profiles("good")

    _write(
        config.PROFILES_CONFIG,
        {"fam": {"default": "dflash", "profiles": {"dflash": {}, "rccl": {"ubatch": 999}}}},
    )

    res = asyncio.run(profiles.restore_snapshot(snap_id, {"family": "fam", "profile": "dflash"}))
    assert res["scope"] == "fam/dflash"

    now = json.loads(config.PROFILES_CONFIG.read_text())["families"]["fam"]["profiles"]
    assert now["dflash"] == {"spec_type": "draft-dflash"}  # restored
    assert now["rccl"] == {"ubatch": 999}  # NOT reverted


def test_scoped_restore_rejects_profile_absent_from_snapshot(state):
    _write(config.PROFILES_CONFIG, {"fam": {"default": "a", "profiles": {"a": {}}}})
    snap_id = config.snapshot_profiles("s")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(profiles.restore_snapshot(snap_id, {"family": "fam", "profile": "ghost"}))
    assert exc.value.status_code == 404


def test_label_is_slugified(state):
    config.save_profiles(_fam("a"), "x")
    config.save_profiles(_fam("b"), "edit/Qwen3.6 27B::rccl!!")

    snap = sorted(config.PROFILE_SNAPSHOTS_DIR.glob("*.json"))[0]
    assert snap.stem.endswith("_edit-qwen3-6-27b-rccl")
