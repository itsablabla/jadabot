"""MemoryManager: per-bot Mem0 administration and scoped access.

Responsibilities (Phase 7 of the jadabot plan):

- per-bot memory configuration (enabled flag, scope policy, retention/top_k)
- scoped memory operations that structurally enforce bot isolation
- scoped token issuance for Pipali runtimes (via :mod:`jadabot.memory.tokens`)
- privacy operations: forget a user across one bot or across all bots
"""

from __future__ import annotations

import typing

from pydantic import BaseModel, Field

from .client import Mem0Client, MemoryRecord
from .scopes import MemoryScope, ScopePolicy
from .tokens import issue_memory_token, verify_memory_token


class BotMemoryConfig(BaseModel):
    """Memory settings for one bot/pipeline."""

    enabled: bool = True
    scope_policy: ScopePolicy = ScopePolicy.PER_USER
    search_top_k: int = Field(default=5, ge=1, le=100)


class MemoryManager:
    """Central memory administration for all bots.

    All memory reads/writes flow through this class so that scoping rules
    are applied in exactly one place.
    """

    def __init__(self, client: Mem0Client, token_secret: str):
        self._client = client
        self._token_secret = token_secret
        self._bot_configs: dict[str, BotMemoryConfig] = {}
        self._known_bots: set[str] = set()

    # -- configuration -------------------------------------------------

    def configure_bot(self, bot_id: str, config: BotMemoryConfig) -> None:
        self._bot_configs[bot_id] = config
        self._known_bots.add(bot_id)

    def get_bot_config(self, bot_id: str) -> BotMemoryConfig:
        return self._bot_configs.get(bot_id, BotMemoryConfig())

    def set_enabled(self, bot_id: str, enabled: bool) -> None:
        config = self.get_bot_config(bot_id).model_copy(update={"enabled": enabled})
        self.configure_bot(bot_id, config)

    def is_enabled(self, bot_id: str) -> bool:
        return self.get_bot_config(bot_id).enabled

    def known_bots(self) -> list[str]:
        return sorted(self._known_bots)

    # -- runtime tokens ------------------------------------------------

    def issue_runtime_token(self, bot_id: str, ttl_seconds: int | None = None) -> str:
        """Issue a memory token for one bot's Pipali runtime."""
        self._known_bots.add(bot_id)
        return issue_memory_token(self._token_secret, bot_id, ttl_seconds)

    def authorize_runtime(self, token: str, bot_id: str) -> None:
        """Validate that ``token`` grants access to ``bot_id``'s memories."""
        token_bot_id = verify_memory_token(self._token_secret, token)
        if token_bot_id != bot_id:
            raise PermissionError(
                f"memory token is scoped to bot {token_bot_id!r}, not {bot_id!r}"
            )

    # -- scoped memory operations ---------------------------------------

    def _identifiers(self, scope: MemoryScope) -> dict[str, str]:
        self._known_bots.add(scope.bot_id)
        policy = self.get_bot_config(scope.bot_id).scope_policy
        return scope.to_mem0_identifiers(policy)

    async def search(self, scope: MemoryScope, query: str, top_k: int | None = None) -> list[MemoryRecord]:
        config = self.get_bot_config(scope.bot_id)
        if not config.enabled:
            return []
        return await self._client.search(
            query,
            self._identifiers(scope),
            top_k=top_k or config.search_top_k,
        )

    async def add(
        self,
        scope: MemoryScope,
        messages: list[dict[str, str]],
        metadata: dict[str, typing.Any] | None = None,
    ) -> dict[str, typing.Any]:
        if not self.is_enabled(scope.bot_id):
            return {"results": []}
        return await self._client.add(messages, self._identifiers(scope), metadata=metadata)

    async def list_memories(self, scope: MemoryScope, top_k: int | None = None) -> list[MemoryRecord]:
        return await self._client.get_all(self._identifiers(scope), top_k=top_k)

    async def delete_memory(self, bot_id: str, memory_id: str) -> None:
        """Delete a single memory after confirming it belongs to ``bot_id``."""
        records = await self._client.get_all({"agent_id": bot_id})
        if not any(record.id == memory_id for record in records):
            raise PermissionError(f"memory {memory_id!r} does not belong to bot {bot_id!r}")
        await self._client.delete(memory_id)

    async def delete_bot_memories(self, bot_id: str) -> None:
        """Wipe all long-term memory for one bot (e.g. on bot deletion)."""
        await self._client.delete_all({"agent_id": bot_id})

    async def forget_user(self, user_id: str, bot_id: str | None = None) -> None:
        """Privacy/GDPR-style deletion of one user's memories.

        With ``bot_id`` set, deletes memories for that bot only; otherwise
        deletes the user's memories across every known bot.
        """
        if bot_id is not None:
            await self._client.delete_all({"agent_id": bot_id, "user_id": user_id})
            return
        for known_bot in self.known_bots():
            await self._client.delete_all({"agent_id": known_bot, "user_id": user_id})
