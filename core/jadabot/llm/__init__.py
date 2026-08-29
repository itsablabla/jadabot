"""Central LLM Manager: the only component holding provider credentials.

Exposes an OpenAI-compatible gateway for every bot and runtime, with per-bot
model assignment, scoped tokens, routing/failover, quotas and usage accounting.
"""

from jadabot.llm.gateway import GatewayError, LLMGateway
from jadabot.llm.registry import BotModelAssignment, ModelRegistry, Provider
from jadabot.llm.quotas import QuotaExceeded, QuotaPolicy, UsageLedger
from jadabot.llm.tokens import BotTokenStore

__all__ = [
    "BotModelAssignment",
    "BotTokenStore",
    "GatewayError",
    "LLMGateway",
    "ModelRegistry",
    "Provider",
    "QuotaExceeded",
    "QuotaPolicy",
    "UsageLedger",
]
