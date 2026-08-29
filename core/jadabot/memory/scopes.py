"""Memory scoping model for jadabot.

Maps Mem0's multi-level memory identifiers onto jadabot's domain:

- ``agent_id``  = bot/pipeline ID (each bot has its own agent memory space)
- ``user_id``   = platform user (stable cross-platform mapping maintained by core)
- ``run_id``    = LangBot session/conversation ID

Every memory operation carries a :class:`MemoryScope` so isolation between
bots is enforced structurally rather than by convention.
"""

from __future__ import annotations

import enum

from pydantic import BaseModel, field_validator


class ScopePolicy(str, enum.Enum):
    """How memories are partitioned for a bot."""

    PER_USER = "per_user"  # memories keyed by (bot, user)
    PER_SESSION = "per_session"  # memories keyed by (bot, user, session)
    AGENT_GLOBAL = "agent_global"  # memories shared across all users of the bot


class MemoryScope(BaseModel):
    """A fully-resolved memory scope for one operation.

    ``bot_id`` is always required: no memory operation may run unscoped,
    which is what guarantees one bot can never read another bot's memories.
    """

    bot_id: str
    user_id: str | None = None
    session_id: str | None = None

    @field_validator("bot_id")
    @classmethod
    def _bot_id_required(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("bot_id must be a non-empty string")
        return v

    def to_mem0_identifiers(self, policy: ScopePolicy) -> dict[str, str]:
        """Translate this scope into Mem0 ``agent_id``/``user_id``/``run_id`` params."""
        identifiers: dict[str, str] = {"agent_id": self.bot_id}
        if policy is ScopePolicy.AGENT_GLOBAL:
            return identifiers
        if self.user_id:
            identifiers["user_id"] = self.user_id
        if policy is ScopePolicy.PER_SESSION and self.session_id:
            identifiers["run_id"] = self.session_id
        return identifiers
