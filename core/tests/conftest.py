"""Shared fixtures for jadabot core tests."""

from __future__ import annotations

import pytest

from jadabot.memory import InMemoryBackend, MemoryManager


@pytest.fixture
def memory_manager() -> MemoryManager:
    return MemoryManager(InMemoryBackend())
