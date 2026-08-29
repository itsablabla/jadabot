"""Memory enrichment for the Pipali RequestRunner message flow.

- Before dispatching a query to a bot's Pipali runtime, search Mem0 for
  relevant memories with a hard timeout; on timeout or error the search is
  skipped gracefully so memory never blocks a reply.
- After the runtime responds, the exchange is written back to Mem0 as a
  fire-and-forget task so extraction latency never delays the response.
"""

from __future__ import annotations

import asyncio
import logging
import typing

from .manager import MemoryManager
from .scopes import MemoryScope

logger = logging.getLogger(__name__)

DEFAULT_SEARCH_TIMEOUT_SECONDS = 2.0

MEMORY_CONTEXT_HEADER = "Relevant long-term memories about this user:"


class MemoryEnricher:
    """Wires MemoryManager into the runner's request/response cycle."""

    def __init__(
        self,
        manager: MemoryManager,
        search_timeout_seconds: float = DEFAULT_SEARCH_TIMEOUT_SECONDS,
    ):
        self._manager = manager
        self._search_timeout = search_timeout_seconds
        self._pending_writes: set[asyncio.Task[typing.Any]] = set()

    async def build_memory_context(self, scope: MemoryScope, query_text: str) -> str | None:
        """Return a context block of relevant memories, or ``None``.

        Applies a hard timeout with graceful skip so time-to-first-token is
        bounded even when the memory backend is slow or down.
        """
        if not self._manager.is_enabled(scope.bot_id):
            return None
        try:
            records = await asyncio.wait_for(
                self._manager.search(scope, query_text),
                timeout=self._search_timeout,
            )
        except asyncio.TimeoutError:
            logger.warning("memory search timed out for bot %s; skipping", scope.bot_id)
            return None
        except Exception:
            logger.exception("memory search failed for bot %s; skipping", scope.bot_id)
            return None
        facts = [record.memory for record in records if record.memory]
        if not facts:
            return None
        lines = "\n".join(f"- {fact}" for fact in facts)
        return f"{MEMORY_CONTEXT_HEADER}\n{lines}"

    def record_exchange(self, scope: MemoryScope, user_message: str, assistant_message: str) -> None:
        """Fire-and-forget write of one exchange to Mem0."""
        if not self._manager.is_enabled(scope.bot_id):
            return
        task = asyncio.get_running_loop().create_task(
            self._record_exchange(scope, user_message, assistant_message)
        )
        self._pending_writes.add(task)
        task.add_done_callback(self._pending_writes.discard)

    async def _record_exchange(self, scope: MemoryScope, user_message: str, assistant_message: str) -> None:
        try:
            await self._manager.add(
                scope,
                [
                    {"role": "user", "content": user_message},
                    {"role": "assistant", "content": assistant_message},
                ],
            )
        except Exception:
            logger.exception("memory add failed for bot %s", scope.bot_id)

    async def drain(self) -> None:
        """Wait for in-flight memory writes (used by tests and shutdown)."""
        if self._pending_writes:
            await asyncio.gather(*tuple(self._pending_writes), return_exceptions=True)
