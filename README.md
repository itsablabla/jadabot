# jadabot

Bot platform built on [LangBot](https://github.com/langbot-app/LangBot) with
per-bot [Pipali](https://github.com/khoj-ai/pipali) runtimes, a central LLM
manager, and [Mem0](https://github.com/mem0ai/mem0) as the long-term memory
system.

## Repository layout

| Path | Contents |
| ---- | -------- |
| `core/` | jadabot core Python package — currently the Mem0-backed memory subsystem (`jadabot.memory`) and its HTTP APIs (`jadabot.api`) |
| `runtime-tools/` | TypeScript `memory_search` / `memory_add` actors registered inside each bot's Pipali runtime |
| `docker/` | `docker-compose.memory.yml` — self-hosted Mem0 server + pgvector stack |
| `docs/` | [`memory.md`](docs/memory.md) — memory architecture, scoping/isolation model, and short-term vs long-term boundary |

## Memory subsystem quickstart

```bash
# 1. Start the self-hosted Mem0 stack
cd docker
cp .env.example .env   # fill in values
docker compose -f docker-compose.memory.yml up -d

# 2. Install and test the core package
cd ../core
pip install -e ".[dev]"
pytest

# 3. Run the core memory API
export JADABOT_MEM0_URL=http://localhost:8888
export JADABOT_MEMORY_TOKEN_SECRET=<random-secret>
export JADABOT_MEMORY_ADMIN_KEY=<random-key>
uvicorn --factory jadabot.app:create_app --port 5300
```

See [docs/memory.md](docs/memory.md) for the full design.
