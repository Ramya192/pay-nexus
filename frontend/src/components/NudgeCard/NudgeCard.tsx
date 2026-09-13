export interface Nudge {
  title: string;
  detail: string;
  impact?: string | null; // e.g. "≈ ₹18,000 saved annually" — null when there isn't enough history for a figure yet
}

/**
 * Rendered from AgentMessage when a chat response includes a `nudge`
 * (backend/agents/orchestrator.py's assembler_node parses Agent 3's
 * structured JSON into exactly this shape — see `_parse_nudge`).
 */
export function NudgeCard({ nudge }: { nudge: Nudge }) {
  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 p-3">
      <p className="text-sm font-medium text-amber-900">{nudge.title}</p>
      <p className="mt-1 text-sm text-amber-800">{nudge.detail}</p>
      {nudge.impact && <p className="mt-2 text-xs font-semibold text-amber-700">{nudge.impact}</p>}
    </div>
  );
}
