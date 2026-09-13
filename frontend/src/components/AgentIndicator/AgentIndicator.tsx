import { FileText, Info, Lightbulb, Scale, type LucideIcon } from "lucide-react";

const AGENT_META: Record<string, { icon: LucideIcon; label: string }> = {
  payslip_agent: { icon: FileText, label: "Payslip Agent reasoning…" },
  regulatory_agent: { icon: Scale, label: "Regulatory Agent reasoning…" },
  // Internal name stays nudge_agent (backend/agents/nudge_agent.py etc.) —
  // only the display string changes; "Savings Advisor" reads clearer than
  // "Nudge Agent" for someone with no context on the internal agent split.
  nudge_agent: { icon: Lightbulb, label: "Savings Advisor reasoning…" },
  // Not a reasoning agent — just recognizing the request is a data-management
  // action (delete/edit/manage) none of the three above can perform. See
  // backend/agents/orchestrator.py's capability_gap_node.
  capability_gap_node: { icon: Info, label: "Checking what's possible from chat…" },
};

/** Driven by real `agent_active` SSE events (api/chat.ts), not a timer — see §10. */
export function AgentIndicator({ agents }: { agents: string[] }) {
  if (agents.length === 0) return null;

  return (
    <div className="flex flex-col gap-1">
      {agents.map((agent) => {
        const meta = AGENT_META[agent];
        const Icon = meta?.icon ?? Info;
        return (
          <div key={agent} className="flex items-center gap-2 text-xs text-slate-500">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-brand-500" />
            <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            {meta?.label ?? `${agent} reasoning…`}
          </div>
        );
      })}
    </div>
  );
}
