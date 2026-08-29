# jadabot memory

All long-term memory goes through **one front door**:
`jadabot.memory.MemoryManager`. No component talks to Mem0 directly, and no
competing memory mechanisms may be added.

## Scoping

Every operation requires a `MemoryScope`, and `MemoryScope` **requires**
`bot_id` — construction fails without it. This makes cross-bot memory leaks
structurally impossible at the API level.

Mapping to [Mem0](https://github.com/mem0ai/mem0) identifiers:

| jadabot | Mem0 | Meaning |
| ------- | ---- | ------- |
| `bot_id` | `agent_id` | the bot (required) |
| `user_id` | `user_id` | the platform user (optional) |
| `session_id` | `run_id` | the conversation/session (optional) |

This isolates each bot's memories entirely while allowing per-user
personalization within a bot and per-session working memory.

## API

- `remember(text, scope, metadata)` — store a salient fact
- `recall(query, scope, limit)` — semantic retrieval within scope
- `build_context(query, scope)` — render recalled memories as an LLM prompt block
- `list_memories(scope)` — web-panel administration
- `forget(memory_id, scope)` — delete one memory; **denied** if the id is not
  in scope (verified, not trusted)
- `wipe(scope)` — full deletion for bot/user removal and retention policy

## Backends

- `Mem0Backend` — production; wraps a self-hosted Mem0 instance (Qdrant vector
  store, see `deploy/docker-compose.yml`). Its Mem0 config must point the
  `llm` and `embedder` sections at the jadabot LLM Manager gateway so memory
  model traffic stays centrally managed. Requires the `jadabot[mem0]` extra.
- `InMemoryBackend` — dependency-free backend for tests and local development.

## Integration points

- **LangBot pipeline** (`jadabot.bridge.BridgeStage`): recalls relevant
  memories before forwarding a message to the bot's runtime (injected as
  `memory_context`), and stores the exchange after the reply completes.
  Memory failures are logged and never break replies.
- **Pipali runtime**: `memory_context` arrives with each task; deliberate
  recall/store during multi-step tasks is exposed to the agent as actor tools
  that call back through the MemoryManager (roadmap).
