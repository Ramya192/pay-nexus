"""
Two-level context compression (PROJECT_CONTEXT.md §6):

Level 1 (in-session)   — sliding window: keep the last few exchanges
                          verbatim. Pure Python, no LLM call, cheap enough
                          to run before every agent dispatch.
Level 2 (cross-session) — after a session ends, compress the whole thing
                          into the ~200-token structured JSON the
                          Orchestrator hands the Nudge Agent as
                          `session_history` on the next session.

Both are gated by config.ENABLE_CONTEXT_COMPRESSION. Level 1 is called from
agents/orchestrator.py before fan-out; Level 2 is called once when a
session ends (wired in from the API layer in Phase 4 — /chat's session
teardown, not built yet).
"""

import json

from openai import OpenAI

from config import config

_client = OpenAI(api_key=config.OPENAI_API_KEY)

_SLIDING_WINDOW = 3

_SUMMARY_SYSTEM_PROMPT = """Compress this PayNexus session into a JSON object with exactly \
these keys: "payslip_snapshot" (object: month, basic, tds, and any other components \
discussed), "key_changes" (array of short strings), "nudges_given" (array of short strings), \
"regime_recommendation" (one string). Be terse — this replaces the full session history in \
future context, so keep the whole object under ~200 tokens."""


def compress_in_session(exchanges: list[dict]) -> list[dict]:
    """Level 1 — keeps the last _SLIDING_WINDOW exchanges verbatim. Older
    ones are dropped here, not summarized; Level 2 is what actually
    preserves them, run once at session end rather than on every turn."""
    if not config.ENABLE_CONTEXT_COMPRESSION:
        return exchanges
    return exchanges[-_SLIDING_WINDOW:]


def compress_session_summary(exchanges: list[dict], payslip_data: dict) -> dict:
    """Level 2 — called once when a session ends. Returns the structured
    summary dict to persist (encrypted, client-side) as a SessionSummary row."""
    if not exchanges:
        return {
            "payslip_snapshot": payslip_data,
            "key_changes": [],
            "nudges_given": [],
            "regime_recommendation": "",
        }

    user_prompt = (
        f"Payslip snapshot: {json.dumps(payslip_data)}\nSession exchanges: {json.dumps(exchanges)}"
    )
    response = _client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": _SUMMARY_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
    )
    return json.loads(response.choices[0].message.content or "{}")
