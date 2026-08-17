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
    history = [{"sha": f"{i:040x}"} for i in range(7)] + [{"sha": revision}]
    client = FakeClient([("/commits", history)])
    row = await update._service_row(client, "chat", update.SERVICES["chat"])

    assert row["current"] == "a" * 12
    assert row["latest"] == f"{0:040x}"[:12]
    assert (row["behind"], row["outdated"]) == (7, True)


@pytest.mark.asyncio
async def test_runner_behind_count_walks_master(monkeypatch):
    """/compare 404s on llama.cpp, so behind-counts come from the commit list."""
    from backend.routes import update

    def commit(i):
        return {
            "sha": f"{i:02d}" + "a" * 38,
            "commit": {
                "message": f"c{i}\n\nbody",
                "author": {"name": "dev"},
                "committer": {"date": "2026-08-17T00:00:00Z"},
            },
        }

    history = [commit(i) for i in range(60)]
    monkeypatch.setattr(update, "_distinct_images", lambda: {"rocm": "runner-rocm:latest"})
    # image label carries a 12-char sha, master's list carries the full one
    monkeypatch.setattr(update, "_image_commit", lambda image: (True, ("39" + "a" * 38)[:12]))

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, **kw):
            request = httpx.Request("GET", url, params=kw.get("params"))
            return httpx.Response(200, json=history, request=request)

    monkeypatch.setattr(update, "GitHub", lambda **kw: Client())
    data = await update.update_status()

    assert data["backends"][0]["behind"] == 39
    assert data["latest"]["sha"] == "00" + "a" * 38
    assert len(data["commits"]) == 39  # the commits it is missing, newest first


@pytest.mark.asyncio
async def test_github_client_caches_and_reports_rate_limit(monkeypatch):
    from backend.routes import update

    calls = []
    limited = {"on": False}

    class Counting:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, **kw):
            calls.append(url)
            request = httpx.Request("GET", url)
            if limited["on"]:
                return httpx.Response(
                    403,
                    json={},
                    request=request,
                    headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1786700000"},
                )
            return httpx.Response(200, json={"sha": "abc"}, request=request)

    monkeypatch.setattr(update.httpx, "AsyncClient", Counting)
    update._gh_cache.clear()

    async with update.GitHub() as client:
        await client.get("https://api.github.com/repos/x/y/commits/main")
        await client.get("https://api.github.com/repos/x/y/commits/main")
    assert len(calls) == 1  # second read served from cache, not from the quota

    limited["on"] = True
    update._gh_cache.clear()
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as excinfo:
        async with update.GitHub() as client:
            await client.get("https://api.github.com/repos/x/y/tags")
    assert excinfo.value.status_code == 429
    assert "GITHUB_TOKEN" in excinfo.value.detail  # tells the user how to raise the cap
    update._gh_cache.clear()


def test_jobs_are_independent():
    """A langfuse rebuild must not lock out an opencode bump."""
    from backend.routes import update
    from fastapi import HTTPException

    update._jobs.clear()
    update._claim_job("langfuse", ["langfuse"])
    update._claim_job("agents", ["agents"])  # different job: allowed while langfuse runs

    with pytest.raises(HTTPException) as excinfo:
        update._claim_job("langfuse", ["langfuse"])  # same job twice: rejected
    assert excinfo.value.status_code == 409

    assert update._others_running("langfuse") is True
    update._finish(update._jobs["agents"])
    assert update._others_running("langfuse") is False
    update._jobs.clear()


@pytest.mark.asyncio
async def test_unknown_service_is_404():
    from backend.main import app
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/update/services/nope/build")
    assert resp.status_code == 404
