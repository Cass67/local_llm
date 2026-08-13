"""Chat / Langfuse update rows: pinned release series and behind-count."""

import httpx
import pytest


class FakeClient:
    def __init__(self, routes):
        self.routes = routes

    async def get(self, url, **kw):
        request = httpx.Request("GET", url, params=kw.get("params"))
        for match, body in self.routes:
            if match in str(request.url):
                return httpx.Response(200, json=body, request=request)
        return httpx.Response(404, json={}, request=request)


@pytest.mark.asyncio
async def test_langfuse_row_stays_on_the_v2_line(monkeypatch):
    from backend.routes import update

    monkeypatch.setattr(
        update, "_image_meta", lambda image: (True, {"langfuse.version": "2.95.11"}, [image])
    )
    client = FakeClient(
        [("/tags", [{"name": n} for n in ("v4.10.0", "v3.225.3", "v2.95.12", "v2.95.11")])]
    )
    row = await update._service_row(client, "langfuse", update.SERVICES["langfuse"])

    assert row["current"] == "2.95.11"
    assert row["latest"] == "2.95.12"  # not v4.10.0 -- v3+ needs ClickHouse
    assert row["outdated"]


@pytest.mark.asyncio
async def test_chat_row_counts_commits_behind_upstream(monkeypatch):
    from backend.routes import update

    revision = "a" * 40
    monkeypatch.setattr(
        update,
        "_image_meta",
        lambda image: (True, {"org.opencontainers.image.revision": revision}, [image]),
    )
    client = FakeClient(
        [
            ("/commits/main", {"sha": "b" * 40}),
            (f"/compare/{revision}...main", {"ahead_by": 7}),
        ]
    )
    row = await update._service_row(client, "chat", update.SERVICES["chat"])

    assert row["current"] == "a" * 12
    assert row["latest"] == "b" * 12
    assert (row["behind"], row["outdated"]) == (7, True)


@pytest.mark.asyncio
async def test_unknown_service_is_404():
    from backend.main import app
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/update/services/nope/build")
    assert resp.status_code == 404
