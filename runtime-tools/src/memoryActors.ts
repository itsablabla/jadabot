/**
 * Mem0-backed memory actors for a Pipali runtime.
 *
 * Each bot's runtime is spawned by the jadabot Runtime Manager with:
 *   JADABOT_BOT_ID            the bot this runtime belongs to
 *   JADABOT_MEMORY_TOKEN      scoped token (grants access to this bot only)
 *   JADABOT_CORE_URL          base URL of jadabot core
 *
 * The actors call jadabot core's scoped runtime memory API; the runtime never
 * holds Mem0 credentials, and the token structurally prevents reading another
 * bot's memories. Register these alongside Pipali's built-in actors so the
 * agent can deliberately recall and store facts mid-task.
 */

export interface MemoryToolsConfig {
  coreUrl: string;
  botId: string;
  memoryToken: string;
  /** Platform user the current conversation belongs to, if any. */
  userId?: string;
  /** LangBot session/conversation ID, if any. */
  sessionId?: string;
}

export interface MemoryRecord {
  id: string | null;
  memory: string | null;
  user_id: string | null;
  agent_id: string | null;
  run_id: string | null;
  score: number | null;
  metadata: Record<string, unknown> | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface ChatMessage {
  role: "user" | "assistant" | "system";
  content: string;
}

/** Pipali-style actor definition (name, description, JSON schema, execute). */
export interface ActorDefinition {
  name: string;
  description: string;
  parameters: Record<string, unknown>;
  execute: (args: Record<string, unknown>) => Promise<string>;
}

export function configFromEnv(env: NodeJS.ProcessEnv = process.env): MemoryToolsConfig {
  const coreUrl = env.JADABOT_CORE_URL;
  const botId = env.JADABOT_BOT_ID;
  const memoryToken = env.JADABOT_MEMORY_TOKEN;
  if (!coreUrl || !botId || !memoryToken) {
    throw new Error(
      "JADABOT_CORE_URL, JADABOT_BOT_ID and JADABOT_MEMORY_TOKEN must be set by the Runtime Manager",
    );
  }
  return { coreUrl, botId, memoryToken };
}

async function callCore(
  config: MemoryToolsConfig,
  path: string,
  body: Record<string, unknown>,
): Promise<unknown> {
  const response = await fetch(`${config.coreUrl.replace(/\/$/, "")}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: "Bearer " + config.memoryToken,
    },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`memory API error ${response.status}: ${detail.slice(0, 500)}`);
  }
  return response.json();
}

export async function memorySearch(
  config: MemoryToolsConfig,
  query: string,
  topK?: number,
): Promise<MemoryRecord[]> {
  const result = (await callCore(config, "/api/memory/runtime/search", {
    bot_id: config.botId,
    query,
    user_id: config.userId,
    session_id: config.sessionId,
    top_k: topK,
  })) as { results: MemoryRecord[] };
  return result.results;
}

export async function memoryAdd(
  config: MemoryToolsConfig,
  messages: ChatMessage[],
  metadata?: Record<string, unknown>,
): Promise<unknown> {
  return callCore(config, "/api/memory/runtime/add", {
    bot_id: config.botId,
    messages,
    user_id: config.userId,
    session_id: config.sessionId,
    metadata,
  });
}

/** Build the actor set to register with the Pipali director. */
export function createMemoryActors(config: MemoryToolsConfig): ActorDefinition[] {
  return [
    {
      name: "memory_search",
      description:
        "Search this bot's long-term memory for facts about the current user or past tasks. " +
        "Use before asking the user for information they may have shared previously.",
      parameters: {
        type: "object",
        properties: {
          query: { type: "string", description: "What to look for" },
          top_k: { type: "number", description: "Max results (default 5)" },
        },
        required: ["query"],
      },
      execute: async (args) => {
        const records = await memorySearch(
          config,
          String(args.query),
          typeof args.top_k === "number" ? args.top_k : undefined,
        );
        if (records.length === 0) return "No relevant memories found.";
        return records
          .map((record) => `- ${record.memory ?? ""}`.trim())
          .join("\n");
      },
    },
    {
      name: "memory_add",
      description:
        "Store an important fact in this bot's long-term memory (e.g. a confirmed action, " +
        "a stated user preference, or a durable task outcome).",
      parameters: {
        type: "object",
        properties: {
          fact: { type: "string", description: "The fact to remember" },
        },
        required: ["fact"],
      },
      execute: async (args) => {
        await memoryAdd(config, [{ role: "assistant", content: String(args.fact) }]);
        return "Memory stored.";
      },
    },
  ];
}
