"""
Shared LangGraph state — see PROJECT_CONTEXT.md §8. Every node reads a
subset of this and returns a partial dict; LangGraph merges each node's
return value back into one PayNexusState per run.
"""

from typing import List, TypedDict

from agents.llm_metrics import LLMCallMetrics


class PayNexusState(TypedDict, total=False):
    # User inputs
    user_query: str
    payslip_data: dict          # decrypted payslip components, this session only
    financial_profile: dict     # decrypted investments/loans/insurance (see tax_calculations.py)
    session_history: List[dict]  # compressed cross-session summaries (§6)
    payslip_history: List[dict]  # decrypted saved payslip snapshots, oldest->newest (see payslip_trends.py) — NOT the same thing as session_history despite the similar name
    conversation: List[dict]     # THIS session's live exchanges so far, [{query, response}, ...] — Level 1 (§6) trims this; lets a follow-up question resolve against what was just asked, not just the new message in isolation
    user_id: str

    # Routing (set by orchestrator_node)
    intent: str                  # "payslip" | "regulatory" | "nudge" | "multi"
    agents_to_invoke: List[str]  # LangGraph node names, e.g. ["payslip_agent"]

    # Agent outputs (set by whichever agents actually ran)
    payslip_response: str
    regulatory_response: str
    nudge_response: str
    unsupported_response: str    # set instead of the above when the request asks for an action no agent can perform (delete/edit/manage saved data) — see agents/orchestrator.py's capability_gap_node
    payslip_tables: List[dict]   # structured {title, headers, rows} tables built directly in Python (never by the LLM) alongside payslip_response — see tax_calculations.py/payslip_trends.py's *_table() builders
    nudge_tables: List[dict]     # same, alongside nudge_response
    regulatory_tables: List[dict]  # same, alongside regulatory_response — always the retrieved-sources table (agents/regulatory_agent.py), not LLM-selected like the other two

    # Exact per-call token/cost metrics (agents/llm_metrics.py) — one list
    # per node that makes an LLM call, same parallel-fan-out-safe pattern
    # as the *_tables fields above (a single shared list would race across
    # concurrently-running nodes; LangGraph merges these by key, not by
    # append, so each node needs its own key). orchestrator_llm_calls
    # covers the intent classifier specifically, set by orchestrator_node
    # itself before fan-out — not part of the fan-out agents' outputs.
    payslip_llm_calls: List[LLMCallMetrics]
    regulatory_llm_calls: List[LLMCallMetrics]
    nudge_llm_calls: List[LLMCallMetrics]
    orchestrator_llm_calls: List[LLMCallMetrics]

    # Final (set by assembler_node)
    final_response: str
    active_agent: str            # comma-joined node names, for the UI's agent indicator
    nudge_card: dict | None      # {title, detail, impact} parsed from nudge_response, for NudgeCard
    tables: List[dict]           # payslip_tables + nudge_tables merged, for the frontend's DataTable rendering
    token_usage: dict            # llm_metrics.summarize() of every *_llm_calls list above — the first thing that's ever actually populated this field; previously declared and never written to
