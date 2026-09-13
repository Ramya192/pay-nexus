"""
Pure-Python pieces reused by agents/orchestrator_v2.py — the intent
classifier's system prompt, the capability-gap message, and the
assembler's merge/formatting logic. All of it is zero-LLM Python (except
the prompt string itself, which orchestrator_v2.py's own Agent Framework
classifier calls), unrelated to *how* the agents that feed it actually
run, so none of it needed reimplementing when the orchestration mechanism
(LangGraph -> Microsoft Agent Framework's asyncio.gather-based concurrent
fan-out) changed. See PROJECT_CONTEXT.md §8/§11 for the state shape this
operates on.

This module used to also own the LangGraph StateGraph itself
(orchestrator_node/route_to_agents/build_graph/paynexus_graph) — removed
once api/routes/chat.py no longer imported any of it
(orchestrator_v2.py's stream_paynexus_workflow/run_paynexus_workflow are
the real entry points now). That history is in git log if it's ever needed
again, not preserved here.

Exercised extensively end-to-end against real Postgres/OpenAI credentials
across many rounds of manual and Playwright-driven testing — see README.md
for the dated log of bugs found and fixed that way.
"""

import json

from agents.llm_metrics import summarize as summarize_metrics
from agents.state import PayNexusState

_INTENT_SYSTEM_PROMPT = """Classify a PayNexus user question by which agents must answer it. \
Agents: "payslip" (explaining THIS ONE active payslip — pay changes, HRA/TDS/regime math for the \
current month only, not a multi-month pattern), "regulatory" (about tax law / budget changes / \
general rules, not this user's own numbers or situation), "nudge" (suggestions, savings/\
investment opportunities, 80C/80D/24(b) deduction-gap questions, or ANYTHING about a pattern, \
change, or comparison across more than one month/session of PAYSLIP data — "trend," \
"increasing," "compare my payslips," "over time," "concerning pattern," etc. all mean nudge, even \
though the word "payslip(s)" appears in them, because analyzing multiple payslips together is the \
Nudge agent's job, not the single-payslip agent's), "spending" (bank transactions, purchases, \
where money went, spending by category, recurring merchants/subscriptions, or a trend in \
SPENDING/transactions rather than in payslip figures — this is about uploaded bank statements, \
never about basic/HRA/TDS/bonus, which stay payslip or nudge), "goal" (savings goals specifically \
— a Trip, Home Loan, Education fund, Emergency Fund, Retirement, or any named goal; progress \
toward one, whether the current pace is enough to hit a target date, adding up how much is saved \
across goals — NOT the same as "nudge"'s 80C/tax-deduction savings room, and not "spending"'s \
transaction categories, even though both can come up in the same answer), "budget" (whether \
spending stayed within a per-category monthly budget, overspending alerts, "am I over budget" — \
this is checking actual spend against a user-set TARGET, which is "spending"'s job only when no \
target/limit is involved; "where did my money go" alone is spending, "did I stay under my grocery \
budget" is budget), "whatif" (an explicit HYPOTHETICAL — "what if", "what would happen if", \
"suppose I", "if I were to" — about switching regime, changing a deduction amount, changing a \
budget category's spend, or contributing more to a goal; the deciding signal is the hypothetical \
framing itself, not the topic, since the same topics (regime, budget, goal) are also asked about \
for REAL current state via payslip/nudge/budget/goal — "am I over budget" is budget, "what if I \
cut my budget by ₹1,000" is whatif), "unsupported" (see the strict test below — reserved for an \
actual instruction to change stored data, not any question that happens to mention data that's \
stored).

The word "payslip" alone doesn't mean the "payslip" agent — what matters is whether the question \
is about the one active payslip (→ payslip) or about several payslips / a pattern across them \
(→ nudge). "Do you see any concerning trends in my payslips?" is nudge, not payslip, despite \
containing the word "payslips," because "trends" and "concerning" signal a multi-month pattern \
question. A "trend" question about spending/transactions instead (e.g. "is my spending going up," \
"am I spending more than last month") is "spending," not "nudge" — the deciding factor is whether \
the numbers in question come from a payslip (nudge/payslip) or from bank transactions (spending).

A question can need more than one agent — e.g. "should I switch regimes" needs both payslip and \
nudge; "how much more can I invest to save tax" is nudge alone, not regulatory, because it's \
asking about this user's own remaining room, not the general rule. "Based on my spending, can I \
afford to invest more in 80C" needs both spending (what's actually being spent) and nudge (the \
80C room itself). "Am I saving enough for my trip goal given my spending" needs both goal (the \
target/progress math) and spending (the actual savings rate behind it). "Why am I over my food \
budget" needs both budget (confirming the overage) and spending (explaining what drove it).

STRICT TEST for "unsupported" — apply it only if the message contains an explicit instruction \
verb telling the system to change what's stored: delete, remove, clear, erase, edit, update, \
correct, or add/enter (as in "add this to my profile," not "what have I entered"). If the message \
only asks to see, check, list, summarize, or tell the user something — "do you have," "can you \
tell me," "what is," "do you see," "show me," "list" — it is a question, never "unsupported," \
REGARDLESS of the topic (payslip history, duplicates, savings entered, saved data, account — none \
of these words make a question "unsupported" by themselves). When in doubt, the message is a \
question, not an instruction — "unsupported" should be rare, not a default for anything that \
mentions stored data. Worked examples:
- "do you have my payslip history?" → nudge (a question about saved data — reading, not writing)
- "can you tell me my savings that I have entered?" → nudge (same — asks to recite saved data)
- "do you see any duplicate payslips?" → nudge (a question — asks to look and report)
- "remove the duplicate payslips" → unsupported (instructs a delete)
- "can you check and remove if there are any duplicates" → unsupported (contains the explicit verb \
  "remove" — the "check" half doesn't cancel that removing is the actual instruction)
- "delete my payslip for April" → unsupported
- "clear my saved history" → unsupported
- "where is most of my money going?" → spending
- "what subscriptions am I paying for?" → spending
- "am I spending more on food this month than last?" → spending (a trend, but in transactions, not payslip figures)
- "how close am I to my trip goal?" → goal
- "am I saving fast enough for my home loan down payment?" → goal (progress + pace), not spending alone
- "am I over budget this month?" → budget
- "did I stay under my grocery budget?" → budget, not spending alone (a target is involved)
- "what if I switch to the new regime?" → whatif (hypothetical framing), NOT payslip/nudge — those \
  answer with the user's real, current situation, not a hypothetical
- "what if I invested ₹50,000 more in ELSS?" → whatif
- "what if I cut my food budget by ₹1,000?" → whatif, not budget (budget only checks REAL spend \
  against a REAL saved target; this is a hypothetical change to that target/spend)
- "what if I saved ₹5,000 more a month for my Goa trip?" → whatif, not goal (goal reports real \
  progress; this asks what a hypothetical extra contribution would do)

If recent conversation is given below, use it to resolve what a short follow-up is actually \
about — "consider the payslip history," "what about that," "yes, factor that in" etc. carry no \
topic of their own and must be classified against whatever the previous question/answer in the \
conversation was about, not read as a fresh, unrelated request. E.g. if the prior turn asked for \
a regime recommendation and the new message says "can you consider the payslip history," that's \
still a regime question (payslip, possibly plus nudge) — not a brand-new nudge-only request.

Respond with JSON: {"agents": ["payslip"|"regulatory"|"nudge"|"spending"|"goal"|"budget"|"whatif"|"unsupported", ...]}."""


