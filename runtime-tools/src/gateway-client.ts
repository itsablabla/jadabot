/**
 * LLM client for runtimes: always talks to the central jadabot LLM Manager
 * gateway with the bot's scoped token — never directly to a provider.
 *
 * This is the piece that replaces Pipali's hosted-platform LLM access when
 * running headlessly under jadabot.
 */

import type { RuntimeConfig } from "./types.ts";

export interface ChatMessage {
  role: "system" | "user" | "assistant" | "tool";
  content: string;
}

export interface ChatCompletionResponse {
  id: string;
  model: string;
  choices: Array<{ message: { role: string; content: string } }>;
  usage?: { prompt_tokens: number; completion_tokens: number };
}

export class GatewayLLMClient {
  private readonly baseUrl: string;
  private readonly token: string;

  constructor(config: RuntimeConfig) {
    this.baseUrl = config.llmGatewayUrl.replace(/\/+$/, "");
    this.token = config.botToken;
  }

  /**
   * OpenAI-compatible chat completion via the gateway. Model selection,
   * routing, failover and quotas are handled centrally; `model` is an
   * optional override subject to the bot's allow-list.
   */
  async chatCompletion(
    messages: ChatMessage[],
    options: { model?: string } = {},
  ): Promise<ChatCompletionResponse> {
    const response = await fetch(`${this.baseUrl}/v1/chat/completions`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: "Bearer " + this.token,
      },
      body: JSON.stringify({ messages, ...(options.model ? { model: options.model } : {}) }),
    });
    if (!response.ok) {
      const detail = await response.text();
      throw new Error(`gateway error ${response.status}: ${detail}`);
    }
    return (await response.json()) as ChatCompletionResponse;
  }
}
