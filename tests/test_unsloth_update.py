import sys
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "container"))

from backend.routes import update  # noqa: E402


def test_reads_the_pinned_tag(tmp_path, monkeypatch):
    (tmp_path / "rocmunsloth").mkdir()
    (tmp_path / "rocmunsloth" / "Dockerfile").write_text(
        "FROM x\nARG UNSLOTH_TAG=b10715-mix-86bd2d3\nARG UNSLOTH_ASSET=app.tar.gz\n"
    )
    monkeypatch.setattr(update, "RUNNER_SRC_DIR", tmp_path)
    assert update._unsloth_pin("rocmunsloth", {}) == "b10715-mix-86bd2d3"
    assert update._unsloth_pin("missing", {}) is None
    # A rebuilt image carries the tag it was built with; the ARG is only the fallback.
    assert update._unsloth_pin("rocmunsloth", {"unsloth.tag": "b10796-mix-659e406"}) == (
        "b10796-mix-659e406"
    )


class _FakeClient:
    def __init__(self, routes):
        self.routes = routes

    async def get(self, url, **kw):
        return httpx.Response(200, json=self.routes[url], request=httpx.Request("GET", url))


def _release(tag, assets):
    return {"tag_name": tag, "assets": [{"name": n} for n in assets]}


@pytest.mark.asyncio
async def test_latest_skips_a_release_without_a_gfx110x_asset():
    client = _FakeClient(
        {
            f"{update.GITHUB_REPOS}/{update.UNSLOTH_REPO}/releases": [
                _release("b10800-mix-aaa", ["app-b10800-mix-aaa-linux-x64-cuda.tar.gz"]),
                _release(
                    "b10796-mix-659e406",
                    ["app-b10796-mix-659e406-linux-x64-rocm-gfx110X.tar.gz"],
                ),
            ]
        }
    )
    tag, asset = await update._latest_unsloth(client)
    assert tag == "b10796-mix-659e406"
    assert asset == "app-b10796-mix-659e406-linux-x64-rocm-gfx110X.tar.gz"


@pytest.mark.asyncio
async def test_base_comes_from_the_upstream_tag_in_the_release_name():
    client = _FakeClient({f"{update.GITHUB_API}/commits/b10715": {"sha": "662a0b0121a5"}})
    assert await update._unsloth_base(client, "b10715-mix-86bd2d3") == "662a0b0121a5"
    with pytest.raises(HTTPException):
        await update._unsloth_base(client, "nightly")
