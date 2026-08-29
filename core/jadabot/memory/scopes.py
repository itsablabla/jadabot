"""Memory scoping.

Every memory operation is scoped. ``bot_id`` is mandatory so one bot can never
read or write another bot's memories. The scope maps onto Mem0 identifiers as:

- ``bot_id``     -> Mem0 ``agent_id``  (the bot)
- ``user_id``    -> Mem0 ``user_id``   (the platform user, optional)
- ``session_id`` -> Mem0 ``run_id``    (the conversation/session, optional)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MemoryScope:
    """Identifies whose memory is being accessed. ``bot_id`` is required."""

    bot_id: str
    user_id: str | None = None
    session_id: str | None = None

    def __post_init__(self) -> None:
        if not self.bot_id or not self.bot_id.strip():
            raise ValueError("MemoryScope requires a non-empty bot_id")

    def to_mem0_ids(self) -> dict[str, str]:
        """Translate this scope to Mem0 identifier keyword arguments."""
        ids: dict[str, str] = {"agent_id": self.bot_id}
        if self.user_id:
            ids["user_id"] = self.user_id
        if self.session_id:
            ids["run_id"] = self.session_id
        return ids
