import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "container"))

from backend.routes.update import _parse_npm_versions  # noqa: E402

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
