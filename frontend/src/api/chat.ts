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
  /** V2 — decrypted, categorized transactions flattened across every saved bank statement; see store/transactionStore.ts and backend/agents/spending_agent.py. */
  transactions: Record<string, unknown>[];
  /** V2 — decrypted savings goals; see store/goalStore.ts and backend/agents/goal_agent.py. */
  goals: Record<string, unknown>[];
  /** V2 — decrypted {category: amount} budget, or null if none saved yet; see store/budgetStore.ts and backend/agents/budget_agent.py. */
  budgets: Record<string, unknown> | null;
}

/**
 * POST /chat streams Server-Sent Events (backend/api/routes/chat.py). Uses
 * fetch + a manual SSE reader instead of the EventSource API, because
 * EventSource can't send the Authorization header this endpoint requires.
 *
 * `signal`, if given, lets the caller cancel client-side (a visible "Stop"
 * button) — this abandons the response immediately from the user's point of
 * view (the fetch/read loop rejects with an AbortError), but does NOT
 * currently interrupt the backend's own in-flight work: `payslip_agent.py`
 * and friends run their LLM call via a synchronous `asyncio.run(...)` inside
 * the graph node, which can't observe a client disconnect. The turn keeps
 * computing server-side and its result is just discarded. True server-side
 * cancellation would need those node functions to become real `await`s
 * reachable from this async request handler — not done here.
 */
export async function streamChat(
  params: StreamChatParams,
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal
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
      transactions: params.transactions,
      goals: params.goals,
      budgets: params.budgets,
    }),
    signal,
  });

  if (!response.ok || !response.body) {
    // A real network failure (backend unreachable, DNS, CORS) makes fetch()
    // itself reject with a TypeError before we ever get here — this branch
    // only runs once we DID get a response, just not an OK one. Tagging
    // `status` lets the caller (ChatInterface.tsx) tell "server answered
    // 401/500" apart from "server never answered at all" instead of
    // collapsing both into the same generic message.
    const err = new Error(`Chat request failed: ${response.status}`) as Error & { status?: number };
    err.status = response.status;
    throw err;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  // SSE frames are separated by a blank line; the payload line starts with
  // "data: " (see backend/api/routes/chat.py's _sse()). Wrapped in try/catch
  // so one malformed frame is logged and skipped instead of silently
  // dropping every event after it (or the whole turn, if it escaped
  // uncaught up to streamChat's caller).
  const processFrame = (frame: string) => {
    const line = frame.split("\n").find((l) => l.startsWith("data: "));
    if (!line) return;
    try {
      onEvent(JSON.parse(line.slice("data: ".length)) as ChatEvent);
    } catch (err) {
      console.error("streamChat: failed to parse SSE frame", line, err);
    }
  };

  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) processFrame(frame);
  }

  // The stream can close with one last complete frame still sitting in
  // `buffer` — every frame the server sends already ends in "\n\n" (_sse()),
  // but if that trailing separator arrives in the very last chunk before the
  // connection closes, the loop above stops before splitting it out, and the
  // final event (often the terminal "final"/"error" event carrying the
  // actual answer) was silently lost. Flush the decoder for any pending
  // multi-byte tail, then process whatever's left the same way.
  buffer += decoder.decode();
  for (const frame of buffer.split("\n\n")) {
    if (frame.trim()) processFrame(frame);
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
