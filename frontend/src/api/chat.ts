import { apiClient } from "./client";
import { useAuthStore } from "../store/authStore";
import type { TableData } from "../components/Chat/DataTable";
import type { Nudge } from "../components/NudgeCard/NudgeCard";
import type { TokenUsage } from "../store/chatStore";
import type { Exchange } from "../utils/exchanges";

export interface ChatEvent {
  event: "agent_active" | "final" | "error";
  agent?: string;
  response?: string;
  active_agent?: string;
  nudge?: Nudge | null;
  /** Built entirely backend-side (agents/tables.py) — the agent only picks which to show. */
  tables?: TableData[];
  /** Exact per-turn LLM cost (backend/agents/llm_metrics.py) — from OpenAI's own usage field. */
  token_usage?: TokenUsage;
  detail?: string;
}

export interface StreamChatParams {
  query: string;
  payslipData: Record<string, unknown> | null;
  financialProfile: Record<string, unknown> | null;
  sessionHistory: Record<string, unknown>[];
  /** Decrypted saved payslip snapshots — NOT sessionHistory despite the similar name; see payslipHistoryStore.ts. */
  payslipHistory: Record<string, unknown>[];
  /** THIS session's exchanges so far — lets a follow-up resolve against what was just asked; see backend/agents/conversation.py. */
  conversation: Exchange[];
}

/**
 * POST /chat streams Server-Sent Events (backend/api/routes/chat.py). Uses
 * fetch + a manual SSE reader instead of the EventSource API, because
 * EventSource can't send the Authorization header this endpoint requires.
 */
export async function streamChat(
  params: StreamChatParams,
  onEvent: (event: ChatEvent) => void
): Promise<void> {
  const token = useAuthStore.getState().token;
  // fetch, not apiClient — EventSource can't send the Authorization header
  // this endpoint requires, so this is a manual SSE reader instead (see
  // this function's docstring). Still needs the same base URL apiClient
  // uses in production (client.ts) — a bare "/chat" path only worked by
  // accident in dev, where Vite's proxy happens to forward it; in a real
  // deployment the frontend and backend are on different hosts entirely.
  const response = await fetch(`${import.meta.env.VITE_API_BASE_URL || ""}/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({
      query: params.query,
      payslip_data: params.payslipData,
      financial_profile: params.financialProfile,
      session_history: params.sessionHistory,
      payslip_history: params.payslipHistory,
      conversation: params.conversation,
    }),
  });

  if (!response.ok || !response.body) {
    throw new Error(`Chat request failed: ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE frames are separated by a blank line; the payload line starts
    // with "data: " (see backend/api/routes/chat.py's _sse()).
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      const line = frame.split("\n").find((l) => l.startsWith("data: "));
      if (!line) continue;
      onEvent(JSON.parse(line.slice("data: ".length)) as ChatEvent);
    }
  }
}

/**
 * POST /chat/summarize — Level 2 compression (§6). Returns a plaintext
 * summary object; the caller (App.tsx's logout flow) is responsible for
 * encrypting it before persisting via api/payslip.ts's saveSessionSummary —
 * this call alone never touches storage.
 */
export async function summarizeSession(
  exchanges: Exchange[],
  payslipData: Record<string, unknown> | null
): Promise<Record<string, unknown>> {
  const { data } = await apiClient.post<{ summary: Record<string, unknown> }>("/chat/summarize", {
    exchanges,
    payslip_data: payslipData,
  });
  return data.summary;
}
