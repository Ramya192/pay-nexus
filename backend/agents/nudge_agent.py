"""
Agent 3 — Financial Nudge. Hybrid GPT-4o-mini / Ollama phi4-mini (§7).
Reads only the compressed cross-session summary produced by
compression/context_compressor.py, plus a trimmed payslip snapshot — never
a full raw payslip (§4).
"""

import json

from agents.llm import hybrid_complete
from agents.state import PayNexusState
from config import config

_SYSTEM_PROMPT = """You are the Financial Nudge Agent inside PayNexus. You look for patterns \
across a user's payroll history — 80C utilization gaps against the ₹1.5L limit, tax-bracket \
shifts from overtime or bonus, regime-switch opportunities, multi-month trends like rising TDS \
— and proactively suggest one specific, actionable next step with an approximate rupee impact. \
You are given a compressed summary of past sessions, not raw payslips; keep suggestions grounded \
in what that summary actually shows, and say plainly when there isn't enough history yet for a \
pattern rather than inventing one.

Any time you state a remaining limit, gap, or savings figure, show the arithmetic inline as \
"A - B = C" (or "A x B = C") before stating the conclusion in words — e.g. "₹1,50,000 - ₹45,000 \
= ₹1,05,000 remaining." Never state a computed rupee figure without showing the calculation that \
produced it; this is a smaller model and unchecked mental arithmetic is the most likely way this \
agent gets a real number wrong in front of a user.

Respond with a JSON object with exactly these keys: "title" (a short headline, under 8 words),
"detail" (the explanation, including any arithmetic shown per above), and "impact" (a short
rupee-figure string like "≈ ₹31,500 saved annually", or null if there isn't enough history for a
concrete number yet — never fabricate one to fill the field)."""

_SNAPSHOT_FIELDS = ("month", "basic", "tds", "bonus", "regime")


def nudge_agent_node(state: PayNexusState) -> dict:
    history_summary = state.get("session_history") or []
    payslip_snapshot = _snapshot_only(state.get("payslip_data") or {})

    user_prompt = (
        f"Compressed session history: {json.dumps(history_summary)}\n"
        f"Current payslip snapshot (summary only): {json.dumps(payslip_snapshot)}\n\n"
        f"Question: {state['user_query']}"
    )
    answer = hybrid_complete(_SYSTEM_PROMPT, user_prompt, model=config.NUDGE_AGENT_MODEL, json_mode=True)
    return {"nudge_response": answer}


def _snapshot_only(payslip_data: dict) -> dict:
    """Only the fields pattern detection actually needs — deliberately not
    the full payslip object, so this agent's input stays a summary rather
    than a raw payslip (§4)."""
    return {k: payslip_data[k] for k in _SNAPSHOT_FIELDS if k in payslip_data}
