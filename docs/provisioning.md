# Provisioning a bot

Each jadabot bot is: a LangBot **bot + pipeline** pair, a dedicated runtime,
a scoped LLM gateway token, and an isolated memory scope.

## Steps

1. **Create the bot in LangBot** (web panel at `http://localhost:5300`):
   configure the platform adapter (Discord, Telegram, …) with the platform
   credentials, and create a pipeline for the bot with the `jadabot-bridge`
   plugin stage enabled. Note the bot id — it is used everywhere below.

2. **Issue a gateway token** for the bot on the LLM Manager (see
   [runbooks.md](runbooks.md#issue-a-bot-token)) and assign its model:

   - assigned model, optional fallback models (failover order),
   - optional allow-list restricting which models the bot may request,
   - quota policy (requests/minute, tokens/day).

3. **Start the runtime** via the Runtime Manager control-plane:

   ```
   POST http://runtime-manager:8200/v1/bots/{bot_id}/runtime
   {"bot_token": "<token from step 2>"}
   ```

   This provisions an isolated working directory
   (`<runtimes_root>/<bot_id>/{data,skills}`), allocates a port, spawns the
   runtime process with `JADABOT_BOT_ID`, `JADABOT_RUNTIME_PORT`,
   `JADABOT_LLM_GATEWAY_URL` and `JADABOT_BOT_TOKEN` in its environment, and
   registers the `bot_id → endpoint` mapping. The call is idempotent.

4. **Send a test message** on the chat platform. Watch:

   - runtime state: `GET /v1/bots/{bot_id}/runtime` (`running`),
   - gateway usage: `GET /v1/bots/{bot_id}/usage` on the LLM Manager,
   - memories accumulating for the bot's scope.

## Decommissioning a bot

1. Disable the bot/pipeline in LangBot.
2. `DELETE /v1/bots/{bot_id}/runtime?purge=true` — stops the runtime and
   removes its working directory.
3. Revoke the bot's gateway tokens (`BotTokenStore.revoke_bot`).
4. Wipe the bot's memories: `MemoryManager.wipe(MemoryScope(bot_id=...))`.
