"""Per-bot scoped gateway tokens.

Bots and their runtimes never see provider API keys; they authenticate to the
gateway with a scoped token that maps back to their ``bot_id``.
"""

from __future__ import annotations

import hmac
import secrets


class BotTokenStore:
    """Issues and verifies per-bot bearer tokens for the gateway."""

    def __init__(self) -> None:
        self._token_to_bot: dict[str, str] = {}

    def issue(self, bot_id: str) -> str:
        """Issue a new token for ``bot_id`` (multiple tokens may coexist)."""
        if not bot_id:
            raise ValueError("bot_id is required")
        token = f"jb-{secrets.token_urlsafe(32)}"
        self._token_to_bot[token] = bot_id
        return token

    def resolve(self, token: str) -> str | None:
        """Return the bot_id for ``token``, or None if invalid."""
        for known, bot_id in self._token_to_bot.items():
            if hmac.compare_digest(known, token):
                return bot_id
        return None

    def revoke(self, token: str) -> None:
        self._token_to_bot.pop(token, None)

    def revoke_bot(self, bot_id: str) -> int:
        """Revoke all tokens for a bot (bot deletion). Returns count revoked."""
        doomed = [t for t, b in self._token_to_bot.items() if b == bot_id]
        for token in doomed:
            del self._token_to_bot[token]
        return len(doomed)
