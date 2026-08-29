"""HTTP/SSE client for a single bot's Pipali runtime.

The runtime contract (implemented by ``runtime-tools``):

- ``GET  /healthz``          -> ``{"status": "ok"}``
- ``POST /v1/task``          -> SSE stream of :class:`RuntimeEvent` items
- ``POST /v1/confirmation``  -> resolve a pending confirmation gate
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass(frozen=True, slots=True)
class RuntimeEvent:
    """One streamed event from the runtime's director loop.

    ``type`` is one of ``text`` (assistant output chunk), ``tool`` (tool
    progress), ``confirmation`` (approval required), or ``done``.
    """

    type: str
    data: dict[str, Any] = field(default_factory=dict)


class RuntimeClient:
    """Talks to one bot's runtime endpoint."""

    def __init__(self, endpoint: str, http_client: httpx.AsyncClient | None = None) -> None:
        self.endpoint = endpoint.rstrip("/")
        self._client = http_client or httpx.AsyncClient(timeout=None)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def run_task(
        self,
        message: str,
        session_id: str,
        user_id: str | None = None,
        memory_context: str | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        """Send a chat message to the runtime; yield streamed agent events."""
        payload: dict[str, Any] = {"message": message, "session_id": session_id}
        if user_id:
            payload["user_id"] = user_id
        if memory_context:
            payload["memory_context"] = memory_context
        async with self._client.stream(
            "POST", f"{self.endpoint}/v1/task", json=payload
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                raw = line[len("data:") :].strip()
                if not raw:
                    continue
                event = json.loads(raw)
                yield RuntimeEvent(type=event.get("type", "text"), data=event.get("data") or {})
                if event.get("type") == "done":
                    return

    async def resolve_confirmation(self, confirmation_id: str, approved: bool) -> None:
        """Answer a pending confirmation-gate prompt."""
        response = await self._client.post(
            f"{self.endpoint}/v1/confirmation",
            json={"confirmation_id": confirmation_id, "approved": approved},
        )
        response.raise_for_status()
