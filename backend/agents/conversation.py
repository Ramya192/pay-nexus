"""
Formatting for the current session's LIVE conversation turns — distinct
from session_history (cross-session compressed summaries, §6) and
payslip_history (saved payslip snapshots). `conversation` is what makes a
follow-up question like "can you consider the payslip history" resolve
against "recommend a tax regime" from the turn before it, instead of being
classified and answered in total isolation.

Kept separate from compression/context_compressor.py because that module's
compress_in_session() only trims the list (Level 1, §6) — this one turns
the (already trimmed) list into prompt text, which orchestrator.py and any
agent that wants conversational continuity both need.
"""


def format_conversation_for_prompt(conversation: list[dict]) -> str:
    if not conversation:
        return ""
    turns = "\n".join(f"Q: {c.get('query', '')}\nA: {c.get('response', '')}" for c in conversation)
    return f"Recent conversation in this session (for context — resolve follow-ups against this):\n{turns}"
