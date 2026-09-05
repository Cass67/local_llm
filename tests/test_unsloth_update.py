import re
import sys
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "container"))

from backend.routes import update  # noqa: E402


@pytest.mark.parametrize("backend", ["rocmunsloth", "rocmunslothsrc"])
def test_no_default_tag_in_the_dockerfile(backend):
    """The image label is the only record of a variant's tag.

    A default here is a second source of truth that nothing keeps current -- it silently sat
    five releases behind what the Updates panel was actually building.
    """
    text = (Path(__file__).resolve().parents[1] / "runner" / backend / "Dockerfile").read_text()
    assert re.search(r"^ARG UNSLOTH_TAG$", text, re.M), "UNSLOTH_TAG must have no default"
    assert not re.search(r"^ARG UNSLOTH_TAG=", text, re.M)


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
