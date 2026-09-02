import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "container"))

from backend.routes import update  # noqa: E402


def test_reads_the_pinned_tag(tmp_path, monkeypatch):
    (tmp_path / "rocmunsloth").mkdir()
    (tmp_path / "rocmunsloth" / "Dockerfile").write_text(
        "FROM x\nARG UNSLOTH_TAG=b10715-mix-86bd2d3\nARG UNSLOTH_ASSET=app.tar.gz\n"
    )
    monkeypatch.setattr(update, "RUNNER_SRC_DIR", tmp_path)
    assert update._unsloth_pin("rocmunsloth") == "b10715-mix-86bd2d3"
    assert update._unsloth_pin("missing") is None
