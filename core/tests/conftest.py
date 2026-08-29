"""Shared test fixtures: an in-memory fake Mem0 server behind httpx."""

from __future__ import annotations

import itertools
import json
import typing

import httpx
import pytest

from jadabot.memory.client import Mem0Client
from jadabot.memory.manager import MemoryManager

TOKEN_SECRET = "test-token-secret"
ADMIN_KEY = "test-admin-key"


class FakeMem0:
    """Minimal in-memory stand-in for the Mem0 server REST API."""

    def __init__(self):
        self.memories: list[dict[str, typing.Any]] = []
        self._ids = itertools.count(1)
        self.search_calls: list[dict[str, typing.Any]] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _matches(self, memory: dict[str, typing.Any], filters: dict[str, str]) -> bool:
        return all(memory.get(key) == value for key, value in filters.items())

    def _handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method
        if method == "POST" and path == "/memories":
            body = json.loads(request.content)
            identifiers = {
                k: body[k] for k in ("user_id", "agent_id", "run_id") if body.get(k)
            }
            results = []
            for message in body["messages"]:
                memory = {
                    "id": f"mem-{next(self._ids)}",
                    "memory": message["content"],
                    "metadata": body.get("metadata"),
                    **identifiers,
                }
                self.memories.append(memory)
                results.append(memory)
            return httpx.Response(200, json={"results": results})
        if method == "POST" and path == "/search":
            body = json.loads(request.content)
            self.search_calls.append(body)
            filters = body.get("filters", {})
            query_tokens = {t for t in body.get("query", "").lower().split() if len(t) > 2}
            matches = [
                m for m in self.memories
                if self._matches(m, filters)
                and query_tokens & set((m["memory"] or "").lower().split())
            ]
            top_k = body.get("top_k")
            if top_k:
                matches = matches[:top_k]
            return httpx.Response(200, json={"results": matches})
        if method == "GET" and path == "/memories":
            filters = {
                k: v for k, v in request.url.params.items()
                if k in ("user_id", "agent_id", "run_id")
            }
            matches = [m for m in self.memories if self._matches(m, filters)]
            return httpx.Response(200, json={"results": matches})
        if method == "DELETE" and path.startswith("/memories/"):
            memory_id = path.removeprefix("/memories/")
            self.memories = [m for m in self.memories if m["id"] != memory_id]
            return httpx.Response(200, json={"message": "deleted"})
        if method == "DELETE" and path == "/memories":
            filters = {
                k: v for k, v in request.url.params.items()
                if k in ("user_id", "agent_id", "run_id")
            }
            self.memories = [m for m in self.memories if not self._matches(m, filters)]
            return httpx.Response(200, json={"message": "deleted"})
        return httpx.Response(404, json={"detail": f"unhandled {method} {path}"})


@pytest.fixture
def fake_mem0() -> FakeMem0:
    return FakeMem0()


@pytest.fixture
def mem0_client(fake_mem0: FakeMem0) -> Mem0Client:
    return Mem0Client(base_url="http://mem0.test", transport=fake_mem0.transport())


@pytest.fixture
def manager(mem0_client: Mem0Client) -> MemoryManager:
    return MemoryManager(mem0_client, token_secret=TOKEN_SECRET)
