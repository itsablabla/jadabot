"""API tests: admin auth, runtime token scoping, deletion propagation."""

from __future__ import annotations

import httpx
import pytest

from jadabot.app import create_app
from jadabot.memory.manager import MemoryManager
from jadabot.memory.scopes import MemoryScope

from conftest import ADMIN_KEY


@pytest.fixture
def app(manager: MemoryManager):
    return create_app(memory_manager=manager, memory_admin_key=ADMIN_KEY)


@pytest.fixture
async def api(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://core.test") as client:
        yield client


def admin_headers():
    return {"Authorization": "Bearer " + ADMIN_KEY}


async def seed(manager: MemoryManager):
    await manager.add(
        MemoryScope(bot_id="bot-a", user_id="user-1"),
        [{"role": "user", "content": "I like hiking"}],
    )
    await manager.add(
        MemoryScope(bot_id="bot-b", user_id="user-1"),
        [{"role": "user", "content": "I like swimming"}],
    )


async def test_admin_requires_auth(api):
    resp = await api.get("/api/memory/admin/bots")
    assert resp.status_code == 401
    resp = await api.get(
        "/api/memory/admin/bots", headers={"Authorization": "Bearer " + "wrong-key"}
    )
    assert resp.status_code == 403


async def test_admin_config_roundtrip(api):
    resp = await api.put(
        "/api/memory/admin/bots/bot-a/config",
        json={"enabled": False, "scope_policy": "per_session", "search_top_k": 3},
        headers=admin_headers(),
    )
    assert resp.status_code == 200
    resp = await api.get("/api/memory/admin/bots/bot-a/config", headers=admin_headers())
    body = resp.json()
    assert body["config"]["enabled"] is False
    assert body["config"]["scope_policy"] == "per_session"


async def test_admin_browse_and_search(api, manager):
    await seed(manager)
    resp = await api.get(
        "/api/memory/admin/bots/bot-a/memories",
        params={"user_id": "user-1"},
        headers=admin_headers(),
    )
    assert resp.status_code == 200
    assert len(resp.json()["results"]) == 1

    resp = await api.post(
        "/api/memory/admin/bots/bot-a/search",
        json={"query": "hiking", "user_id": "user-1"},
        headers=admin_headers(),
    )
    assert len(resp.json()["results"]) == 1
    resp = await api.post(
        "/api/memory/admin/bots/bot-a/search",
        json={"query": "swimming", "user_id": "user-1"},
        headers=admin_headers(),
    )
    assert resp.json()["results"] == []


async def test_admin_forget_user_propagates_across_bots(api, manager, fake_mem0):
    await seed(manager)
    resp = await api.delete("/api/memory/admin/users/user-1", headers=admin_headers())
    assert resp.status_code == 200
    assert fake_mem0.memories == []


async def test_admin_delete_memory_wrong_bot_404(api, manager, fake_mem0):
    await seed(manager)
    memory_id = fake_mem0.memories[0]["id"]  # belongs to bot-a
    resp = await api.delete(
        f"/api/memory/admin/bots/bot-b/memories/{memory_id}", headers=admin_headers()
    )
    assert resp.status_code == 404
    resp = await api.delete(
        f"/api/memory/admin/bots/bot-a/memories/{memory_id}", headers=admin_headers()
    )
    assert resp.status_code == 200


async def test_runtime_token_scoping(api, manager):
    await seed(manager)
    token_a = manager.issue_runtime_token("bot-a")

    # Correct scope works
    resp = await api.post(
        "/api/memory/runtime/search",
        json={"bot_id": "bot-a", "query": "hiking", "user_id": "user-1"},
        headers={"Authorization": "Bearer " + token_a},
    )
    assert resp.status_code == 200
    assert len(resp.json()["results"]) == 1

    # bot-a token may not touch bot-b memories
    resp = await api.post(
        "/api/memory/runtime/search",
        json={"bot_id": "bot-b", "query": "swimming", "user_id": "user-1"},
        headers={"Authorization": "Bearer " + token_a},
    )
    assert resp.status_code == 403

    # Garbage token rejected
    resp = await api.post(
        "/api/memory/runtime/search",
        json={"bot_id": "bot-a", "query": "hiking"},
        headers={"Authorization": "Bearer " + "not.a.token"},
    )
    assert resp.status_code == 403


async def test_runtime_add(api, manager, fake_mem0):
    token = manager.issue_runtime_token("bot-a")
    resp = await api.post(
        "/api/memory/runtime/add",
        json={
            "bot_id": "bot-a",
            "user_id": "user-1",
            "messages": [{"role": "assistant", "content": "confirmed: order #42 shipped"}],
        },
        headers={"Authorization": "Bearer " + token},
    )
    assert resp.status_code == 200
    assert len(fake_mem0.memories) == 1
    assert fake_mem0.memories[0]["agent_id"] == "bot-a"
