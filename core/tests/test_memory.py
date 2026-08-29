"""MemoryManager scoping tests — especially cross-bot isolation."""

from __future__ import annotations

import pytest

from jadabot.memory import MemoryManager, MemoryScope


def test_scope_requires_bot_id() -> None:
    with pytest.raises(ValueError):
        MemoryScope(bot_id="")
    with pytest.raises(ValueError):
        MemoryScope(bot_id="   ")


def test_scope_maps_to_mem0_ids() -> None:
    scope = MemoryScope(bot_id="bot-a", user_id="user-1", session_id="sess-9")
    assert scope.to_mem0_ids() == {
        "agent_id": "bot-a",
        "user_id": "user-1",
        "run_id": "sess-9",
    }
    assert MemoryScope(bot_id="bot-a").to_mem0_ids() == {"agent_id": "bot-a"}


def test_remember_and_recall(memory_manager: MemoryManager) -> None:
    scope = MemoryScope(bot_id="bot-a", user_id="user-1")
    memory_manager.remember("The user prefers dark mode", scope)
    memory_manager.remember("The user lives in Lisbon", scope)
    records = memory_manager.recall("where does the user live? Lisbon", scope)
    assert records
    assert records[0].text == "The user lives in Lisbon"


def test_cross_bot_isolation(memory_manager: MemoryManager) -> None:
    scope_a = MemoryScope(bot_id="bot-a", user_id="user-1")
    scope_b = MemoryScope(bot_id="bot-b", user_id="user-1")
    memory_manager.remember("secret fact for bot-a", scope_a)

    assert memory_manager.recall("secret fact", scope_b) == []
    assert memory_manager.list_memories(scope_b) == []
    assert len(memory_manager.list_memories(scope_a)) == 1


def test_user_isolation_within_bot(memory_manager: MemoryManager) -> None:
    scope_u1 = MemoryScope(bot_id="bot-a", user_id="user-1")
    scope_u2 = MemoryScope(bot_id="bot-a", user_id="user-2")
    memory_manager.remember("user-1 likes tea", scope_u1)
    assert memory_manager.recall("likes tea", scope_u2) == []


def test_forget_denies_out_of_scope_ids(memory_manager: MemoryManager) -> None:
    scope_a = MemoryScope(bot_id="bot-a")
    scope_b = MemoryScope(bot_id="bot-b")
    memory_id = memory_manager.remember("bot-a memory", scope_a)
    with pytest.raises(PermissionError):
        memory_manager.forget(memory_id, scope_b)
    memory_manager.forget(memory_id, scope_a)
    assert memory_manager.list_memories(scope_a) == []


def test_wipe_only_wipes_scope(memory_manager: MemoryManager) -> None:
    scope_a = MemoryScope(bot_id="bot-a")
    scope_b = MemoryScope(bot_id="bot-b")
    memory_manager.remember("a1", scope_a)
    memory_manager.remember("a2", scope_a)
    memory_manager.remember("b1", scope_b)
    assert memory_manager.wipe(scope_a) == 2
    assert memory_manager.list_memories(scope_a) == []
    assert len(memory_manager.list_memories(scope_b)) == 1


def test_empty_memory_rejected(memory_manager: MemoryManager) -> None:
    with pytest.raises(ValueError):
        memory_manager.remember("   ", MemoryScope(bot_id="bot-a"))


def test_build_context(memory_manager: MemoryManager) -> None:
    scope = MemoryScope(bot_id="bot-a")
    assert memory_manager.build_context("anything", scope) == ""
    memory_manager.remember("The user is a python developer", scope)
    context = memory_manager.build_context("python", scope)
    assert "Relevant long-term memories:" in context
    assert "python developer" in context
