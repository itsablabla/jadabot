"""Memory subsystem configuration and FastAPI app factory.

All settings come from environment variables so the same image works in the
Docker Compose stack and in local development:

- ``JADABOT_MEM0_URL``          base URL of the self-hosted Mem0 server
- ``JADABOT_MEM0_API_KEY``      optional API key (self-hosted auth or Mem0 cloud)
- ``JADABOT_MEMORY_TOKEN_SECRET``  HMAC secret for per-bot runtime tokens
- ``JADABOT_MEMORY_ADMIN_KEY``  bearer key for the memory admin API
"""

from __future__ import annotations

import os

from fastapi import FastAPI

from .api.memory_routes import admin_router, runtime_router
from .memory.client import Mem0Client
from .memory.manager import MemoryManager


class ConfigError(RuntimeError):
    pass


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ConfigError(f"environment variable {name} is required")
    return value


def create_memory_manager_from_env() -> MemoryManager:
    client = Mem0Client(
        base_url=os.environ.get("JADABOT_MEM0_URL", "http://localhost:8888"),
        api_key=os.environ.get("JADABOT_MEM0_API_KEY"),
    )
    return MemoryManager(client, token_secret=_require_env("JADABOT_MEMORY_TOKEN_SECRET"))


def create_app(
    memory_manager: MemoryManager | None = None,
    memory_admin_key: str | None = None,
) -> FastAPI:
    """Build the jadabot core API app (currently the memory subsystem)."""
    app = FastAPI(title="jadabot core", version="0.1.0")
    app.state.memory_manager = memory_manager or create_memory_manager_from_env()
    app.state.memory_admin_key = memory_admin_key or _require_env("JADABOT_MEMORY_ADMIN_KEY")
    app.include_router(admin_router)
    app.include_router(runtime_router)
    return app
