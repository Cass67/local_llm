"""Commit detail lookup: GitHub commit + originating PR discussion."""

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

COMMIT = {
    "sha": "0666ad2b" + "0" * 32,
    "html_url": "https://github.com/ggml-org/llama.cpp/commit/0666ad2b",
    "commit": {
        "message": "vomit\n\nthe long why",
        "author": {"name": "someone"},
        "committer": {"date": "2026-08-01T00:00:00Z"},
    },
    "stats": {"additions": 3, "deletions": 1, "total": 4},
    "files": [{"filename": "ggml.c", "status": "modified", "additions": 3, "deletions": 1}],
}
PULL = {
    "number": 42,
    "title": "fix vomit",
    "body": "PR body",
    "html_url": "https://github.com/ggml-org/llama.cpp/pull/42",
    "state": "closed",
    "merged_at": "2026-08-01T01:00:00Z",
    "user": {"login": "dev"},
}


class FakeClient:
    """Stand-in for the httpx client the route opens against GitHub."""

    def __init__(self, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, **kw):
        return _github(url)


def _github(url) -> httpx.Response:
    request = httpx.Request("GET", url)
    path = request.url.path
    if path.endswith("/pulls"):
        body = [PULL]
    elif path.endswith("/issues/42/comments"):
        body = [{"user": {"login": "a"}, "body": "why?", "created_at": "2026-08-01T02:00:00Z"}]
    elif path.endswith("/pulls/42/comments"):
        body = [
            {
                "user": {"login": "b"},
                "body": "nit",
                "created_at": "2026-08-01T00:30:00Z",
                "path": "ggml.c",
            }
        ]
    else:
        body = COMMIT
    return httpx.Response(200, json=body, request=request)


@pytest.mark.asyncio
async def test_commit_detail_includes_body_files_and_pr(monkeypatch):
    from backend.routes import update

    monkeypatch.setattr(update.httpx, "AsyncClient", FakeClient)
    data = await update.commit_detail("0666ad2b")

    assert data["subject"] == "vomit"
    assert data["body"] == "the long why"
    assert data["files"][0]["filename"] == "ggml.c"
    assert data["pull"]["number"] == 42
    # review + issue comments merged, oldest first
    assert [c["user"] for c in data["pull"]["comments"]] == ["b", "a"]


@pytest.mark.asyncio
async def test_commit_detail_rejects_non_sha():
    from backend.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/update/commit/master")
    assert resp.status_code == 400
