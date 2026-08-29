# jadabot architecture

jadabot is a multi-bot platform composed of four layers:

1. **[LangBot](https://github.com/langbot-app/LangBot)** — the base platform: IM
   platform connectors (Discord, Telegram, Slack, QQ, WeChat, …), message
   pipelines, plugin system, web management panel, and HTTP/MCP API.
2. **[Pipali](https://github.com/khoj-ai/pipali)** — the agent execution
   runtime: headless Bun + Hono server with the director–actor agent loop,
   sandboxed command execution, skills, and a local PGlite database.
   **One dedicated runtime instance per bot.**
3. **LLM Manager** (`jadabot.llm`) — a single, centralized gateway that owns
   all model providers, API keys, routing, and quotas for every bot and
   every runtime.
4. **[Mem0](https://github.com/mem0ai/mem0)** — the long-term memory layer,
   shared as a service but strictly scoped per bot/user/session
   (see [memory.md](memory.md)).

```
IM Platforms ──► LangBot (connectors, pipelines, web panel)
                    │  per-bot bridge (HTTP/SSE)
                    ▼
        Runtime Manager ──► Pipali Runtime #1 (bot A: own sandbox, PGlite, skills)
                        ──► Pipali Runtime #2 (bot B: …)
                        ──► Pipali Runtime #N
                    │                │
                    ▼                ▼
             Mem0 Memory Service   LLM Manager (single gateway for ALL bots)
```

## Repository layout

| Path | Contents |
| ---- | -------- |
| `core/` | Python platform layer (`jadabot` package): memory, llm, runtimes, bridge |
| `runtime-tools/` | TypeScript runtime harness implementing the runtime HTTP contract |
| `deploy/` | Docker Compose, Dockerfiles, LangBot bridge plugin glue |
| `docs/` | This documentation |

## Components

### LangBot base (Phase 1)

LangBot is consumed as its published Docker image (pinned in
`deploy/docker-compose.yml`) rather than vendored source, so upstream updates
are a version bump. Each jadabot "bot" is a LangBot **bot + pipeline** pair:
LangBot's multi-pipeline architecture provides per-bot routing, access
control, rate limiting and monitoring out of the box. The
`deploy/langbot-plugin/` adapter mounts `jadabot.bridge.BridgeStage` as a
pipeline stage.

### Per-bot runtimes (Phase 2)

`jadabot.runtimes.RuntimeManager` guarantees the **one-runtime-per-bot**
invariant:

- each bot gets a dedicated process with its own working directory
  (`<runtimes_root>/<bot_id>/` containing `data/` and `skills/`), its own
  database, and its own port — no shared filesystem state between bots;
- lifecycle: spawn on bot creation/enable, health checks (`/healthz`),
  crash restarts (`ensure_running`), teardown + optional purge on deletion;
- `RuntimeRegistry` is the authoritative `bot_id → endpoint` mapping;
- the spawner is pluggable (`RuntimeSpawner`): `SubprocessSpawner` for
  local processes, a container-backed spawner for hard isolation.

The runtime HTTP contract (implemented by `runtime-tools`, designed so a
headless Pipali server can sit behind it):

| Endpoint | Purpose |
| -------- | ------- |
| `GET /healthz` | liveness |
| `POST /v1/task` | run a chat task; responds with an SSE stream of `text` / `tool` / `confirmation` / `done` events |
| `POST /v1/confirmation` | resolve a pending confirmation-gate prompt |

`runtime-tools/src/index.ts` currently ships an `EchoEngine` (gateway-backed,
no tools) that validates the platform plumbing end to end; the production
engine adapts Pipali's director–actor loop behind the same `AgentEngine`
interface. Pipali's hosted-platform LLM/auth dependency is replaced by
`GatewayLLMClient`, which talks only to the jadabot LLM Manager.

### Central LLM Manager (Phase 3)

`jadabot.llm` is the **only** component holding provider credentials:

- `ModelRegistry` — providers (OpenAI-compatible), model catalog, per-bot
  model assignment with fallbacks and allow-lists;
- `BotTokenStore` — per-bot scoped bearer tokens; bots/runtimes never see
  provider API keys;
- `UsageLedger` — per-bot rate limits, daily token quotas, usage accounting;
- `LLMGateway` + FastAPI app (`jadabot.llm.app`) — OpenAI-compatible
  `/v1/chat/completions` endpoint with routing and failover across fallback
  models and providers.

All consumers point at the gateway: every Pipali runtime, LangBot pipelines,
and Mem0's internal LLM/embedding calls — so all model traffic for all bots is
centrally managed, observable and billable per bot.

### Memory (Phase 4)

See [memory.md](memory.md). Single front door (`MemoryManager` +
`MemoryScope` requiring `bot_id`), Mem0 backend, strict per-bot isolation.

### Message flow

1. A platform message arrives at LangBot; the pipeline identifies the bot.
2. `BridgeStage` builds a `MemoryScope(bot_id, user_id, session_id)`, recalls
   relevant memories, and renders them as a context block.
3. The message + memory context is POSTed to that bot's runtime (`/v1/task`);
   SSE events stream back: text chunks and tool progress are relayed to the
   chat, confirmation prompts are surfaced to the bot owner and answered via
   `/v1/confirmation`.
4. Inside the runtime, the agent loop calls the LLM Manager gateway with the
   bot's scoped token; the gateway enforces quotas, routes with failover and
   records usage.
5. After completion, the bridge stores the exchange back into memory
   (asynchronously with respect to the reply — memory failures never break
   replies).

## Key risks / open items

- **Pipali headless mode** is the largest engineering unknown: Pipali is a
  desktop app whose auth/LLM access goes through the hosted Pipali Platform.
  The `AgentEngine` interface + `GatewayLLMClient` are the decoupling seam;
  validate with a spike. Fallback: keep the shipped engine and grow a minimal
  director–actor loop inspired by Pipali.
- **Resource cost** of one runtime per bot — mitigate with idle-runtime
  suspension and lazy start on first message (Runtime Manager roadmap).
- **Licensing** — Pipali and Mem0 are Apache-2.0; LangBot is consumed as an
  unmodified image. Re-verify before distributing modified LangBot code.
