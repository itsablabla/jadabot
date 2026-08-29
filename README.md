# jadabot

Multi-bot AI platform: [LangBot](https://github.com/langbot-app/LangBot) as the
base (IM connectors, pipelines, web panel), one dedicated
[Pipali](https://github.com/khoj-ai/pipali)-style runtime **per bot**, a single
central **LLM Manager** gateway for all bots, and
[Mem0](https://github.com/mem0ai/mem0) as the strictly-scoped memory system.

```
IM Platforms ──► LangBot (connectors, pipelines, web panel)
                    │  per-bot bridge (HTTP/SSE)
                    ▼
        Runtime Manager ──► Pipali Runtime #1 (bot A: own sandbox, db, skills)
                        ──► Pipali Runtime #2 (bot B: …)
                        ──► Pipali Runtime #N
                    │                │
                    ▼                ▼
             Mem0 Memory Service   LLM Manager (single gateway for ALL bots)
```

## Layout

- [`core/`](core/) — Python platform layer: `jadabot.memory`, `jadabot.llm`,
  `jadabot.runtimes`, `jadabot.bridge`
- [`runtime-tools/`](runtime-tools/) — TypeScript per-bot runtime harness
- [`deploy/`](deploy/) — Docker Compose stack + LangBot bridge plugin
- [`docs/`](docs/) — [architecture](docs/architecture.md),
  [memory](docs/memory.md), [provisioning](docs/provisioning.md),
  [runbooks](docs/runbooks.md)

## Quick start

```bash
# Tests
cd core && pip install -e ".[dev]" && pytest
cd runtime-tools && npm install && npx tsc --noEmit

# Full stack
cd deploy && cp .env.example .env && docker compose up -d
```
