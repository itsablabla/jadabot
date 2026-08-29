"""The LangBot pipeline stage.

For each inbound platform message, the stage:

1. resolves the bot's runtime endpoint from the :class:`RuntimeRegistry`,
2. recalls relevant memories via :class:`MemoryManager` and injects them,
3. forwards the message to that bot's Pipali runtime and relays streamed
   output/tool-progress/confirmation events back to the chat platform,
4. asynchronously stores the exchange back into memory after completion.

This module is deliberately framework-light: LangBot's plugin API wraps
:class:`BridgeStage` in a thin adapter (see ``deploy/langbot-plugin``), which
keeps the bridge unit-testable without a LangBot installation.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass

import httpx

from jadabot.bridge.client import RuntimeClient
from jadabot.memory import MemoryManager, MemoryScope
from jadabot.runtimes.registry import RuntimeRegistry

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class InboundMessage:
    """A platform message routed to a bot by a LangBot pipeline."""

    bot_id: str
    user_id: str
    session_id: str
    text: str


@dataclass(frozen=True, slots=True)
class OutboundChunk:
    """A chunk relayed back to the chat platform.

    ``kind`` is ``text``, ``tool_progress`` or ``confirmation_request``.
    """

    kind: str
    text: str
    confirmation_id: str | None = None


class BridgeStage:
    """Forwards messages from LangBot pipelines to per-bot Pipali runtimes."""

    def __init__(
        self,
        registry: RuntimeRegistry,
        memory: MemoryManager,
        client_factory: Callable[[str], RuntimeClient] | None = None,
        memory_recall_limit: int = 5,
    ) -> None:
        self._registry = registry
        self._memory = memory
        self._client_factory = client_factory or RuntimeClient
        self._clients: dict[str, RuntimeClient] = {}
        self._recall_limit = memory_recall_limit

    def _client_for(self, bot_id: str) -> RuntimeClient:
        endpoint = self._registry.endpoint_for(bot_id)
        client = self._clients.get(bot_id)
        if client is None or client.endpoint.rstrip("/") != endpoint.rstrip("/"):
            client = self._client_factory(endpoint)
            self._clients[bot_id] = client
        return client

    async def process(self, message: InboundMessage) -> AsyncIterator[OutboundChunk]:
        """Handle one inbound message; yield chunks to send back to the chat."""
        scope = MemoryScope(
            bot_id=message.bot_id,
            user_id=message.user_id,
            session_id=message.session_id,
        )
        memory_context = self._memory.build_context(
            message.text, scope, limit=self._recall_limit
        )
        client = self._client_for(message.bot_id)
        reply_parts: list[str] = []
        async for event in client.run_task(
            message.text,
            session_id=message.session_id,
            user_id=message.user_id,
            memory_context=memory_context or None,
        ):
            if event.type == "text":
                chunk = str(event.data.get("text", ""))
                if chunk:
                    reply_parts.append(chunk)
                    yield OutboundChunk(kind="text", text=chunk)
            elif event.type == "tool":
                yield OutboundChunk(
                    kind="tool_progress",
                    text=str(event.data.get("description", "running a tool")),
                )
            elif event.type == "confirmation":
                yield OutboundChunk(
                    kind="confirmation_request",
                    text=str(event.data.get("prompt", "The agent needs your approval.")),
                    confirmation_id=str(event.data.get("confirmation_id", "")),
                )
            elif event.type == "done":
                break
        self._store_exchange(message, "".join(reply_parts), scope)

    async def resolve_confirmation(
        self, bot_id: str, confirmation_id: str, approved: bool
    ) -> None:
        """Relay the bot owner's approval decision to the runtime."""
        await self._client_for(bot_id).resolve_confirmation(confirmation_id, approved)

    def _store_exchange(self, message: InboundMessage, reply: str, scope: MemoryScope) -> None:
        if not reply:
            return
        try:
            self._memory.remember(
                f"User said: {message.text}\nAssistant replied: {reply}",
                scope,
                metadata={"source": "bridge"},
            )
        except Exception:  # noqa: BLE001 - memory writes must never break replies
            logger.exception("failed to store exchange for bot %s", message.bot_id)

    async def aclose(self) -> None:
        for client in self._clients.values():
            try:
                await client.aclose()
            except httpx.HTTPError:  # pragma: no cover - best-effort cleanup
                pass
        self._clients.clear()
