import { useChatStore } from "../../store/chatStore";
import { AgentMessage } from "./AgentMessage";
import { UserMessage } from "./UserMessage";

export function MessageList() {
  const messages = useChatStore((s) => s.messages);
  const activeAgents = useChatStore((s) => s.activeAgents);

  return (
    <div className="flex flex-1 flex-col gap-3 overflow-y-auto px-4 py-4">
      {messages.length === 0 && (
        <p className="m-auto max-w-sm whitespace-pre-line text-center text-sm text-slate-400">
          {"Ask something like:\n" +
            '• "Am I on the best tax regime for me?"\n' +
            '• "How much can I still save under 80C this year?"\n\n' +
            "Enter a payslip on the left first for the most useful answers."}
        </p>
      )}
      {messages.map((m, i) => {
        const isLast = i === messages.length - 1;
        if (m.role === "user") return <UserMessage key={m.id} content={m.content} />;
        return <AgentMessage key={m.id} message={m} pendingAgents={isLast ? activeAgents : []} />;
      })}
    </div>
  );
}
