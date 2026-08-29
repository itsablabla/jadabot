"""Per-bot rate limits, token quotas and usage accounting."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass


class QuotaExceeded(Exception):
    """Raised when a bot exceeds its rate limit or token quota."""


@dataclass(frozen=True, slots=True)
class QuotaPolicy:
    """Limits applied to one bot. ``None`` means unlimited."""

    requests_per_minute: int | None = None
    tokens_per_day: int | None = None


@dataclass(slots=True)
class BotUsage:
    """Aggregate usage for one bot (surfaced in the dashboard)."""

    requests: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class UsageLedger:
    """Enforces per-bot quotas and records usage for accounting."""

    _DAY = 86_400.0
    _MINUTE = 60.0

    def __init__(self, clock=time.monotonic) -> None:
        self._clock = clock
        self._policies: dict[str, QuotaPolicy] = {}
        self._request_times: dict[str, deque[float]] = defaultdict(deque)
        self._token_events: dict[str, deque[tuple[float, int]]] = defaultdict(deque)
        self._usage: dict[str, BotUsage] = defaultdict(BotUsage)

    def set_policy(self, bot_id: str, policy: QuotaPolicy) -> None:
        self._policies[bot_id] = policy

    def check(self, bot_id: str) -> None:
        """Raise :class:`QuotaExceeded` if the bot may not make a request now."""
        policy = self._policies.get(bot_id)
        if policy is None:
            return
        now = self._clock()
        if policy.requests_per_minute is not None:
            window = self._request_times[bot_id]
            while window and now - window[0] > self._MINUTE:
                window.popleft()
            if len(window) >= policy.requests_per_minute:
                raise QuotaExceeded(f"bot {bot_id!r} exceeded requests-per-minute limit")
        if policy.tokens_per_day is not None:
            events = self._token_events[bot_id]
            while events and now - events[0][0] > self._DAY:
                events.popleft()
            if sum(tokens for _, tokens in events) >= policy.tokens_per_day:
                raise QuotaExceeded(f"bot {bot_id!r} exceeded tokens-per-day quota")

    def record(self, bot_id: str, prompt_tokens: int = 0, completion_tokens: int = 0) -> None:
        """Record a completed request against a bot's usage."""
        now = self._clock()
        self._request_times[bot_id].append(now)
        total = prompt_tokens + completion_tokens
        if total:
            self._token_events[bot_id].append((now, total))
        usage = self._usage[bot_id]
        usage.requests += 1
        usage.prompt_tokens += prompt_tokens
        usage.completion_tokens += completion_tokens

    def usage_for(self, bot_id: str) -> BotUsage:
        return self._usage[bot_id]
