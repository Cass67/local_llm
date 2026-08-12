import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "container"))

from backend.routes.update import _installable_version, _parse_npm_versions  # noqa: E402

NPM_LS = """
{
  "name": "npm-global",
  "dependencies": {
    "@earendil-works/pi-coding-agent": {"version": "0.84.1", "resolved": "..."},
    "opencode-ai": {"version": "1.18.16"},
    "corepack": {"version": "0.29.4", "overridden": false}
  }
}
"""


def test_parses_global_listing():
    versions = _parse_npm_versions(NPM_LS)
    assert versions["@earendil-works/pi-coding-agent"] == "0.84.1"
    assert versions["opencode-ai"] == "1.18.16"


def test_tolerates_broken_output():
    # `npm ls -g` prints warnings on stderr but can also exit non-zero with no JSON
    assert _parse_npm_versions("") == {}
    assert _parse_npm_versions('{"dependencies": {"x": "invalid"}}') == {}


class _Resp:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload


class _FakeRegistry:
    """opencode-ai has published 1.18.17, its platform package has not."""

    VERSIONS = ["1.18.15", "1.18.16", "0.0.0-dev-202608121637", "1.18.17"]

    async def get(self, url, **_kwargs):
        if url.endswith("opencode-ai/latest"):
            return _Resp(200, {"version": "1.18.17"})
        if url.endswith("opencode-ai"):
            return _Resp(200, {"versions": dict.fromkeys(self.VERSIONS, {})})
        version = url.rsplit("/", 1)[1]
        return _Resp(200 if version == "1.18.16" else 404)


def test_skips_versions_whose_platform_package_is_unpublished():
    version = asyncio.run(
        _installable_version(_FakeRegistry(), "opencode-ai", "opencode-linux-x64")
    )
    assert version == "1.18.16"  # not 1.18.17, and not the 0.0.0-dev prerelease
