/**
 * Runtime entrypoint for one bot.
 *
 * Launched by the jadabot Runtime Manager (one process per bot) with
 * `JADABOT_*` environment variables. Wires the runtime contract server to an
 * agent engine.
 *
 * The `EchoEngine` below is a stand-in used for integration testing of the
 * platform plumbing. The production engine adapts the headless Pipali
 * director–actor loop (see `docs/architecture.md`, Phase 2) behind the same
 * `AgentEngine` interface, using `GatewayLLMClient` for all model calls.
 */

import { GatewayLLMClient } from "./gateway-client.ts";
import { createRuntimeHandler } from "./server.ts";
import type { AgentEngine, RuntimeConfig, RuntimeEvent, TaskRequest } from "./types.ts";
import { configFromEnv } from "./types.ts";

export { configFromEnv, createRuntimeHandler, GatewayLLMClient };
export type { AgentEngine, RuntimeConfig, RuntimeEvent, TaskRequest };

/** Minimal engine: answers via the LLM gateway, no tools. */
export class EchoEngine implements AgentEngine {
  private readonly llm: GatewayLLMClient;

  constructor(config: RuntimeConfig) {
    this.llm = new GatewayLLMClient(config);
  }

  async *runTask(request: TaskRequest): AsyncIterable<RuntimeEvent> {
    const messages: Array<{ role: "system" | "user"; content: string }> = [];
    if (request.memory_context) {
      messages.push({ role: "system", content: request.memory_context });
    }
    messages.push({ role: "user", content: request.message });
    const completion = await this.llm.chatCompletion(messages);
    const text = completion.choices[0]?.message?.content ?? "";
    yield { type: "text", data: { text } };
    yield { type: "done" };
  }

  resolveConfirmation(_confirmationId: string, _approved: boolean): void {
    // EchoEngine never raises confirmation gates.
  }
}

/** Start the runtime server (Bun). */
export function main(env: Record<string, string | undefined>): void {
  const config = configFromEnv(env);
  const handler = createRuntimeHandler(config, new EchoEngine(config));
  // deno-lint-ignore no-explicit-any
  const bun = (globalThis as any).Bun;
  if (!bun?.serve) {
    throw new Error("this entrypoint requires Bun (bun run src/index.ts)");
  }
  bun.serve({ port: config.port, fetch: handler });
  console.log(`jadabot runtime for bot ${config.botId} listening on :${config.port}`);
}

// Auto-start when executed directly under Bun.
// deno-lint-ignore no-explicit-any
const maybeBun = (globalThis as any).Bun;
if (maybeBun?.main && maybeBun.main === import.meta.url.replace("file://", "")) {
  main(maybeBun.env as Record<string, string | undefined>);
}
