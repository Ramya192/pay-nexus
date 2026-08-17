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
    transactions: List[dict]     # V2: decrypted, categorized transactions from every saved bank statement (models.Transaction shape) — same trust tier as payslip_data, decrypted client-side, plaintext for this request only
    goals: List[dict]            # V2: decrypted savings goals (store/goalStore.ts's Goal shape) — same trust tier as transactions
    budgets: dict                # V2: decrypted {category: amount} budget (store/budgetStore.ts's Budget shape) — same trust tier as financial_profile
    user_id: str

    # Routing (set by orchestrator_node)
    intent: str                  # "payslip" | "regulatory" | "nudge" | "spending" | "goal" | "budget" | "whatif" | "multi"
    agents_to_invoke: List[str]  # LangGraph node names, e.g. ["payslip_agent"]

    # Agent outputs (set by whichever agents actually ran)
    payslip_response: str
    regulatory_response: str
    nudge_response: str
    spending_response: str       # V2 — SpendingAnalyser, see agents/spending_agent.py
    goal_response: str           # V2 — GoalTracker, see agents/goal_agent.py
    budget_response: str         # V2 — BudgetPlanner, see agents/budget_agent.py
    scenario_response: str       # V2 — What-If Simulator, see agents/whatif_agent.py
    unsupported_response: str    # set instead of the above when the request asks for an action no agent can perform (delete/edit/manage saved data) — see agents/orchestrator.py's capability_gap_node
    payslip_tables: List[dict]   # structured {title, headers, rows} tables built directly in Python (never by the LLM) alongside payslip_response — see tax_calculations.py/payslip_trends.py's *_table() builders
    nudge_tables: List[dict]     # same, alongside nudge_response
    regulatory_tables: List[dict]  # same, alongside regulatory_response — always the retrieved-sources table (agents/regulatory_agent.py), not LLM-selected like the other two
    spending_tables: List[dict]  # same, alongside spending_response — see analytics/spending_trends.py + analytics/recurring.py's *_table() builders
    goal_tables: List[dict]      # same, alongside goal_response — see analytics/goal_progress.py's goal_progress_table
    budget_tables: List[dict]    # same, alongside budget_response — see budgeting/budgets.py's budget_vs_actual_table
    scenario_tables: List[dict]  # same, alongside scenario_response — built fresh per scenario in agents/whatif_agent.py, not from one shared *_table() builder

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
    spending_llm_calls: List[LLMCallMetrics]
    goal_llm_calls: List[LLMCallMetrics]
    budget_llm_calls: List[LLMCallMetrics]
    scenario_llm_calls: List[LLMCallMetrics]
    orchestrator_llm_calls: List[LLMCallMetrics]

    # Final (set by assembler_node)
    final_response: str
    active_agent: str            # comma-joined node names, for the UI's agent indicator
    nudge_card: dict | None      # {title, detail, impact} parsed from nudge_response, for NudgeCard
    tables: List[dict]           # payslip_tables + nudge_tables merged, for the frontend's DataTable rendering
    token_usage: dict            # llm_metrics.summarize() of every *_llm_calls list above — the first thing that's ever actually populated this field; previously declared and never written to
