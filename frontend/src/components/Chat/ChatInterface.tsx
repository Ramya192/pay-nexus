import { useState } from "react";
import { streamChat } from "../../api/chat";
import { useChatStore } from "../../store/chatStore";
import { usePayslipStore } from "../../store/payslipStore";
import { useSessionHistoryStore } from "../../store/sessionHistoryStore";
import { ChatInput } from "./ChatInput";
import { MessageList } from "./MessageList";

export function ChatInterface() {
  const [sending, setSending] = useState(false);
  const addMessage = useChatStore((s) => s.addMessage);
  const addActiveAgent = useChatStore((s) => s.addActiveAgent);
  const clearActiveAgents = useChatStore((s) => s.clearActiveAgents);
  const updateLastMessage = useChatStore((s) => s.updateLastMessage);
  const payslipData = usePayslipStore((s) => s.payslipData);
  const sessionHistory = useSessionHistoryStore((s) => s.history);

  async function handleSend(text: string) {
    addMessage({ id: crypto.randomUUID(), role: "user", content: text });
    addMessage({ id: crypto.randomUUID(), role: "assistant", content: "" });
    setSending(true);
    clearActiveAgents();

    try {
      // Decrypted on login by AuthScreen — real cross-session summaries now,
      // not a hardcoded []. The orchestrator applies its own Level 1
      // sliding-window compression on top of whatever's here (§6).
      await streamChat(text, payslipData, sessionHistory, (event) => {
        if (event.event === "agent_active" && event.agent) {
          addActiveAgent(event.agent);
        } else if (event.event === "final") {
          clearActiveAgents();
          updateLastMessage(event.response ?? "", event.active_agent, event.nudge);
        } else if (event.event === "error") {
          clearActiveAgents();
          updateLastMessage(event.detail ?? "Something went wrong.");
        }
      });
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
