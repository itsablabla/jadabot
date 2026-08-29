"""Pluggable memory backends.

:class:`Mem0Backend` is the production backend (requires the ``mem0ai``
package, installed via the ``jadabot[mem0]`` extra). :class:`InMemoryBackend`
is a dependency-free backend used for tests and local development.
"""

from __future__ import annotations

import itertools
import time
from abc import ABC, abstractmethod
from typing import Any

from jadabot.memory.scopes import MemoryScope


class MemoryBackend(ABC):
    """Storage interface used by :class:`jadabot.memory.MemoryManager`."""

    @abstractmethod
    def add(self, text: str, scope: MemoryScope, metadata: dict[str, Any] | None = None) -> str:
        """Store a memory, returning its id."""

    @abstractmethod
    def search(self, query: str, scope: MemoryScope, limit: int = 10) -> list[dict[str, Any]]:
        """Return memories relevant to ``query`` within ``scope``."""

    @abstractmethod
    def get_all(self, scope: MemoryScope, limit: int = 100) -> list[dict[str, Any]]:
        """Return all memories within ``scope``."""

    @abstractmethod
    def delete(self, memory_id: str) -> None:
        """Delete a single memory by id."""

    @abstractmethod
    def delete_all(self, scope: MemoryScope) -> int:
        """Delete all memories within ``scope``; return the number deleted."""


class Mem0Backend(MemoryBackend):
    """Backend that delegates to a self-hosted Mem0 instance.

    ``config`` is passed to ``mem0.Memory.from_config``; point its ``llm`` and
    ``embedder`` sections at the jadabot LLM Manager gateway so all model
    traffic stays centrally managed.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        try:
            from mem0 import Memory
        except ImportError as exc:  # pragma: no cover - depends on extra
            raise RuntimeError(
                "Mem0Backend requires the mem0ai package; install jadabot[mem0]"
            ) from exc
        self._memory = Memory.from_config(config) if config else Memory()

    def add(self, text: str, scope: MemoryScope, metadata: dict[str, Any] | None = None) -> str:
        result = self._memory.add(text, metadata=metadata or {}, **scope.to_mem0_ids())
        entries = result.get("results", []) if isinstance(result, dict) else []
        return str(entries[0]["id"]) if entries else ""

    def search(self, query: str, scope: MemoryScope, limit: int = 10) -> list[dict[str, Any]]:
        result = self._memory.search(query, limit=limit, **scope.to_mem0_ids())
        return list(result.get("results", [])) if isinstance(result, dict) else list(result)

    def get_all(self, scope: MemoryScope, limit: int = 100) -> list[dict[str, Any]]:
        result = self._memory.get_all(limit=limit, **scope.to_mem0_ids())
        return list(result.get("results", [])) if isinstance(result, dict) else list(result)

    def delete(self, memory_id: str) -> None:
        self._memory.delete(memory_id)

    def delete_all(self, scope: MemoryScope) -> int:
        existing = self.get_all(scope, limit=10_000)
        self._memory.delete_all(**scope.to_mem0_ids())
        return len(existing)


class InMemoryBackend(MemoryBackend):
    """Simple substring-scoring backend for tests and local development."""

    def __init__(self) -> None:
        self._records: dict[str, dict[str, Any]] = {}
        self._ids = itertools.count(1)

    @staticmethod
    def _scope_key(scope: MemoryScope) -> tuple[str, str | None, str | None]:
        return (scope.bot_id, scope.user_id, scope.session_id)

    def _in_scope(self, record: dict[str, Any], scope: MemoryScope) -> bool:
        if record["bot_id"] != scope.bot_id:
            return False
        if scope.user_id is not None and record["user_id"] != scope.user_id:
            return False
        if scope.session_id is not None and record["session_id"] != scope.session_id:
            return False
        return True

    def add(self, text: str, scope: MemoryScope, metadata: dict[str, Any] | None = None) -> str:
        memory_id = f"mem-{next(self._ids)}"
        self._records[memory_id] = {
            "id": memory_id,
            "memory": text,
            "metadata": metadata or {},
            "bot_id": scope.bot_id,
            "user_id": scope.user_id,
            "session_id": scope.session_id,
            "created_at": time.time(),
        }
        return memory_id

    def search(self, query: str, scope: MemoryScope, limit: int = 10) -> list[dict[str, Any]]:
        words = [w for w in query.lower().split() if w]
        scored: list[tuple[int, dict[str, Any]]] = []
        for record in self._records.values():
            if not self._in_scope(record, scope):
                continue
            text = record["memory"].lower()
            score = sum(1 for w in words if w in text)
            if score:
                scored.append((score, record))
        scored.sort(key=lambda item: (-item[0], item[1]["created_at"]))
        return [dict(record) for _, record in scored[:limit]]

    def get_all(self, scope: MemoryScope, limit: int = 100) -> list[dict[str, Any]]:
        records = [dict(r) for r in self._records.values() if self._in_scope(r, scope)]
        records.sort(key=lambda r: r["created_at"])
        return records[:limit]

    def delete(self, memory_id: str) -> None:
        self._records.pop(memory_id, None)

    def delete_all(self, scope: MemoryScope) -> int:
        doomed = [mid for mid, r in self._records.items() if self._in_scope(r, scope)]
        for mid in doomed:
            del self._records[mid]
        return len(doomed)
