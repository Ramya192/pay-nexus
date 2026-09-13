"""
Two-level context compression (PROJECT_CONTEXT.md §6):

Level 1 (in-session)   — sliding window: keep the last few exchanges
                          verbatim. Pure Python, no LLM call, cheap enough
                          to run before every agent dispatch.
Level 2 (cross-session) — after a session ends, compress the whole thing
                          into the ~200-token structured JSON the
                          Orchestrator hands the Nudge Agent as
                          `session_history` on the next session, and caps
                          how many of those summaries stay in play at once
                          (cap_session_history) — GET /payslip/history
                          returns every summary a user has ever had, with
                          no limit, so without a cap here `session_history`
                          would grow unboundedly across months of use.

Both levels are gated by config.ENABLE_CONTEXT_COMPRESSION. Level 1 is
called from agents/orchestrator.py before fan-out; so is the
cap_session_history step. Level 2's summarization itself is called once
when a session ends, from /chat/summarize.

Level 1 and the cap step each have two modes now (2026-09-12): a fixed
window (`headroom_tokens=None`, the original behavior — always exactly
_SLIDING_WINDOW/_MAX_SESSIONS regardless of which model ends up serving
the turn) and a dynamic, capacity-aware trim (`headroom_tokens` given —
keeps as many recent items as actually fit that many tokens, per
compression/token_budget.trim_to_headroom). orchestrator_v2.classify_intent
uses the fixed mode to size its OWN classifier input (agent_keys don't
exist yet to size a real per-model headroom against) and the dynamic mode
for the shared conversation/session_history every fanned-out agent
receives, once it knows which agent(s) — and therefore which real context
window — this turn actually involves (see
orchestrator_v2._context_window_for_turn). Existing callers that don't
pass `headroom_tokens` (compression/eval.py, tests) keep the old fixed
behavior unchanged.

compression/eval.py's cost-savings harness caught a real bug in this
module on its first run: the summary used to embed the FULL
payslip_snapshot object (month, basic, hra, PF, TDS...) verbatim in every
single session's summary. With several accumulated sessions all covering
the same month (a common case — a user asks a few questions, closes the
tab, comes back the same week), that snapshot was byte-for-byte duplicated
across every one of them, and the harness measured a real case where
compression cost MORE tokens than sending the raw exchanges would have —
the opposite of the point. Fixed by keeping only `payslip_month` — a cheap
anchor for "which month this session was about" — instead of the full
object; the Nudge/Payslip agents already receive the actual payslip
figures through their own state fields (payslip_data, payslip_history),
never through session_history, so the full snapshot was pure duplication,
not unique information.
"""

import json
import time

from openai import OpenAI

from agents.llm_metrics import LLMCallMetrics, record_from_response
from compression import token_budget
from config import config

_client = OpenAI(api_key=config.OPENAI_API_KEY)

_SLIDING_WINDOW = 3

# How many past session summaries stay in play at once — the cross-session
# analogue of _SLIDING_WINDOW above. Each summary is already capped at
# ~200 tokens on its own, but nothing capped the COUNT of them, so a
# long-time user's session_history could otherwise grow every session,
# forever, with no ceiling.
_MAX_SESSIONS = 10

# Dynamic-mode floors/ceilings (see module docstring) — a floor so
# trimming never removes the most recent turn(s) entirely even under a
# tiny headroom, and a ceiling so a huge context window doesn't turn into
# "keep the whole history," same reasoning as the fixed constants above,
# just as bounds instead of an exact count. The session-history ceiling
# reuses _MAX_SESSIONS itself — no reason for the dynamic mode's upper
# bound to differ from the fixed mode's only value.
_MIN_KEPT_EXCHANGES = 1
_MAX_KEPT_EXCHANGES = 20
_MIN_KEPT_SESSIONS = 1
_MAX_KEPT_SESSIONS = _MAX_SESSIONS


def _render_exchange(exchange: dict) -> str:
    """Approximates what one exchange actually contributes to a prompt —
    the same Q/A shape agents/conversation.py's format_conversation_for_prompt
    renders the whole (already-trimmed) list into, just per-item so
    token_budget.trim_to_headroom can size one exchange at a time."""
    return f"Q: {exchange.get('query', '')}\nA: {exchange.get('response', '')}"


