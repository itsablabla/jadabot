# jadabot-bridge LangBot plugin

Thin adapter that mounts `jadabot.bridge.BridgeStage` into a LangBot pipeline.

For each inbound platform message, LangBot resolves the target bot + pipeline;
this plugin forwards the message to that bot's dedicated Pipali runtime (via
the Runtime Manager registry), streams the agent's output back to the chat,
surfaces confirmation-gate prompts to the bot owner, and persists the exchange
through the jadabot `MemoryManager` (Mem0).

All heavy lifting lives in the `jadabot` package so it stays unit-testable
without a LangBot install; this directory contains only the LangBot-specific
glue (event registration and message send calls against the LangBot plugin
API of the pinned LangBot version).

Configuration (environment variables on the LangBot container):

- `JADABOT_RUNTIME_MANAGER_URL` — Runtime Manager control-plane (default `http://runtime-manager:8200`)
- `JADABOT_MEM0_URL` — Mem0 service endpoint used by the MemoryManager

See `docs/architecture.md` (Phase 2) and `docs/provisioning.md` for the full
message flow and per-bot setup steps.
