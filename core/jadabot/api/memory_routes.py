"""HTTP APIs for the jadabot memory subsystem.

Two surfaces:

- ``/api/memory/admin/...``  — web-panel administration (per-bot config,
  browse/search/delete, forget-user). Guarded by an admin API key.
- ``/api/memory/runtime/...`` — scoped endpoints used by the per-bot Pipali
  runtime memory actors (``memory_search`` / ``memory_add``). Guarded by the
  per-bot scoped token issued by the Runtime Manager; the token's ``bot_id``
  must match the requested scope.
"""

from __future__ import annotations

import hmac
import typing

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from ..memory.manager import BotMemoryConfig, MemoryManager
from ..memory.scopes import MemoryScope
from ..memory.tokens import TokenError


def get_memory_manager(request: Request) -> MemoryManager:
    manager = getattr(request.app.state, "memory_manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="memory manager not configured")
    return manager


def get_admin_key(request: Request) -> str:
    admin_key = getattr(request.app.state, "memory_admin_key", None)
    if not admin_key:
        raise HTTPException(status_code=503, detail="memory admin key not configured")
    return admin_key


def require_admin(
    request: Request,
    authorization: str | None = Header(default=None),
) -> None:
    admin_key = get_admin_key(request)
    token = _bearer_token(authorization)
    if not hmac.compare_digest(token, admin_key):
        raise HTTPException(status_code=403, detail="admin credentials required")


def _bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    return authorization.removeprefix("Bearer ")


# ---------------------------------------------------------------------------
# Admin API (web panel)
# ---------------------------------------------------------------------------

admin_router = APIRouter(
    prefix="/api/memory/admin",
    dependencies=[Depends(require_admin)],
    tags=["memory-admin"],
)


class BotConfigResponse(BaseModel):
    bot_id: str
    config: BotMemoryConfig


class MemoryListResponse(BaseModel):
    results: list[dict[str, typing.Any]]


class SearchBody(BaseModel):
    query: str
    user_id: str | None = None
    session_id: str | None = None
    top_k: int | None = Field(default=None, ge=1, le=100)


@admin_router.get("/bots", response_model=list[BotConfigResponse])
async def list_bot_configs(manager: MemoryManager = Depends(get_memory_manager)):
    return [
        BotConfigResponse(bot_id=bot_id, config=manager.get_bot_config(bot_id))
        for bot_id in manager.known_bots()
    ]


@admin_router.get("/bots/{bot_id}/config", response_model=BotConfigResponse)
async def get_bot_config(bot_id: str, manager: MemoryManager = Depends(get_memory_manager)):
    return BotConfigResponse(bot_id=bot_id, config=manager.get_bot_config(bot_id))


@admin_router.put("/bots/{bot_id}/config", response_model=BotConfigResponse)
async def put_bot_config(
    bot_id: str,
    config: BotMemoryConfig,
    manager: MemoryManager = Depends(get_memory_manager),
):
    manager.configure_bot(bot_id, config)
    return BotConfigResponse(bot_id=bot_id, config=config)


@admin_router.get("/bots/{bot_id}/memories", response_model=MemoryListResponse)
async def browse_memories(
    bot_id: str,
    user_id: str | None = None,
    session_id: str | None = None,
    top_k: int | None = None,
    manager: MemoryManager = Depends(get_memory_manager),
):
    scope = MemoryScope(bot_id=bot_id, user_id=user_id, session_id=session_id)
    records = await manager.list_memories(scope, top_k=top_k)
    return MemoryListResponse(results=[r.model_dump() for r in records])


@admin_router.post("/bots/{bot_id}/search", response_model=MemoryListResponse)
async def search_memories(
    bot_id: str,
    body: SearchBody,
    manager: MemoryManager = Depends(get_memory_manager),
):
    scope = MemoryScope(bot_id=bot_id, user_id=body.user_id, session_id=body.session_id)
    records = await manager.search(scope, body.query, top_k=body.top_k)
    return MemoryListResponse(results=[r.model_dump() for r in records])


@admin_router.delete("/bots/{bot_id}/memories/{memory_id}")
async def delete_memory(
    bot_id: str,
    memory_id: str,
    manager: MemoryManager = Depends(get_memory_manager),
):
    try:
        await manager.delete_memory(bot_id, memory_id)
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"deleted": memory_id}


@admin_router.delete("/bots/{bot_id}/memories")
async def delete_bot_memories(bot_id: str, manager: MemoryManager = Depends(get_memory_manager)):
    await manager.delete_bot_memories(bot_id)
    return {"deleted_bot": bot_id}


@admin_router.delete("/users/{user_id}")
async def forget_user(
    user_id: str,
    bot_id: str | None = None,
    manager: MemoryManager = Depends(get_memory_manager),
):
    """Privacy/GDPR-style deletion of one user's memories (all bots by default)."""
    await manager.forget_user(user_id, bot_id=bot_id)
    return {"forgotten_user": user_id, "bot_id": bot_id}


# ---------------------------------------------------------------------------
# Runtime API (per-bot Pipali runtime memory actors)
# ---------------------------------------------------------------------------

runtime_router = APIRouter(prefix="/api/memory/runtime", tags=["memory-runtime"])


class RuntimeSearchBody(BaseModel):
    bot_id: str
    query: str
    user_id: str | None = None
    session_id: str | None = None
    top_k: int | None = Field(default=None, ge=1, le=100)


class RuntimeAddBody(BaseModel):
    bot_id: str
    messages: list[dict[str, str]]
    user_id: str | None = None
    session_id: str | None = None
    metadata: dict[str, typing.Any] | None = None


def _authorize_runtime(manager: MemoryManager, authorization: str | None, bot_id: str) -> None:
    token = _bearer_token(authorization)
    try:
        manager.authorize_runtime(token, bot_id)
    except (TokenError, PermissionError) as exc:
        raise HTTPException(status_code=403, detail=str(exc))


@runtime_router.post("/search", response_model=MemoryListResponse)
async def runtime_search(
    body: RuntimeSearchBody,
    authorization: str | None = Header(default=None),
    manager: MemoryManager = Depends(get_memory_manager),
):
    _authorize_runtime(manager, authorization, body.bot_id)
    scope = MemoryScope(bot_id=body.bot_id, user_id=body.user_id, session_id=body.session_id)
    records = await manager.search(scope, body.query, top_k=body.top_k)
    return MemoryListResponse(results=[r.model_dump() for r in records])


@runtime_router.post("/add")
async def runtime_add(
    body: RuntimeAddBody,
    authorization: str | None = Header(default=None),
    manager: MemoryManager = Depends(get_memory_manager),
):
    _authorize_runtime(manager, authorization, body.bot_id)
    scope = MemoryScope(bot_id=body.bot_id, user_id=body.user_id, session_id=body.session_id)
    return await manager.add(scope, body.messages, metadata=body.metadata)
