"""The single front door for all long-term memory operations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from jadabot.memory.backends import MemoryBackend
from jadabot.memory.scopes import MemoryScope


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    """A memory returned to callers."""

    id: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


class MemoryManager:
    """Scoped access to long-term memory.

    Every operation requires a :class:`MemoryScope` (which requires ``bot_id``),
    guaranteeing cross-bot isolation regardless of backend. This is the only
    component allowed to talk to the memory backend.
    """

    def __init__(self, backend: MemoryBackend) -> None:
        self._backend = backend

    def remember(
        self, text: str, scope: MemoryScope, metadata: dict[str, Any] | None = None
    ) -> str:
        """Store a salient fact. Returns the memory id."""
        if not text or not text.strip():
            raise ValueError("cannot store an empty memory")
        return self._backend.add(text.strip(), scope, metadata)

    def recall(self, query: str, scope: MemoryScope, limit: int = 10) -> list[MemoryRecord]:
        """Return memories relevant to ``query`` within ``scope``."""
        return [self._to_record(r) for r in self._backend.search(query, scope, limit)]

    def list_memories(self, scope: MemoryScope, limit: int = 100) -> list[MemoryRecord]:
        """List memories in ``scope`` (for web-panel administration)."""
        return [self._to_record(r) for r in self._backend.get_all(scope, limit)]

    def forget(self, memory_id: str, scope: MemoryScope) -> None:
        """Delete one memory. The id must belong to ``scope``."""
        owned = {record.id for record in self.list_memories(scope, limit=10_000)}
        if memory_id not in owned:
            raise PermissionError(f"memory {memory_id!r} is not in scope for bot {scope.bot_id!r}")
        self._backend.delete(memory_id)

    def wipe(self, scope: MemoryScope) -> int:
        """Delete every memory in ``scope`` (bot or user deletion). Returns count."""
        return self._backend.delete_all(scope)

    def build_context(self, query: str, scope: MemoryScope, limit: int = 5) -> str:
        """Render relevant memories as a context block for LLM prompt injection."""
        records = self.recall(query, scope, limit)
        if not records:
            return ""
        lines = "\n".join(f"- {record.text}" for record in records)
        return f"Relevant long-term memories:\n{lines}"

    @staticmethod
    def _to_record(raw: dict[str, Any]) -> MemoryRecord:
        return MemoryRecord(
            id=str(raw.get("id", "")),
            text=str(raw.get("memory", raw.get("text", ""))),
            metadata=dict(raw.get("metadata") or {}),
        )
