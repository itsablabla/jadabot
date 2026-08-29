/**
 * The jadabot runtime contract.
 *
 * Every per-bot runtime (a headless Pipali server, or any compatible
 * implementation) exposes this HTTP contract to the LangBot bridge:
 *
 * - `GET  /healthz`         -> `{ "status": "ok" }`
 * - `POST /v1/task`         -> `text/event-stream` of {@link RuntimeEvent}
 * - `POST /v1/confirmation` -> resolves a pending confirmation gate
 */

/** Inbound task from the LangBot bridge. */
export interface TaskRequest {
  /** The user's chat message. */
  message: string;
  /** Conversation/session id (maps to Mem0 run_id). */
  session_id: string;
  /** Platform user id (maps to Mem0 user_id). */
  user_id?: string;
  /** Pre-rendered long-term memory context from the MemoryManager. */
  memory_context?: string;
}

/** Streamed agent events, sent as SSE `data:` lines. */
export type RuntimeEvent =
  | { type: "text"; data: { text: string } }
  | { type: "tool"; data: { description: string } }
  | { type: "confirmation"; data: { confirmation_id: string; prompt: string } }
  | { type: "done"; data?: Record<string, never> };

/** Answer to a confirmation-gate prompt. */
export interface ConfirmationRequest {
  confirmation_id: string;
  approved: boolean;
}

/** Per-bot runtime configuration, injected by the Runtime Manager via env. */
export interface RuntimeConfig {
  /** The bot this runtime serves. Exactly one runtime exists per bot. */
  botId: string;
  /** Port to listen on (allocated by the Runtime Manager). */
  port: number;
  /**
   * The central jadabot LLM Manager gateway. The runtime's LLM client must
   * point here (never directly at a provider) using {@link botToken}.
   */
  llmGatewayUrl: string;
  /** Per-bot scoped gateway token. Never a raw provider API key. */
  botToken: string;
}

/**
 * The agent engine behind the HTTP contract. Production wires this to the
 * Pipali director-actor loop; tests can use a scripted implementation.
 */
export interface AgentEngine {
  /** Run one task, yielding streamed events; must end with a `done` event. */
  runTask(request: TaskRequest): AsyncIterable<RuntimeEvent>;
  /** Resolve a confirmation gate raised during a task. */
  resolveConfirmation(confirmationId: string, approved: boolean): void;
}

/** Read runtime configuration from Runtime Manager environment variables. */
export function configFromEnv(env: Record<string, string | undefined>): RuntimeConfig {
  const botId = env.JADABOT_BOT_ID;
  const port = Number(env.JADABOT_RUNTIME_PORT);
  const llmGatewayUrl = env.JADABOT_LLM_GATEWAY_URL;
  const botToken = env.JADABOT_BOT_TOKEN;
  if (!botId || !llmGatewayUrl || !botToken || !Number.isInteger(port) || port <= 0) {
    throw new Error(
      "missing runtime env: JADABOT_BOT_ID, JADABOT_RUNTIME_PORT, JADABOT_LLM_GATEWAY_URL, JADABOT_BOT_TOKEN",
    );
  }
  return { botId, port, llmGatewayUrl, botToken };
}