def capability_gap_node(state: PayNexusState) -> dict:
    """Handles requests none of the three reasoning agents can act on —
    adding, editing, or deleting saved data (duplicate payslips, a payslip
    entry, the financial profile, the account itself). No LLM call: what's
    possible here is fixed and already known, not something worth spending
    a model call guessing at, and a plain, honest answer beats a
    plausible-sounding one that risks implying an action was taken when
    nothing was. Found missing in testing — before this node existed, a
    request like "remove duplicate payslips" was silently misrouted to the
    Nudge agent, which has no delete capability and no way to say so; it
    just answered a different, unrelated question instead.

    No LLM call — what's possible here is fixed and already known, so the
    message below covers every V2 data type generically rather than
    guessing which one the user meant (the intent classifier's "unsupported"
    bucket doesn't preserve a topic to key off of, and a keyword guess here
    risks being confidently wrong for an ambiguous phrasing). Also fixed
    from an earlier version that said "sidebar" — the sidebar was replaced
    by tabs (components/Dashboard/TabbedPanel.tsx) and this message wasn't
    updated at the time, a real found-in-testing staleness bug."""
    return {
        "unsupported_response": (
            "I can't add, edit, or delete your saved data from a chat message — that's kept as "
            "an explicit action you take, not something an agent decides on its own. Use whichever "
            "tab holds what you're trying to change: Bank statements, Payslip history, and Goals "
            "each list your saved entries with their own Delete button (Payslip history also has a "
            "\"Remove duplicates\" button); Budget doesn't have a delete — just edit the numbers "
            "directly on its own tab."
        )
    }


