import type { ChatMessage } from "../../store/chatStore";
import { AgentIndicator } from "../AgentIndicator/AgentIndicator";
import { NudgeCard } from "../NudgeCard/NudgeCard";

export function AgentMessage({
  message,
  pendingAgents,
}: {
  message: ChatMessage;
  pendingAgents: string[];
}) {
  const isStreaming = pendingAgents.length > 0 && message.content === "";

  return (
    <div className="flex justify-start">
      <div className="max-w-[75%] space-y-2">
        {pendingAgents.length > 0 && <AgentIndicator agents={pendingAgents} />}
        {!isStreaming && (
          <div className="whitespace-pre-wrap rounded-2xl rounded-bl-sm border border-slate-200 bg-white px-4 py-2 text-sm text-slate-800">
            {message.content}
          </div>
        )}
        {message.nudge && <NudgeCard nudge={message.nudge} />}
      </div>
    </div>
  );
}
