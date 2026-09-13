import type { ChatMessage } from "../../store/chatStore";
import { AgentIndicator } from "../AgentIndicator/AgentIndicator";
import { NudgeCard } from "../NudgeCard/NudgeCard";
import { DataTable } from "./DataTable";

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
      <div className="max-w-[85%] space-y-2">
        {pendingAgents.length > 0 && <AgentIndicator agents={pendingAgents} />}
        {!isStreaming && (
          <div className="whitespace-pre-wrap rounded-2xl rounded-bl-sm border border-slate-200 bg-white px-4 py-2 text-sm text-slate-800">
            {message.content}
          </div>
        )}
        {message.nudge && <NudgeCard nudge={message.nudge} />}
        {message.tables?.map((table, i) => (
          <DataTable key={i} table={table} />
        ))}
        {/* Dev-build only (Vite's built-in import.meta.env.DEV — true under
         * `npm run dev`, stripped entirely from a production build). This
         * is a raw per-turn API cost figure — real, but a debugging/testing
         * concern, not something a real end user asking about their HRA
         * exemption has any use for. Found showing unconditionally to every
         * account when it was first built for exactly one purpose (seeing
         * compression's effect while testing); gating it here is what
         * actually confines it to that purpose instead of leaking into
         * production for real users. */}
        {import.meta.env.DEV && message.tokenUsage && <TokenUsageLine usage={message.tokenUsage} />}
      </div>
    </div>
  );
}

/** Exact per-turn cost from OpenAI's own usage field (backend/agents/
 * llm_metrics.py) — visible here so the effect of context compression
 * (or anything else touching prompt size) can actually be seen while
 * testing, not just inferred. Per-agent breakdown is a title tooltip
 * rather than its own UI, to stay out of the way for the common case. */
function TokenUsageLine({ usage }: { usage: import("../../store/chatStore").TokenUsage }) {
  const breakdown = Object.entries(usage.by_agent)
    .map(([agent, m]) => `${agent}: ${m.input_tokens}in/${m.output_tokens}out ($${m.cost_usd.toFixed(6)})`)
    .join("\n");
  return (
    <p
      className="px-1 text-[11px] tabular-nums text-slate-400"
      title={breakdown}
    >
      {usage.total_input_tokens.toLocaleString()} in · {usage.total_output_tokens.toLocaleString()} out · $
      {usage.total_cost_usd.toFixed(6)}
    </p>
  );
}
