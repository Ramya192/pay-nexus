import { useRef, useState } from "react";
import { streamChat } from "../../api/chat";
import { useBudgetStore } from "../../store/budgetStore";
import { useChatStore } from "../../store/chatStore";
import { useFinancialProfileStore } from "../../store/financialProfileStore";
import { useGoalStore } from "../../store/goalStore";
import { usePayslipHistoryStore } from "../../store/payslipHistoryStore";
import { usePayslipStore } from "../../store/payslipStore";
import { useSessionHistoryStore } from "../../store/sessionHistoryStore";
import { useTransactionStore } from "../../store/transactionStore";
import { buildExchanges } from "../../utils/exchanges";
import { ChatInput } from "./ChatInput";
import { MessageList } from "./MessageList";

export function ChatInterface() {
  const [sending, setSending] = useState(false);
  // One turn runs at a time — a question typed while another is still in
  // flight goes into chatStore's queue instead of firing a second, racing
  // request against the same conversation state. This ref carries the
  // in-flight turn's AbortController so the Stop button below can cancel it;
  // it deliberately lives outside React state since aborting doesn't itself
  // need a re-render (the resulting catch block's state update does that).
  const abortControllerRef = useRef<AbortController | null>(null);
  const addMessage = useChatStore((s) => s.addMessage);
  const addActiveAgent = useChatStore((s) => s.addActiveAgent);
  const clearActiveAgents = useChatStore((s) => s.clearActiveAgents);
  const updateLastMessage = useChatStore((s) => s.updateLastMessage);
  const dequeue = useChatStore((s) => s.dequeue);
  const queue = useChatStore((s) => s.queue);
  const removeFromQueue = useChatStore((s) => s.removeFromQueue);
  const payslipData = usePayslipStore((s) => s.payslipData);
  const financialProfile = useFinancialProfileStore((s) => s.profile);
  const sessionHistory = useSessionHistoryStore((s) => s.history);
  const payslipHistory = usePayslipHistoryStore((s) => s.snapshots);
  const transactions = useTransactionStore((s) => s.transactions);
  const goals = useGoalStore((s) => s.goals);
  const budgets = useBudgetStore((s) => s.budget);

  async function runTurn(text: string) {
    // Captured BEFORE adding this turn's own (still-empty) entries below —
    // conversation is everything asked *before* this message, so a
    // follow-up can resolve against the prior turn instead of arriving
    // with no context (see backend/agents/conversation.py). Reading it here
    // (not at enqueue time) also means a queued turn sees every earlier
    // turn that's actually finished by the time it's this one's turn to run.
    const conversation = buildExchanges(useChatStore.getState().messages);

    addMessage({ id: crypto.randomUUID(), role: "user", content: text });
    addMessage({ id: crypto.randomUUID(), role: "assistant", content: "" });
    setSending(true);
    clearActiveAgents();

    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      await streamChat(
        {
          query: text,
          payslipData,
          // Cast: FinancialProfile is a named interface (for type-safety
          // in the form/store), streamChat takes the same loose shape
          // payslipData already uses — structurally compatible, just not
          // the same declared type.
          financialProfile: financialProfile as Record<string, unknown> | null,
          // All decrypted on login by AuthScreen (except conversation,
          // which is this session's own live messages). The orchestrator
          // applies Level 1 sliding-window compression (§6) to
          // `conversation`, not to sessionHistory — sessionHistory is
          // cross-session summaries, payslipHistory is real month-over-
          // month trend data (payslip_trends.py), conversation is what
          // was just asked a moment ago. Three different things despite
          // the similar names.
          sessionHistory,
          payslipHistory,
          conversation,
          transactions,
          goals,
          budgets: budgets as Record<string, unknown> | null,
        },
        (event) => {
          if (event.event === "agent_active" && event.agent) {
            addActiveAgent(event.agent);
          } else if (event.event === "final") {
            clearActiveAgents();
            updateLastMessage(event.response ?? "", event.active_agent, event.nudge, event.tables, event.token_usage);
          } else if (event.event === "error") {
            clearActiveAgents();
            updateLastMessage(event.detail ?? "Something went wrong.");
          }
        },
        controller.signal
      );
    } catch (err) {
      clearActiveAgents();
      // A user-initiated Stop click surfaces here as an AbortError — that's
      // an intentional cancellation, not a real failure, so it gets its own
      // message rather than "couldn't reach PayNexus" (see streamChat's
      // docstring for what Stop does and doesn't cancel server-side).
      const wasAborted = err instanceof DOMException && err.name === "AbortError";
      // The backend answering with a non-OK status (streamChat tags this via
      // `.status`, see api/chat.ts) is a genuinely different failure from the
      // backend never answering at all — a stale/expired session shouldn't
      // read as "the server is down" (a real, observed bug: a 401 from an
      // expired auth token showed the exact same "check that the backend is
      // running" text as an actually-dead server, right after a previous
      // turn on the same page had just succeeded).
      const status = (err as { status?: number } | null)?.status;
      let message: string;
      if (wasAborted) {
        message = "Stopped.";
      } else if (status === 401) {
        message = "Your session has expired — please log in again.";
      } else if (typeof status === "number") {
        message = `PayNexus returned an error (${status}) — please try again.`;
      } else {
        message = "Couldn't reach PayNexus — check that the backend is running.";
      }
      updateLastMessage(message);
    } finally {
      setSending(false);
      abortControllerRef.current = null;
      const next = dequeue();
      if (next !== undefined) void runTurn(next);
    }
  }

  function handleSend(text: string) {
    if (sending) {
      useChatStore.getState().enqueue(text);
      return;
    }
    void runTurn(text);
  }

  function handleStop() {
    abortControllerRef.current?.abort();
  }

  return (
    <div className="flex h-full flex-col">
      <MessageList />
      {sending && (
        <div className="border-t border-slate-200 bg-slate-50 px-3 py-1.5 text-xs text-slate-500">
          <div className="flex items-center justify-between">
            <span>Thinking…</span>
            <button
              type="button"
              onClick={handleStop}
              className="rounded border border-slate-300 bg-white px-2 py-0.5 font-medium text-slate-600 hover:bg-slate-100"
            >
              Stop
            </button>
          </div>
          {/* Stop above only cancels the turn currently running — a queued
              question hasn't started yet, so it needs its own way to be
              retracted without touching that in-flight turn. */}
          {queue.length > 0 && (
            <ul className="mt-1 space-y-1">
              {queue.map((q) => (
                <li key={q.id} className="flex items-center justify-between gap-2">
                  <span className="truncate text-slate-500">{q.text}</span>
                  <button
                    type="button"
                    onClick={() => removeFromQueue(q.id)}
                    aria-label={`Remove queued question: ${q.text}`}
                    className="shrink-0 rounded px-1.5 leading-none text-slate-400 hover:bg-slate-200 hover:text-slate-600"
                  >
                    ✕
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      {/* Never disabled while sending — a follow-up typed here is queued via
          handleSend above instead of blocked, so the user isn't stuck
          waiting with nothing to do while a turn is in flight. */}
      <ChatInput onSend={handleSend} />
    </div>
  );
}
