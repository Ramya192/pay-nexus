const AGENT_LABELS: Record<string, string> = {
  payslip_agent: "📋 Payslip Agent reasoning…",
  regulatory_agent: "📜 Regulatory Agent reasoning…",
  nudge_agent: "💡 Nudge Agent reasoning…",
};

/** Driven by real `agent_active` SSE events (api/chat.ts), not a timer — see §10. */
export function AgentIndicator({ agents }: { agents: string[] }) {
  if (agents.length === 0) return null;

  return (
    <div className="flex flex-col gap-1">
      {agents.map((agent) => (
        <div key={agent} className="flex items-center gap-2 text-xs text-slate-500">
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-indigo-500" />
          {AGENT_LABELS[agent] ?? `${agent} reasoning…`}
        </div>
      ))}
    </div>
  );
}
