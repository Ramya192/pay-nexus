import { useState } from "react";
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
  const addMessage = useChatStore((s) => s.addMessage);
  const addActiveAgent = useChatStore((s) => s.addActiveAgent);
  const clearActiveAgents = useChatStore((s) => s.clearActiveAgents);
  const updateLastMessage = useChatStore((s) => s.updateLastMessage);
  const payslipData = usePayslipStore((s) => s.payslipData);
  const financialProfile = useFinancialProfileStore((s) => s.profile);
  const sessionHistory = useSessionHistoryStore((s) => s.history);
  const payslipHistory = usePayslipHistoryStore((s) => s.snapshots);
  const transactions = useTransactionStore((s) => s.transactions);
  const goals = useGoalStore((s) => s.goals);
  const budgets = useBudgetStore((s) => s.budget);

  async function handleSend(text: string) {
    // Captured BEFORE adding this turn's own (still-empty) entries below —
    // conversation is everything asked *before* this message, so a
    // follow-up can resolve against the prior turn instead of arriving
    // with no context (see backend/agents/conversation.py).
    const conversation = buildExchanges(useChatStore.getState().messages);

    addMessage({ id: crypto.randomUUID(), role: "user", content: text });
    addMessage({ id: crypto.randomUUID(), role: "assistant", content: "" });
    setSending(true);
    clearActiveAgents();

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
        }
      );
    } catch {
      clearActiveAgents();
      updateLastMessage("Couldn't reach PayNexus — check that the backend is running.");
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="flex h-full flex-col">
      <MessageList />
      <ChatInput onSend={handleSend} disabled={sending} />
    </div>
  );
}
