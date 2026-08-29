# jadabot core

Python platform layer built around [LangBot](https://github.com/langbot-app/LangBot):

- `jadabot.memory` — single front door to [Mem0](https://github.com/mem0ai/mem0) long-term memory.
- `jadabot.llm` — central LLM Manager gateway for **all** bots.
- `jadabot.runtimes` — Runtime Manager guaranteeing one [Pipali](https://github.com/khoj-ai/pipali) runtime per bot.
- `jadabot.bridge` — LangBot pipeline stage forwarding chat messages to per-bot runtimes.

## Development

```bash
cd core
pip install -e ".[dev]"
pytest
```
