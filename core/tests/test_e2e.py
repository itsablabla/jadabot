"""End-to-end test: bridge -> runtime contract (SSE) -> LLM gateway -> memory.

Simulates the full message path with an in-process ASGI runtime implementing
the runtime HTTP contract, backed by the real LLMGateway (mock provider) and
the real MemoryManager.
"""

from __future__ import annotations

import json

import httpx

from jadabot.bridge import BridgeStage, InboundMessage, RuntimeClient
from jadabot.llm import (
    BotModelAssignment,
    BotTokenStore,
    LLMGateway,
    ModelRegistry,
    Provider,
    UsageLedger,
)
from jadabot.memory import InMemoryBackend, MemoryManager, MemoryScope
from jadabot.runtimes.registry import RuntimeInfo, RuntimeRegistry


def _provider_handler(request: httpx.Request) -> httpx.Response:
    payload = json.loads(request.content)
    user_text = payload["messages"][-1]["content"]
    return httpx.Response(
        200,
        json={
            "id": "cmpl-e2e",
            "model": payload["model"],
            "choices": [{"message": {"role": "assistant", "content": f"echo: {user_text}"}}],
            "usage": {"prompt_tokens": 7, "completion_tokens": 3},
        },
    )


def _make_runtime_asgi(gateway: LLMGateway, bot_token: str):
    """A minimal ASGI app implementing the runtime contract, like runtime-tools."""

    async def app(scope, receive, send):
        assert scope["type"] == "http"
        if scope["method"] == "GET" and scope["path"] == "/healthz":
            await _respond_json(send, {"status": "ok"})
            return
        if scope["method"] == "POST" and scope["path"] == "/v1/task":
            body = b""
            while True:
                event = await receive()
                body += event.get("body", b"")
                if not event.get("more_body"):
                    break
            task = json.loads(body)
            # The runtime calls the central gateway with its scoped bot token.
            bot_id = gateway.authenticate("Bearer " + bot_token)
            assert bot_id is not None
            messages = []
            if task.get("memory_context"):
                messages.append({"role": "system", "content": task["memory_context"]})
            messages.append({"role": "user", "content": task["message"]})
            completion = await gateway.chat_completion(bot_id, {"messages": messages})
            text = completion["choices"][0]["message"]["content"]
            events = [
                {"type": "text", "data": {"text": text}},
                {"type": "done", "data": {}},
            ]
            sse = "".join(f"data: {json.dumps(e)}\n\n" for e in events)
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", b"text/event-stream")],
                }
            )
            await send({"type": "http.response.body", "body": sse.encode()})
            return
        await _respond_json(send, {"error": "not found"}, status=404)

    async def _respond_json(send, body: dict, status: int = 200) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": json.dumps(body).encode()})

    return app


async def test_full_message_path() -> None:
    # Central LLM gateway with a mock provider.
    registry = ModelRegistry()
    registry.add_provider(
        Provider(name="mock", base_url="http://provider.test/v1", api_key="sk-mock", models=("m1",))
    )
    registry.assign(BotModelAssignment(bot_id="bot-a", model="m1"))
    tokens = BotTokenStore()
    ledger = UsageLedger()
    gateway = LLMGateway(
        registry,
        tokens,
        ledger,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(_provider_handler)),
    )
    bot_token = tokens.issue("bot-a")

    # Per-bot runtime implementing the runtime contract, served in-process.
    runtime_app = _make_runtime_asgi(gateway, bot_token)
    runtime_transport = httpx.ASGITransport(app=runtime_app)

    # Bridge with memory and the runtime registry.
    memory = MemoryManager(InMemoryBackend())
    scope = MemoryScope(bot_id="bot-a", user_id="u1", session_id="s1")
    memory.remember("The user's name is Ada", scope)

    runtime_registry = RuntimeRegistry()
    runtime_registry.register(
        RuntimeInfo(bot_id="bot-a", endpoint="http://runtime.test", workdir="/tmp/bot-a")
    )
    stage = BridgeStage(
        runtime_registry,
        memory,
        client_factory=lambda endpoint: RuntimeClient(
            endpoint, http_client=httpx.AsyncClient(transport=runtime_transport, timeout=None)
        ),
    )

    message = InboundMessage(bot_id="bot-a", user_id="u1", session_id="s1", text="hello Ada")
    chunks = [chunk async for chunk in stage.process(message)]

    # The reply flowed platform -> bridge -> runtime -> gateway -> provider and back.
    texts = [c.text for c in chunks if c.kind == "text"]
    assert texts == ["echo: hello Ada"]

    # Usage was recorded against the bot at the central gateway.
    usage = ledger.usage_for("bot-a")
    assert usage.requests == 1
    assert usage.total_tokens == 10

    # The memory round-trip: the exchange was stored in the bot's scope only.
    stored = memory.list_memories(scope)
    assert any("echo: hello Ada" in record.text for record in stored)
    assert memory.list_memories(MemoryScope(bot_id="bot-b")) == []

    await stage.aclose()
    await gateway.aclose()
