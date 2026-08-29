"""Scoping, isolation, and token tests."""

from __future__ import annotations

import pytest

from jadabot.memory.manager import BotMemoryConfig, MemoryManager
from jadabot.memory.scopes import MemoryScope, ScopePolicy
from jadabot.memory.tokens import TokenError, issue_memory_token, verify_memory_token

from conftest import TOKEN_SECRET, FakeMem0


def test_scope_requires_bot_id():
    with pytest.raises(ValueError):
        MemoryScope(bot_id="")


def test_scope_policy_mapping():
    scope = MemoryScope(bot_id="bot-a", user_id="user-1", session_id="sess-9")
    assert scope.to_mem0_identifiers(ScopePolicy.PER_USER) == {
        "agent_id": "bot-a",
        "user_id": "user-1",
    }
    assert scope.to_mem0_identifiers(ScopePolicy.PER_SESSION) == {
        "agent_id": "bot-a",
        "user_id": "user-1",
        "run_id": "sess-9",
    }
    assert scope.to_mem0_identifiers(ScopePolicy.AGENT_GLOBAL) == {"agent_id": "bot-a"}


async def test_bots_cannot_see_each_others_memories(manager: MemoryManager):
    scope_a = MemoryScope(bot_id="bot-a", user_id="user-1")
    scope_b = MemoryScope(bot_id="bot-b", user_id="user-1")
    await manager.add(scope_a, [{"role": "user", "content": "the launch code is banana"}])
    await manager.add(scope_b, [{"role": "user", "content": "favorite fruit is mango"}])

    results_b = await manager.search(scope_b, "banana")
    assert results_b == []
    results_a = await manager.search(scope_a, "banana")
    assert len(results_a) == 1


async def test_cross_session_recall_same_user(manager: MemoryManager):
    """PER_USER policy: memories persist for the user across sessions."""
    session_1 = MemoryScope(bot_id="bot-a", user_id="user-1", session_id="s1")
    session_2 = MemoryScope(bot_id="bot-a", user_id="user-1", session_id="s2")
    await manager.add(session_1, [{"role": "user", "content": "I prefer tea over coffee"}])
    results = await manager.search(session_2, "tea")
    assert len(results) == 1


async def test_per_session_policy_isolates_sessions(manager: MemoryManager):
    manager.configure_bot("bot-a", BotMemoryConfig(scope_policy=ScopePolicy.PER_SESSION))
    session_1 = MemoryScope(bot_id="bot-a", user_id="user-1", session_id="s1")
    session_2 = MemoryScope(bot_id="bot-a", user_id="user-1", session_id="s2")
    await manager.add(session_1, [{"role": "user", "content": "I prefer tea over coffee"}])
    assert await manager.search(session_2, "tea") == []
    assert len(await manager.search(session_1, "tea")) == 1


async def test_disabled_bot_skips_memory(manager: MemoryManager, fake_mem0: FakeMem0):
    manager.set_enabled("bot-a", False)
    scope = MemoryScope(bot_id="bot-a", user_id="user-1")
    result = await manager.add(scope, [{"role": "user", "content": "remember me"}])
    assert result == {"results": []}
    assert fake_mem0.memories == []
    assert await manager.search(scope, "remember") == []


async def test_forget_user_across_all_bots(manager: MemoryManager, fake_mem0: FakeMem0):
    scope_a = MemoryScope(bot_id="bot-a", user_id="user-1")
    scope_b = MemoryScope(bot_id="bot-b", user_id="user-1")
    other_user = MemoryScope(bot_id="bot-a", user_id="user-2")
    await manager.add(scope_a, [{"role": "user", "content": "fact one"}])
    await manager.add(scope_b, [{"role": "user", "content": "fact two"}])
    await manager.add(other_user, [{"role": "user", "content": "fact three"}])

    await manager.forget_user("user-1")

    remaining = [m["user_id"] for m in fake_mem0.memories]
    assert remaining == ["user-2"]


async def test_delete_memory_enforces_bot_ownership(manager: MemoryManager, fake_mem0: FakeMem0):
    scope_a = MemoryScope(bot_id="bot-a", user_id="user-1")
    await manager.add(scope_a, [{"role": "user", "content": "bot a fact"}])
    memory_id = fake_mem0.memories[0]["id"]

    with pytest.raises(PermissionError):
        await manager.delete_memory("bot-b", memory_id)
    await manager.delete_memory("bot-a", memory_id)
    assert fake_mem0.memories == []


def test_token_roundtrip():
    token = issue_memory_token(TOKEN_SECRET, "bot-a")
    assert verify_memory_token(TOKEN_SECRET, token) == "bot-a"


def test_token_rejects_wrong_secret_and_tampering():
    token = issue_memory_token(TOKEN_SECRET, "bot-a")
    with pytest.raises(TokenError):
        verify_memory_token("other-secret", token)
    body, signature = token.split(".", 1)
    with pytest.raises(TokenError):
        verify_memory_token(TOKEN_SECRET, f"{body}x.{signature}")
    with pytest.raises(TokenError):
        verify_memory_token(TOKEN_SECRET, "not-a-token")


def test_token_expiry():
    token = issue_memory_token(TOKEN_SECRET, "bot-a", ttl_seconds=-1)
    with pytest.raises(TokenError):
        verify_memory_token(TOKEN_SECRET, token)


def test_authorize_runtime_scope_mismatch(manager: MemoryManager):
    token = manager.issue_runtime_token("bot-a")
    manager.authorize_runtime(token, "bot-a")
    with pytest.raises(PermissionError):
        manager.authorize_runtime(token, "bot-b")
