import { apiClient } from "./client";
import { useAuthStore } from "../store/authStore";
import type { Nudge } from "../components/NudgeCard/NudgeCard";

export interface ChatEvent {
  event: "agent_active" | "final" | "error";
  agent?: string;
  response?: string;
  active_agent?: string;
  nudge?: Nudge | null;
  detail?: string;
}

/**
 * POST /chat streams Server-Sent Events (backend/api/routes/chat.py). Uses
 * fetch + a manual SSE reader instead of the EventSource API, because
 * EventSource can't send the Authorization header this endpoint requires.
 */
export async function streamChat(
  query: string,
  payslipData: Record<string, unknown> | null,
  sessionHistory: Record<string, unknown>[],
  onEvent: (event: ChatEvent) => void
): Promise<void> {
  const token = useAuthStore.getState().token;
  const response = await fetch("/chat", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ query, payslip_data: payslipData, session_history: sessionHistory }),
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

export interface ChatExchange {
  query: string;
  response: string;
}

/**
 * POST /chat/summarize — Level 2 compression (§6). Returns a plaintext
 * summary object; the caller (App.tsx's logout flow) is responsible for
 * encrypting it before persisting via api/payslip.ts's saveSessionSummary —
 * this call alone never touches storage.
 */
export async function summarizeSession(
  exchanges: ChatExchange[],
  payslipData: Record<string, unknown> | null
): Promise<Record<string, unknown>> {
  const { data } = await apiClient.post<{ summary: Record<string, unknown> }>("/chat/summarize", {
    exchanges,
    payslip_data: payslipData,
  });
  return data.summary;
}
