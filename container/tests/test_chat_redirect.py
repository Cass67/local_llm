"""Tests for direct management-port chat redirects."""

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_chat_path_redirects_from_management_port_to_caddy_chat():
    from backend.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://ubt26:3100", follow_redirects=False
    ) as client:
        response = await client.get("/chat/")

    assert response.status_code == 307
    assert response.headers["location"] == "http://ubt26:3001/chat/"
