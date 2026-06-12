"""Tests for /api/local-llm browser API prefix."""

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_local_llm_prefix_rewrites_to_existing_api_routes():
    from backend.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/local-llm/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
