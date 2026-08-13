"""
Shared LangGraph state — see PROJECT_CONTEXT.md §8. Every node reads a
subset of this and returns a partial dict; LangGraph merges each node's
return value back into one PayNexusState per run.
"""

from typing import List, TypedDict


class PayNexusState(TypedDict, total=False):
    # User inputs
    user_query: str
    payslip_data: dict          # decrypted payslip components, this session only
    session_history: List[dict]  # compressed cross-session summaries (§6)
    user_id: str

    # Routing (set by orchestrator_node)
    intent: str                  # "payslip" | "regulatory" | "nudge" | "multi"
    agents_to_invoke: List[str]  # LangGraph node names, e.g. ["payslip_agent"]

    # Agent outputs (set by whichever agents actually ran)
    payslip_response: str
    regulatory_response: str
    nudge_response: str

    # Final (set by assembler_node)
    final_response: str
    active_agent: str            # comma-joined node names, for the UI's agent indicator
    nudge_card: dict | None      # {title, detail, impact} parsed from nudge_response, for NudgeCard
    token_usage: dict