def _format_agent_response(raw: str) -> str:
    """Payslip Reasoning (Agent 1) always returns structured JSON — good for
    the API contract (§2), unreadable dumped raw into a chat bubble. If
    `raw` parses as an object with an "explanation" key, render it as prose
    plus a bullet list of follow-up suggestions; otherwise (Agent 2/3,
    which already return plain text, or a malformed payload) return it
    unchanged rather than guess at a shape that isn't there."""
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw

    if not isinstance(parsed, dict) or "explanation" not in parsed:
        return raw

    parts = [parsed["explanation"]]
    suggestions = parsed.get("follow_up_suggestions")
    if suggestions:
        # Labeled explicitly — found in testing that a bare bullet list
        # right after the explanation reads ambiguously (more facts? a
        # checklist?) with nothing marking it as suggested next questions.
        parts.append("You can ask more like:\n" + "\n".join(f"• {s}" for s in suggestions))
    return "\n\n".join(parts)


_NULL_LOOKING_STRINGS = {"null", "none", "n/a", "na", "-", ""}


def _parse_nudge(raw: str) -> dict | None:
    """Agent 3 also returns structured JSON now — {title, detail, impact},
    matching frontend/src/components/NudgeCard/NudgeCard.tsx's `Nudge`
    shape. Returns None (not the raw string) on anything that doesn't
    parse as that shape, so the caller can fall back to showing the raw
    text rather than silently dropping content the model did produce."""
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(parsed, dict) or "title" not in parsed or "detail" not in parsed:
        return None
    return {"title": parsed["title"], "detail": parsed["detail"], "impact": _normalize_impact(parsed.get("impact"))}


def _normalize_impact(impact) -> str | None:
    """The prompt asks for the JSON literal `null` when there's no impact
    figure, but a JSON-mode model can instead emit the STRING "null" (or
    "None"/"N/A") — valid JSON, wrong value: a real, observed case where
    NudgeCard.tsx's `{nudge.impact && <p>...}` check saw a truthy non-empty
    string and rendered the literal word "null" in the card. Collapses any
    of these look-alikes to a real None so the frontend's existing falsy
    check works as intended, rather than patching the check in two places."""
    if isinstance(impact, str) and impact.strip().lower() in _NULL_LOOKING_STRINGS:
        return None
    return impact


