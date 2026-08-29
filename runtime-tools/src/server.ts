/**
 * Headless per-bot runtime server.
 *
 * A fetch-style handler implementing the jadabot runtime contract, ready to
 * mount on `Bun.serve` (or any WHATWG fetch server, e.g. Hono). The Runtime
 * Manager launches one of these per bot, so each bot gets its own process,
 * working directory, database, skills and port.
 */

import type { AgentEngine, RuntimeConfig, RuntimeEvent, TaskRequest } from "./types.ts";

const JSON_HEADERS = { "Content-Type": "application/json" };

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: JSON_HEADERS });
}

function sseLine(event: RuntimeEvent): string {
  return `data: ${JSON.stringify(event)}\n\n`;
}

/**
 * Build the fetch handler for one bot's runtime.
 *
 * Usage with Bun:
 * ```ts
 * import { configFromEnv } from "./types.ts";
 * import { createRuntimeHandler } from "./server.ts";
 * import { PipaliEngine } from "./pipali-engine.ts";
 *
 * const config = configFromEnv(process.env);
 * Bun.serve({ port: config.port, fetch: createRuntimeHandler(config, new PipaliEngine(config)) });
 * ```
 */
export function createRuntimeHandler(
  config: RuntimeConfig,
  engine: AgentEngine,
): (request: Request) => Promise<Response> {
  return async (request: Request): Promise<Response> => {
    const url = new URL(request.url);

    if (request.method === "GET" && url.pathname === "/healthz") {
      return json({ status: "ok", bot_id: config.botId });
    }

    if (request.method === "POST" && url.pathname === "/v1/task") {
      let task: TaskRequest;
      try {
        task = (await request.json()) as TaskRequest;
      } catch {
        return json({ error: "invalid JSON body" }, 400);
      }
      if (!task.message || !task.session_id) {
        return json({ error: "message and session_id are required" }, 400);
      }
      const encoder = new TextEncoder();
      const stream = new ReadableStream<Uint8Array>({
        async start(controller) {
          try {
            for await (const event of engine.runTask(task)) {
              controller.enqueue(encoder.encode(sseLine(event)));
              if (event.type === "done") break;
            }
          } catch (error) {
            const message = error instanceof Error ? error.message : String(error);
            controller.enqueue(
              encoder.encode(sseLine({ type: "text", data: { text: `runtime error: ${message}` } })),
            );
            controller.enqueue(encoder.encode(sseLine({ type: "done" })));
          } finally {
            controller.close();
          }
        },
      });
      return new Response(stream, {
        headers: {
          "Content-Type": "text/event-stream",
          "Cache-Control": "no-cache",
        },
      });
    }

    if (request.method === "POST" && url.pathname === "/v1/confirmation") {
      let body: { confirmation_id?: string; approved?: boolean };
      try {
        body = (await request.json()) as typeof body;
      } catch {
        return json({ error: "invalid JSON body" }, 400);
      }
      if (!body.confirmation_id || typeof body.approved !== "boolean") {
        return json({ error: "confirmation_id and approved are required" }, 400);
      }
      engine.resolveConfirmation(body.confirmation_id, body.approved);
      return json({ status: "resolved" });
    }

    return json({ error: "not found" }, 404);
  };
}
