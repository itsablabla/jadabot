"""Scoped per-bot memory tokens.

The Runtime Manager injects one of these tokens into each Pipali runtime at
spawn time. A token binds the runtime to exactly one ``bot_id``; the memory
API rejects any request whose token does not match the requested scope, so a
runtime can never read or write another bot's memories.

Tokens are HMAC-SHA256 signed with a core-held secret. Runtimes never hold
Mem0 credentials — only these scoped tokens.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time


class TokenError(ValueError):
    """Raised when a memory token is invalid or expired."""


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def issue_memory_token(secret: str, bot_id: str, ttl_seconds: int | None = None) -> str:
    """Issue a signed token scoped to ``bot_id``.

    ``ttl_seconds=None`` produces a non-expiring token (rotated when the
    runtime is respawned).
    """
    if not secret:
        raise TokenError("token secret must not be empty")
    if not bot_id:
        raise TokenError("bot_id must not be empty")
    claims: dict[str, object] = {"bot_id": bot_id}
    if ttl_seconds is not None:
        claims["exp"] = int(time.time()) + ttl_seconds
    body = _b64encode(json.dumps(claims, separators=(",", ":"), sort_keys=True).encode())
    signature = hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
    return f"{body}.{_b64encode(signature)}"


def verify_memory_token(secret: str, token: str) -> str:
    """Verify ``token`` and return the ``bot_id`` it is scoped to."""
    try:
        body, signature = token.split(".", 1)
    except ValueError as exc:
        raise TokenError("malformed memory token") from exc
    expected = hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
    try:
        if not hmac.compare_digest(expected, _b64decode(signature)):
            raise TokenError("invalid memory token signature")
        claims = json.loads(_b64decode(body))
    except TokenError:
        raise
    except (ValueError, json.JSONDecodeError) as exc:
        raise TokenError("malformed memory token") from exc
    exp = claims.get("exp")
    if exp is not None and time.time() > exp:
        raise TokenError("memory token expired")
    bot_id = claims.get("bot_id")
    if not isinstance(bot_id, str) or not bot_id:
        raise TokenError("memory token missing bot_id")
    return bot_id
