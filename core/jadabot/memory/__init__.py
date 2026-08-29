"""jadabot long-term memory subsystem, backed by Mem0.

Short-term/transactional state (LangBot sessions, Pipali PGlite history)
stays where it is; this package is the single source of long-term semantic
memory. See docs/memory.md for the boundary.
"""

from .client import Mem0Client, Mem0ClientError, MemoryRecord
from .enrichment import MemoryEnricher
from .manager import BotMemoryConfig, MemoryManager
from .scopes import MemoryScope, ScopePolicy
from .tokens import TokenError, issue_memory_token, verify_memory_token

__all__ = [
    "BotMemoryConfig",
    "Mem0Client",
    "Mem0ClientError",
    "MemoryEnricher",
    "MemoryManager",
    "MemoryRecord",
    "MemoryScope",
    "ScopePolicy",
    "TokenError",
    "issue_memory_token",
    "verify_memory_token",
]
