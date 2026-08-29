# Runbooks

## Bring up the full stack

```bash
cd deploy
cp .env.example .env   # fill in provider keys; never commit .env
docker compose up -d
```

Services: LangBot (`:5300`), LLM Manager (`:8100`), Runtime Manager (`:8200`),
Mem0 + Qdrant (internal).

## Add a provider to the LLM Manager

Provider credentials live **only** in the LLM Manager environment. For a
provider named `NAME` (OpenAI-compatible API), set in `deploy/.env`:

```
JADABOT_PROVIDER_NAME_BASE_URL=https://api.example.com/v1
JADABOT_PROVIDER_NAME_API_KEY=...
JADABOT_PROVIDER_NAME_MODELS=model-a,model-b   # optional allow-list
```

then `docker compose up -d llm-manager`. Registration order is failover
order for providers serving the same model.

## Issue a bot token

Tokens are issued via `BotTokenStore.issue(bot_id)` (currently in-process;
the roadmap exposes this as an authenticated admin endpoint). Distribute the
token only to that bot's runtime (the Runtime Manager passes it via the
`JADABOT_BOT_TOKEN` environment variable). Revoke with `revoke(token)` or all
of a bot's tokens with `revoke_bot(bot_id)`.

## Operate runtimes

- List: `GET http://runtime-manager:8200/v1/runtimes`
- Health: `GET /v1/bots/{bot_id}/runtime` — returns `starting|running|unhealthy|stopped`
- Restart a crashed runtime: handled by `ensure_running`; manual restart is
  `DELETE` then `POST /v1/bots/{bot_id}/runtime`.
- Logs: runtime process stdout/stderr goes to the Runtime Manager container
  logs (`docker logs jadabot-runtime-manager`).

## Observability

- **LangBot dashboard** — message volume, model calls, success rate, sessions.
- **LLM Manager** — per-bot usage: `GET /v1/bots/{bot_id}/usage` (requests,
  prompt/completion/total tokens).
- **Runtime Manager** — `GET /v1/runtimes` for fleet state.

## Memory administration

Use `MemoryManager` (see `docs/memory.md`):

- browse a bot's memories: `list_memories(MemoryScope(bot_id=...))`
- delete one: `forget(memory_id, scope)` (scope-checked)
- wipe a bot or a user within a bot: `wipe(scope)`

## Run the test suites

```bash
cd core && pip install -e ".[dev]" && pytest          # Python core
cd runtime-tools && npm install && npx tsc --noEmit   # TypeScript typecheck
```
