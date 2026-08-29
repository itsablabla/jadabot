"""FastAPI application exposing the LLM Manager as an OpenAI-compatible gateway.

Run with: ``uvicorn jadabot.llm.app:create_app --factory``
"""

from __future__ import annotations

import os

from fastapi import FastAPI, Header, HTTPException, Request

from jadabot.llm.gateway import GatewayError, LLMGateway
from jadabot.llm.quotas import QuotaExceeded, UsageLedger
from jadabot.llm.registry import ModelRegistry, Provider
from jadabot.llm.tokens import BotTokenStore


def registry_from_env() -> ModelRegistry:
    """Build a registry from ``JADABOT_PROVIDER_*`` environment variables.

    For each provider ``NAME``, set:
    ``JADABOT_PROVIDER_NAME_BASE_URL``, ``JADABOT_PROVIDER_NAME_API_KEY`` and
    optionally ``JADABOT_PROVIDER_NAME_MODELS`` (comma-separated).
    ``JADABOT_DEFAULT_MODEL`` sets the default model for unassigned bots.
    """
    registry = ModelRegistry(default_model=os.environ.get("JADABOT_DEFAULT_MODEL"))
    prefix, base_suffix = "JADABOT_PROVIDER_", "_BASE_URL"
    for key, base_url in os.environ.items():
        if not (key.startswith(prefix) and key.endswith(base_suffix)):
            continue
        name = key[len(prefix) : -len(base_suffix)]
        api_key = os.environ.get(f"{prefix}{name}_API_KEY", "")
        models = tuple(
            m.strip()
            for m in os.environ.get(f"{prefix}{name}_MODELS", "").split(",")
            if m.strip()
        )
        registry.add_provider(
            Provider(name=name.lower(), base_url=base_url, api_key=api_key, models=models)
        )
    return registry


def create_app(gateway: LLMGateway | None = None) -> FastAPI:
    """Create the gateway app. Pass a preconfigured gateway, or build from env."""
    if gateway is None:
        gateway = LLMGateway(registry_from_env(), BotTokenStore(), UsageLedger())

    app = FastAPI(title="jadabot LLM Manager", version="0.1.0")
    app.state.gateway = gateway

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/chat/completions")
    async def chat_completions(
        request: Request, authorization: str | None = Header(default=None)
    ) -> dict:
        bot_id = gateway.authenticate(authorization)
        if bot_id is None:
            raise HTTPException(status_code=401, detail="invalid or missing bot token")
        payload = await request.json()
        try:
            return await gateway.chat_completion(bot_id, payload)
        except QuotaExceeded as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except GatewayError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/v1/bots/{bot_id}/usage")
    async def bot_usage(bot_id: str, authorization: str | None = Header(default=None)) -> dict:
        caller = gateway.authenticate(authorization)
        if caller is None or caller != bot_id:
            raise HTTPException(status_code=403, detail="token does not match bot")
        usage = gateway.ledger.usage_for(bot_id)
        return {
            "bot_id": bot_id,
            "requests": usage.requests,
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "total_tokens": usage.total_tokens,
        }

    return app