def _render_session_summary(summary: dict) -> str:
    """Same idea for one cross-session summary — nudge_agent_node embeds
    the whole session_history list via one json.dumps(...) call; this
    renders a single entry the same way so its per-item token cost is a
    fair proxy for its real contribution."""
    return json.dumps(summary)

_SUMMARY_SYSTEM_PROMPT = """Compress this PayNexus session into a JSON object with exactly \
these keys: "payslip_month" (string — just the month, e.g. "2026-03", not the full payslip \
breakdown; the agents reading this already have the actual figures elsewhere and don't need \
them repeated here), "key_changes" (array of short strings), "nudges_given" (array of short \
strings), "regime_recommendation" (one string). Be terse — this replaces the full session \
history in future context, so keep the whole object under ~100 tokens."""


def compress_in_session(
    exchanges: list[dict], *, headroom_tokens: int | None = None, model: str = "gpt-4o"
) -> list[dict]:
    """Level 1. Older exchanges are dropped here, not summarized — Level 2
    is what actually preserves them, run once at session end rather than
    on every turn.

    `headroom_tokens=None` (default): the original fixed window — always
    exactly the last _SLIDING_WINDOW exchanges, unaware of which model
    will actually see this. `headroom_tokens` given: dynamic, capacity-
    aware trim (see module docstring and compression/token_budget) — keeps
    as many recent exchanges as actually fit that many tokens, floored at
    _MIN_KEPT_EXCHANGES and capped at _MAX_KEPT_EXCHANGES."""
    if not config.ENABLE_CONTEXT_COMPRESSION:
        return exchanges
    if headroom_tokens is None:
        return exchanges[-_SLIDING_WINDOW:]
    return token_budget.trim_to_headroom(
        exchanges, _render_exchange, headroom_tokens,
        min_keep=_MIN_KEPT_EXCHANGES, max_keep=_MAX_KEPT_EXCHANGES, model=model,
    )


def cap_session_history(
    session_history: list[dict], *, headroom_tokens: int | None = None, model: str = "gpt-4o"
) -> list[dict]:
    """Level 2's per-turn cap. session_history arrives newest-first (GET
    /payslip/history orders by created_at.desc()).

    `headroom_tokens=None` (default): the original fixed cap — always the
    _MAX_SESSIONS most recent summaries, a simple head-slice. `headroom_tokens`
    given: dynamic, capacity-aware trim, same idea as compress_in_session
    above — note the list is newest-first here (opposite of `exchanges`),
    so it's reversed before trim_to_headroom (which trims oldest-first,
    i.e. drops from the end of whatever list it's given) and reversed back
    after, rather than reimplementing the same logic in the other
    direction."""
    if not config.ENABLE_CONTEXT_COMPRESSION:
        return session_history
    if headroom_tokens is None:
        return session_history[:_MAX_SESSIONS]
    oldest_first = list(reversed(session_history))
    kept = token_budget.trim_to_headroom(
        oldest_first, _render_session_summary, headroom_tokens,
        min_keep=_MIN_KEPT_SESSIONS, max_keep=_MAX_KEPT_SESSIONS, model=model,
    )
    return list(reversed(kept))


def compress_session_summary(exchanges: list[dict], payslip_data: dict) -> tuple[dict, LLMCallMetrics | None]:
    """Level 2 — called once when a session ends. Returns (summary,
    metrics) — metrics is None for the no-exchanges early return, since no
    LLM call happens there at all (not "a call that cost zero," an actual
    absence of one — compression/eval.py's harness relies on this
    distinction to avoid reporting a fake $0.00 call as a real data point)."""
    if not exchanges:
        return {
            "payslip_month": payslip_data.get("month", ""),
            "key_changes": [],
            "nudges_given": [],
            "regime_recommendation": "",
        }, None

    user_prompt = (
        f"Payslip snapshot: {json.dumps(payslip_data)}\nSession exchanges: {json.dumps(exchanges)}"
    )
    start = time.perf_counter()
    response = _client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": _SUMMARY_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
    )
    latency_ms = (time.perf_counter() - start) * 1000
    metrics = record_from_response(agent="session_summary", model="gpt-4o-mini", response=response, latency_ms=latency_ms)
    return json.loads(response.choices[0].message.content or "{}"), metrics
