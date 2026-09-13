import type { ChatMessage } from "../store/chatStore";

export interface Exchange {
  query: string;
  response: string;
}

/**
 * Pairs consecutive user/assistant messages into {query, response}
 * exchanges. Shared by ChatInterface.tsx (sends recent exchanges with
 * every /chat call, so a follow-up like "consider the payslip history"
 * resolves against what was just asked — see backend/agents/conversation.py)
 * and App.tsx's logout flow (Level 2 summarization, §6). Skips a trailing
 * assistant message with empty content — mid-stream, not a real answer yet.
 */
export function buildExchanges(messages: ChatMessage[]): Exchange[] {
  const exchanges: Exchange[] = [];
  for (let i = 0; i < messages.length - 1; i++) {
    const user = messages[i];
    const assistant = messages[i + 1];
    if (user.role === "user" && assistant?.role === "assistant" && assistant.content) {
      exchanges.push({ query: user.content, response: assistant.content });
    }
  }
  return exchanges;
}
