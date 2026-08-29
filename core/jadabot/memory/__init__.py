"""Single front door to long-term memory.

All memory reads/writes in jadabot go through :class:`MemoryManager` with an
explicit :class:`MemoryScope`. No component talks to Mem0 directly.
"""

from jadabot.memory.backends import InMemoryBackend, Mem0Backend, MemoryBackend
from jadabot.memory.manager import MemoryManager, MemoryRecord
from jadabot.memory.scopes import MemoryScope

__all__ = [
    "InMemoryBackend",
    "Mem0Backend",
    "MemoryBackend",
    "MemoryManager",
    "MemoryRecord",
    "MemoryScope",
]
