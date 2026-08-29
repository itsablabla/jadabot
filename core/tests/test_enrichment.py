"""Enrichment tests: injection, timeout skip, fire-and-forget writes."""

from __future__ import annotations

import asyncio

from jadabot.memory.client import MemoryRecord
from jadabot.memory.enrichment import MEMORY_CONTEXT_HEADER, MemoryEnricher
from jadabot.memory.manager import MemoryManager
from jadabot.memory.scopes import MemoryScope


async def test_memory_context_injection(manager: MemoryManager):
    scope = MemoryScope(bot_id="bot-a", user_id="user-1")
    await manager.add(scope, [{"role": "user", "content": "my dog is named Rex"}])
    enricher = MemoryEnricher(manager)

    context = await enricher.build_memory_context(scope, "what is my dog named Rex called")
    assert context is not None
    assert context.startswith(MEMORY_CONTEXT_HEADER)
    assert "Rex" in context


async def test_no_context_when_no_matches(manager: MemoryManager):
    scope = MemoryScope(bot_id="bot-a", user_id="user-1")
    enricher = MemoryEnricher(manager)
    assert await enricher.build_memory_context(scope, "anything") is None


async def test_search_timeout_gracefully_skips(manager: MemoryManager, monkeypatch):
    async def slow_search(*args, **kwargs):
        await asyncio.sleep(10)
        return [MemoryRecord(memory="too late")]

    monkeypatch.setattr(manager, "search", slow_search)
    enricher = MemoryEnricher(manager, search_timeout_seconds=0.05)
    scope = MemoryScope(bot_id="bot-a", user_id="user-1")
    assert await enricher.build_memory_context(scope, "query") is None


async def test_search_error_gracefully_skips(manager: MemoryManager, monkeypatch):
    async def broken_search(*args, **kwargs):
        raise RuntimeError("mem0 is down")

    monkeypatch.setattr(manager, "search", broken_search)
    enricher = MemoryEnricher(manager)
    scope = MemoryScope(bot_id="bot-a", user_id="user-1")
    assert await enricher.build_memory_context(scope, "query") is None


async def test_record_exchange_is_fire_and_forget(manager: MemoryManager, fake_mem0):
    enricher = MemoryEnricher(manager)
    scope = MemoryScope(bot_id="bot-a", user_id="user-1")
    enricher.record_exchange(scope, "I live in Lisbon", "Noted!")
    assert fake_mem0.memories == []  # not yet written; call did not block
    await enricher.drain()
    assert len(fake_mem0.memories) == 2
    assert all(m["agent_id"] == "bot-a" for m in fake_mem0.memories)


async def test_record_exchange_skipped_when_disabled(manager: MemoryManager, fake_mem0):
    manager.set_enabled("bot-a", False)
    enricher = MemoryEnricher(manager)
    enricher.record_exchange(MemoryScope(bot_id="bot-a", user_id="u"), "hi", "hello")
    await enricher.drain()
    assert fake_mem0.memories == []
