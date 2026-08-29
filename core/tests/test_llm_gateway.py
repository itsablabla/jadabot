"""LLM gateway tests: auth, routing/failover, quotas, usage accounting."""

from __future__ import annotations

import json

import httpx
import pytest

from jadabot.llm import (
    BotModelAssignment,
    BotTokenStore,
    GatewayError,
    LLMGateway,
    ModelRegistry,
    Provider,
    QuotaExceeded,
    QuotaPolicy,
    UsageLedger,
)
from jadabot.llm.app import create_app


def _completion_body(model: str) -> dict:
    return {
        "id": "cmpl-1",
        "model": model,
        "choices": [{"message": {"role": "assistant", "content": f"hello from {model}"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }


def _make_gateway(
    handler, providers: list[Provider], default_model: str | None = None
) -> tuple[LLMGateway, BotTokenStore, UsageLedger, ModelRegistry]:
    registry = ModelRegistry(default_model=default_model)
    for provider in providers:
        registry.add_provider(provider)
    tokens = BotTokenStore()
    ledger = UsageLedger()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return LLMGateway(registry, tokens, ledger, http_client=client), tokens, ledger, registry


async def test_routes_to_assigned_model_and_records_usage() -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen.append((request.headers["Authorization"], payload["model"]))
        return httpx.Response(200, json=_completion_body(payload["model"]))

    provider = Provider(name="acme", base_url="http://acme.test/v1", api_key="sk-acme", models=("gpt-x",))
    gateway, tokens, ledger, registry = _make_gateway(handler, [provider])
    registry.assign(BotModelAssignment(bot_id="bot-a", model="gpt-x"))
    body = await gateway.chat_completion("bot-a", {"messages": []})

    assert body["choices"][0]["message"]["content"] == "hello from gpt-x"
    assert seen == [("Bearer " + "sk-acme", "gpt-x")]
    usage = ledger.usage_for("bot-a")
    assert usage.requests == 1
    assert usage.total_tokens == 15
    await gateway.aclose()


async def test_failover_to_fallback_model() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        if payload["model"] == "primary":
            return httpx.Response(500)
        return httpx.Response(200, json=_completion_body(payload["model"]))

    provider = Provider(name="acme", base_url="http://acme.test/v1", api_key="k", models=("primary", "backup"))
    gateway, _, _, registry = _make_gateway(handler, [provider])
    registry.assign(
        BotModelAssignment(bot_id="bot-a", model="primary", fallback_models=("backup",))
    )
    body = await gateway.chat_completion("bot-a", {"messages": []})
    assert body["model"] == "backup"
    await gateway.aclose()


async def test_failover_across_providers_for_same_model() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "down.test":
            raise httpx.ConnectError("down")
        return httpx.Response(200, json=_completion_body("m1"))

    providers = [
        Provider(name="down", base_url="http://down.test/v1", api_key="k1", models=("m1",)),
        Provider(name="up", base_url="http://up.test/v1", api_key="k2", models=("m1",)),
    ]
    gateway, _, _, registry = _make_gateway(handler, providers)
    registry.assign(BotModelAssignment(bot_id="bot-a", model="m1"))
    body = await gateway.chat_completion("bot-a", {"messages": []})
    assert body["model"] == "m1"
    await gateway.aclose()


async def test_all_providers_failing_raises_gateway_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    provider = Provider(name="acme", base_url="http://acme.test/v1", api_key="k", models=("m1",))
    gateway, _, _, registry = _make_gateway(handler, [provider])
    registry.assign(BotModelAssignment(bot_id="bot-a", model="m1"))
    with pytest.raises(GatewayError):
        await gateway.chat_completion("bot-a", {"messages": []})
    await gateway.aclose()


async def test_disallowed_model_override_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        return httpx.Response(200, json=_completion_body("m1"))

    provider = Provider(name="acme", base_url="http://acme.test/v1", api_key="k")
    gateway, _, _, registry = _make_gateway(handler, [provider])
    registry.assign(
        BotModelAssignment(bot_id="bot-a", model="m1", allowed_models=frozenset({"m1"}))
    )
    with pytest.raises(PermissionError):
        await gateway.chat_completion("bot-a", {"messages": [], "model": "forbidden"})
    await gateway.aclose()


async def test_quota_enforcement() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_completion_body("m1"))

    provider = Provider(name="acme", base_url="http://acme.test/v1", api_key="k", models=("m1",))
    gateway, _, ledger, registry = _make_gateway(handler, [provider])
    registry.assign(BotModelAssignment(bot_id="bot-a", model="m1"))
    ledger.set_policy("bot-a", QuotaPolicy(requests_per_minute=2))

    await gateway.chat_completion("bot-a", {"messages": []})
    await gateway.chat_completion("bot-a", {"messages": []})
    with pytest.raises(QuotaExceeded):
        await gateway.chat_completion("bot-a", {"messages": []})
    await gateway.aclose()


def test_token_store_scoping() -> None:
    store = BotTokenStore()
    token_a = store.issue("bot-a")
    token_b = store.issue("bot-b")
    assert store.resolve(token_a) == "bot-a"
    assert store.resolve(token_b) == "bot-b"
    assert store.resolve("jb-forged") is None
    assert store.revoke_bot("bot-a") == 1
    assert store.resolve(token_a) is None


async def test_gateway_app_auth_and_usage_endpoint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_completion_body("m1"))

    provider = Provider(name="acme", base_url="http://acme.test/v1", api_key="k", models=("m1",))
    gateway, tokens, _, registry = _make_gateway(handler, [provider])
    registry.assign(BotModelAssignment(bot_id="bot-a", model="m1"))
    token = tokens.issue("bot-a")
    app = create_app(gateway)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://gw.test") as client:
        # Unauthenticated requests are rejected.
        response = await client.post("/v1/chat/completions", json={"messages": []})
        assert response.status_code == 401

        response = await client.post(
            "/v1/chat/completions",
            json={"messages": []},
            headers={"Authorization": "Bearer " + token},
        )
        assert response.status_code == 200
        assert response.json()["model"] == "m1"

        # A bot can only read its own usage.
        response = await client.get(
            "/v1/bots/bot-a/usage", headers={"Authorization": "Bearer " + token}
        )
        assert response.status_code == 200
        assert response.json()["total_tokens"] == 15
        response = await client.get(
            "/v1/bots/bot-b/usage", headers={"Authorization": "Bearer " + token}
        )
        assert response.status_code == 403
    await gateway.aclose()
