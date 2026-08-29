# memory in jadabot

jadabot uses [Mem0](https://github.com/mem0ai/mem0) as its **single source of
long-term semantic memory**. This document describes the architecture, the
scoping/isolation model, and the boundary between short-term and long-term
memory so contributors don't add competing memory mechanisms.

## Architecture

```
IM Platforms
     │
┌────▼─────────────────────────────────────────┐
│  jadabot Core (LangBot base)                 │
│  • Pipelines + Pipali RequestRunner          │
│  • Runtime Manager                           │
│  • Central LLM Manager (gateway)             │
│  • Memory Manager (Mem0 admin/config)        │
└────┬───────────────┬───────────────┬─────────┘
     │               │               │
┌────▼─────┐   ┌─────▼────┐   ┌──────▼───┐
│ Pipali   │   │ Pipali   │   │ Pipali   │
│ Runtime A│   │ Runtime B│   │ Runtime C│
└────┬─────┘   └────┬─────┘   └────┬─────┘
     │  memory ops  │               │
     └──────────────┼───────────────┘
        ┌───────────▼────────────┐        ┌──────────────────┐
        │  Mem0 Server (self-    │───────►│ Central LLM      │
        │  hosted, shared infra) │ extract│ Manager (gateway)│
        │  • vector store        │ /embed │                  │
        │  • per-bot namespaces  │        └──────────────────┘
        └────────────────────────┘
```

- The **Mem0 server is shared infrastructure** (one deployment, one vector
  store), started via `docker/docker-compose.memory.yml`. The Mem0 cloud
  platform is a config-switchable alternative (`JADABOT_MEM0_API_KEY` +
  pointing `JADABOT_MEM0_URL` at the cloud API).
- Mem0's **own LLM/embedding calls go through the central LLM manager**
  (`OPENAI_BASE_URL` in the compose file), so extraction usage is routed,
  rate-limited, and cost-attributed like every other model call. The memory
  layer holds no provider API keys.

## Scoping and isolation

Mem0 identifiers map onto jadabot's domain (see `core/jadabot/memory/scopes.py`):

| Mem0 identifier | jadabot meaning |
| --------------- | ---------------- |
| `agent_id`      | bot/pipeline ID — every bot has its own memory space |
| `user_id`       | platform user (stable cross-platform mapping) |
| `run_id`        | LangBot session/conversation ID |

Every operation goes through `MemoryManager` with a `MemoryScope` that
**requires `bot_id`**, so unscoped access is impossible by construction.

Per-bot **scope policies** (`BotMemoryConfig.scope_policy`):

- `per_user` (default) — memories keyed by (bot, user); recalled across sessions
- `per_session` — memories additionally keyed by session
- `agent_global` — one shared memory space for all users of the bot

### Runtime tokens

The Runtime Manager injects a signed, bot-scoped memory token
(`JADABOT_MEMORY_TOKEN`) into each Pipali runtime at spawn time. The
runtime-facing API (`/api/memory/runtime/...`) verifies that the token's
`bot_id` matches the requested scope, so **one bot's runtime can never query
another bot's memories**. Runtimes never hold Mem0 credentials — only their
scoped token. Mem0 credentials live only in jadabot core.

## Message-flow integration

The Pipali `RequestRunner` uses `MemoryEnricher`
(`core/jadabot/memory/enrichment.py`):

1. **Before dispatch** — `build_memory_context()` searches Mem0 for relevant
   memories for this user + bot and injects them into the runtime context.
   The search runs with a **hard timeout (2s default) and graceful skip**, so
   a slow or down memory backend never blocks a reply.
2. **After response** — `record_exchange()` writes the exchange back to Mem0
   as a **fire-and-forget** task; extraction latency never delays the reply.

Inside the runtime, the agent additionally gets deliberate `memory_search` /
`memory_add` actors (`runtime-tools/src/memoryActors.ts`), which take
advantage of Mem0's first-class agent-generated facts.

## Administration

The admin API (`/api/memory/admin/...`, bearer-key protected; consumed by the
web panel) supports:

- per-bot config: enable/disable memory, scope policy, search `top_k`
- browse/search/delete memories per bot and per user
- **forget user**: privacy/GDPR-style deletion of one user's memories across
  one bot or across all bots (`DELETE /api/memory/admin/users/{user_id}`)

## Short-term vs long-term boundary

| Store | Role | Retention |
| ----- | ---- | --------- |
| LangBot session/conversation state | short-term dialogue context within a pipeline | transactional |
| Pipali per-bot PGlite DB | runtime conversation history and task state | per-bot, transactional |
| **Mem0** | **long-term semantic memory (facts, preferences, outcomes)** | governed by Memory Manager |

Do **not** add new long-term memory mechanisms elsewhere; extend the Memory
Manager instead. Conversation text intentionally exists in both PGlite and
Mem0 — deletion flows (bot deletion, forget-user) must cover both stores.

## Version pinning

Mem0's memory algorithm changed significantly between v2 and v3 (ADD-only
extraction, entity linking, multi-signal retrieval). Pin the server image to
a tested tag in `docker/docker-compose.memory.yml` and follow the
[migration guide](https://docs.mem0.ai/migration/oss-v2-to-v3) deliberately
when upgrading.

## Running the tests

```bash
cd core
pip install -e ".[dev]"
pytest
```

Covered: bot-to-bot isolation, cross-session recall, scope policies,
enrichment timeout/error skip, fire-and-forget writes, admin/runtime API
auth, token tampering/expiry, and deletion propagation (forget-user across
bots, ownership-checked deletes).
