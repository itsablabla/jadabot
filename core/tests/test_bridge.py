"""Bridge tests: message forwarding, streaming relay, confirmation gate, memory."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from jadabot.bridge import BridgeStage, InboundMessage, RuntimeEvent
from jadabot.memory import MemoryManager, MemoryScope
from jadabot.runtimes.registry import RuntimeInfo, RuntimeRegistry


class FakeRuntimeClient:
    """Stands in for RuntimeClient; replays scripted events."""

    def __init__(self, endpoint: str) -> None:
        self.endpoint = endpoint
        self.tasks: list[dict] = []
        self.confirmations: list[tuple[str, bool]] = []
        self.script: list[RuntimeEvent] = []

    async def run_task(
        self,
        message: str,
        session_id: str,
        user_id: str | None = None,
        memory_context: str | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        self.tasks.append(
            {
                "message": message,
                "session_id": session_id,
                "user_id": user_id,
                "memory_context": memory_context,
            }
        )
        for event in self.script:
            yield event

    async def resolve_confirmation(self, confirmation_id: str, approved: bool) -> None:
        self.confirmations.append((confirmation_id, approved))

    async def aclose(self) -> None:
        pass


@pytest.fixture
def registry() -> RuntimeRegistry:
    reg = RuntimeRegistry()
    reg.register(RuntimeInfo(bot_id="bot-a", endpoint="http://127.0.0.1:7001", workdir="/tmp/a"))
    reg.register(RuntimeInfo(bot_id="bot-b", endpoint="http://127.0.0.1:7002", workdir="/tmp/b"))
    return reg


@pytest.fixture
def clients() -> dict[str, FakeRuntimeClient]:
    return {}


@pytest.fixture
def stage(
    registry: RuntimeRegistry,
    memory_manager: MemoryManager,
    clients: dict[str, FakeRuntimeClient],
) -> BridgeStage:
    def factory(endpoint: str) -> FakeRuntimeClient:
        client = FakeRuntimeClient(endpoint)
        clients[endpoint] = client
        return client

    return BridgeStage(registry, memory_manager, client_factory=factory)


def _script(client: FakeRuntimeClient) -> None:
    client.script = [
        RuntimeEvent(type="text", data={"text": "Hello "}),
        RuntimeEvent(type="tool", data={"description": "searching the web"}),
        RuntimeEvent(type="text", data={"text": "world"}),
        RuntimeEvent(type="done"),
    ]


async def test_routes_message_to_correct_runtime(
    stage: BridgeStage, clients: dict[str, FakeRuntimeClient]
) -> None:
    stage._client_for("bot-a")  # noqa: SLF001 - create client to script it
    client = clients["http://127.0.0.1:7001"]
    _script(client)
    message = InboundMessage(bot_id="bot-a", user_id="u1", session_id="s1", text="hi")
    chunks = [chunk async for chunk in stage.process(message)]

    assert client.tasks[-1]["message"] == "hi"
    assert client.tasks[-1]["session_id"] == "s1"
    assert "http://127.0.0.1:7002" not in clients  # bot-b runtime untouched
    texts = [c.text for c in chunks if c.kind == "text"]
    assert texts == ["Hello ", "world"]
    tools = [c for c in chunks if c.kind == "tool_progress"]
    assert tools and tools[0].text == "searching the web"


async def test_memory_recall_injection_and_store(
    stage: BridgeStage,
    clients: dict[str, FakeRuntimeClient],
    memory_manager: MemoryManager,
) -> None:
    scope = MemoryScope(bot_id="bot-a", user_id="u1", session_id="s1")
    memory_manager.remember("The user prefers formal greetings", scope)

    message = InboundMessage(
        bot_id="bot-a", user_id="u1", session_id="s1", text="greetings please"
    )
    # Prime the client with a scripted reply.
    stage._client_for("bot-a")  # noqa: SLF001 - create client to script it
    client = clients["http://127.0.0.1:7001"]
    client.script = [
        RuntimeEvent(type="text", data={"text": "Good day."}),
        RuntimeEvent(type="done"),
    ]
    [chunk async for chunk in stage.process(message)]

    assert "formal greetings" in (client.tasks[-1]["memory_context"] or "")
    stored = memory_manager.list_memories(scope)
    assert any("Good day." in record.text for record in stored)


async def test_confirmation_gate_round_trip(
    stage: BridgeStage, clients: dict[str, FakeRuntimeClient]
) -> None:
    stage._client_for("bot-a")  # noqa: SLF001
    client = clients["http://127.0.0.1:7001"]
    client.script = [
        RuntimeEvent(
            type="confirmation",
            data={"confirmation_id": "c-1", "prompt": "Run `rm -rf build`?"},
        ),
        RuntimeEvent(type="done"),
    ]
    message = InboundMessage(bot_id="bot-a", user_id="u1", session_id="s1", text="clean up")
    chunks = [chunk async for chunk in stage.process(message)]

    requests = [c for c in chunks if c.kind == "confirmation_request"]
    assert requests and requests[0].confirmation_id == "c-1"
    await stage.resolve_confirmation("bot-a", "c-1", approved=True)
    assert client.confirmations == [("c-1", True)]


async def test_unknown_bot_raises(stage: BridgeStage) -> None:
    message = InboundMessage(bot_id="bot-x", user_id="u1", session_id="s1", text="hi")
    with pytest.raises(KeyError):
        async for _ in stage.process(message):
            pass