def assembler_node(state: PayNexusState) -> dict:
    """Merges whichever agent responses actually ran into one
    final_response and tags which agent(s) produced it, for the frontend's
    agent indicator (§10). The Nudge Agent's output is additionally exposed
    as a separate structured `nudge_card`, for the frontend to render as
    its own NudgeCard component rather than inline prose (§10's component
    tree treats it as a distinct UI element) — the prose section still gets
    a one-line pointer so the chat bubble is never empty when nudge is the
    only agent that ran."""
    sections = []
    active = []
    nudge_card = None

    if state.get("payslip_response"):
        sections.append(("Payslip Reasoning Agent", _format_agent_response(state["payslip_response"])))
        active.append("payslip_agent")
    if state.get("regulatory_response"):
        sections.append(("Regulatory Intelligence Agent", state["regulatory_response"]))
        active.append("regulatory_agent")
    if state.get("nudge_response"):
        nudge_card = _parse_nudge(state["nudge_response"])
        nudge_text = f"💡 {nudge_card['title']}" if nudge_card else state["nudge_response"]
        # Display label only — internal node name stays "nudge_agent"
        # (agents/nudge_agent.py, active_agent value, etc.); "Savings
        # Advisor" is just clearer UI copy than "Nudge Agent".
        sections.append(("Savings Advisor", nudge_text))
        active.append("nudge_agent")
    if state.get("spending_response"):
        sections.append(("SpendingAnalyser Agent", _format_agent_response(state["spending_response"])))
        active.append("spending_agent")
    if state.get("goal_response"):
        sections.append(("GoalTracker Agent", _format_agent_response(state["goal_response"])))
        active.append("goal_agent")
    if state.get("budget_response"):
        sections.append(("BudgetPlanner Agent", _format_agent_response(state["budget_response"])))
        active.append("budget_agent")
    if state.get("scenario_response"):
        sections.append(("Foresight Agent", _format_agent_response(state["scenario_response"])))
        active.append("whatif_agent")
    if state.get("unsupported_response"):
        # Not one of the three reasoning agents, so no "[Name] reasoned
        # about your data" framing — plain "PayNexus" label, since nothing
        # was actually reasoned over here.
        sections.append(("PayNexus", state["unsupported_response"]))
        active.append("capability_gap_node")

    if not sections:
        # Graceful fallback (§4) — an agent failing shouldn't surface a raw exception.
        final = (
            "Something went wrong reasoning over that — none of the agents returned a "
            "response. Try rephrasing the question."
        )
    else:
        final = "\n\n".join(f"[{name}]\n{content}" for name, content in sections)

    # Built entirely in Python by the agent nodes (tax_calculations.py /
    # payslip_trends.py table builders) — never by the LLM — and merged
    # here so the frontend can render real tables instead of the agent
    # re-stating every rupee figure as prose. See agents/tables.py.
    #
    # De-duplicated by content, not just concatenated: payslip_agent.py and
    # nudge_agent.py both independently compute the "gaps" and "liability"
    # tables (each needs its own copy to reason from) and each has its own
    # LLM call independently deciding whether to show it — so on a
    # multi-agent question, both can pick the same one, and the identical
    # table rendered twice in the same response was a real, observed bug
    # (a user's "recommend a tax regime" showing the exact same "Tax
    # liability estimate" table back to back). Dict-keyed-by-JSON dedup
    # rather than a title check, since a title collision alone wouldn't
    # prove the rows are actually identical.
    seen_tables: dict[str, dict] = {}
    for table in (
        (state.get("payslip_tables") or [])
        + (state.get("nudge_tables") or [])
        + (state.get("regulatory_tables") or [])
        + (state.get("spending_tables") or [])
        + (state.get("goal_tables") or [])
        + (state.get("budget_tables") or [])
        + (state.get("scenario_tables") or [])
    ):
        seen_tables[json.dumps(table, sort_keys=True)] = table
    tables = list(seen_tables.values())

    # Every LLM call this turn actually made, aggregated — see
    # agents/llm_metrics.py. orchestrator_llm_calls is always present (the
    # intent classifier runs every turn, from orchestrator_v2.classify_intent
    # — see that module); the other seven only when that agent actually ran.
    all_calls = (
        (state.get("orchestrator_llm_calls") or [])
        + (state.get("payslip_llm_calls") or [])
        + (state.get("regulatory_llm_calls") or [])
        + (state.get("nudge_llm_calls") or [])
        + (state.get("spending_llm_calls") or [])
        + (state.get("goal_llm_calls") or [])
        + (state.get("budget_llm_calls") or [])
        + (state.get("scenario_llm_calls") or [])
    )

    return {
        "final_response": final,
        "active_agent": ",".join(active),
        "nudge_card": nudge_card,
        "tables": tables,
        "token_usage": summarize_metrics(all_calls),
    }
