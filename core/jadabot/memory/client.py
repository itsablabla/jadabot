"""Async REST client for a Mem0 server (self-hosted or cloud-compatible).

Speaks the Mem0 server HTTP API:

- ``POST /memories``   add memories from messages
- ``GET  /memories``   list memories filtered by identifiers
- ``POST /search``     semantic search with identifier filters
- ``DELETE /memories/{id}``  delete one memory
- ``DELETE /memories``       delete all memories matching identifiers

The client is scope-agnostic; scoping is applied by callers (MemoryManager)
so that all isolation decisions live in one place.
"""

from __future__ import annotations

import typing

import httpx
from pydantic import BaseModel


class MemoryRecord(BaseModel):
    """A single memory returned by Mem0."""

    id: str | None = None
    memory: str | None = None
    user_id: str | None = None
    agent_id: str | None = None
    run_id: str | None = None
    score: float | None = None
    metadata: dict[str, typing.Any] | None = None
    created_at: str | None = None
    updated_at: str | None = None


class Mem0ClientError(RuntimeError):
    """Raised when the Mem0 server returns an error."""


class Mem0Client:
    """Thin async wrapper over the Mem0 server REST API."""

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        headers = {}
        if api_key:
            headers["Authorization"] = "Bearer " + api_key
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers=headers,
            timeout=timeout,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def add(
        self,
        messages: list[dict[str, str]],
        identifiers: dict[str, str],
        metadata: dict[str, typing.Any] | None = None,
    ) -> dict[str, typing.Any]:
        """Store new memories extracted from ``messages``."""
        payload: dict[str, typing.Any] = {"messages": messages, **identifiers}
        if metadata:
            payload["metadata"] = metadata
        resp = await self._http.post("/memories", json=payload)
        self._raise_for_status(resp)
        return resp.json()

    async def search(
        self,
        query: str,
        identifiers: dict[str, str],
        top_k: int | None = None,
    ) -> list[MemoryRecord]:
        """Semantic search restricted to ``identifiers``."""
        payload: dict[str, typing.Any] = {"query": query, "filters": identifiers}
        if top_k is not None:
            payload["top_k"] = top_k
        resp = await self._http.post("/search", json=payload)
        self._raise_for_status(resp)
        return self._parse_results(resp.json())

    async def get_all(
        self,
        identifiers: dict[str, str],
        top_k: int | None = None,
    ) -> list[MemoryRecord]:
        """List memories matching ``identifiers``."""
        params: dict[str, typing.Any] = dict(identifiers)
        if top_k is not None:
            params["top_k"] = top_k
        resp = await self._http.get("/memories", params=params)
        self._raise_for_status(resp)
        return self._parse_results(resp.json())

    async def get(self, memory_id: str) -> MemoryRecord | None:
        """Fetch one memory by ID, or ``None`` if it does not exist."""
        resp = await self._http.get(f"/memories/{memory_id}")
        if resp.status_code == 404:
            return None
        self._raise_for_status(resp)
        body = resp.json()
        if not isinstance(body, dict) or body.get("id") is None:
            return None
        return MemoryRecord.model_validate(body)

    async def delete(self, memory_id: str) -> None:
        """Delete one memory by ID."""
        resp = await self._http.delete(f"/memories/{memory_id}")
        self._raise_for_status(resp)

    async def delete_all(self, identifiers: dict[str, str]) -> None:
        """Delete every memory matching ``identifiers``."""
        resp = await self._http.delete("/memories", params=identifiers)
        self._raise_for_status(resp)

    @staticmethod
    def _parse_results(body: typing.Any) -> list[MemoryRecord]:
        results = body.get("results", body) if isinstance(body, dict) else body
        if not isinstance(results, list):
            return []
        return [MemoryRecord.model_validate(item) for item in results if isinstance(item, dict)]

    @staticmethod
    def _raise_for_status(resp: httpx.Response) -> None:
        if resp.status_code >= 400:
            raise Mem0ClientError(f"Mem0 server error {resp.status_code}: {resp.text[:500]}")
