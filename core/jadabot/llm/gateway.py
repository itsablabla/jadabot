"""Routing/failover core of the LLM gateway."""

from __future__ import annotations

from typing import Any

import httpx

from jadabot.llm.quotas import UsageLedger
from jadabot.llm.registry import ModelRegistry
from jadabot.llm.tokens import BotTokenStore


class GatewayError(Exception):
    """Raised when no provider could serve a request."""


class LLMGateway:
    """Routes a bot's chat-completion request to an upstream provider.

    The gateway is the only component that ever sees provider API keys. Bots
    authenticate with scoped tokens; requests are quota-checked, routed to the
    bot's assigned model (with failover across fallback models/providers) and
    recorded in the usage ledger.
    """

    def __init__(
        self,
        registry: ModelRegistry,
        tokens: BotTokenStore,
        ledger: UsageLedger,
        http_client: httpx.AsyncClient | None = None,
        request_timeout: float = 120.0,
    ) -> None:
        self.registry = registry
        self.tokens = tokens
        self.ledger = ledger
        self._client = http_client or httpx.AsyncClient(timeout=request_timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    def authenticate(self, authorization: str | None) -> str | None:
        """Resolve a ``Bearer`` header to a bot_id, or None."""
        if not authorization or not authorization.startswith("Bearer "):
            return None
        return self.tokens.resolve(authorization.removeprefix("Bearer ").strip())

    async def chat_completion(self, bot_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Serve an OpenAI-style ``/v1/chat/completions`` request for a bot."""
        self.ledger.check(bot_id)
        requested = payload.get("model")
        candidates = self.registry.candidate_models(bot_id, requested)
        errors: list[str] = []
        for model in candidates:
            providers = self.registry.providers_for(model)
            if not providers:
                errors.append(f"no provider serves model {model!r}")
                continue
            for provider in providers:
                try:
                    response = await self._client.post(
                        f"{provider.base_url.rstrip('/')}/chat/completions",
                        json={**payload, "model": model},
                        headers={"Authorization": "Bearer " + provider.api_key},
                    )
                    response.raise_for_status()
                except httpx.HTTPError as exc:
                    errors.append(f"{provider.name}/{model}: {exc}")
                    continue
                body = response.json()
                usage = body.get("usage") or {}
                self.ledger.record(
                    bot_id,
                    prompt_tokens=int(usage.get("prompt_tokens", 0)),
                    completion_tokens=int(usage.get("completion_tokens", 0)),
                )
                return body
        raise GatewayError(
            f"all providers failed for bot {bot_id!r}: " + "; ".join(errors)
        )
