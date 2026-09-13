"""
Agent 4 — Orchestrator. LangGraph StateGraph: classifies intent, compresses
session history, fans the query out to whichever of the three reasoning
agents it needs (in parallel), then merges their outputs at the assembler
node. See PROJECT_CONTEXT.md §8 for the state shape and graph sketch this
implements, and §11 for where this fits (backend/agents/orchestrator.py).

Exercised extensively end-to-end against real Postgres/OpenAI credentials
across many rounds of manual and Playwright-driven testing — see README.md
for the dated log of bugs found and fixed that way.
"""

import json
import logging
import time

from langgraph.graph import END, StateGraph
from openai import OpenAI

from agents.conversation import format_conversation_for_prompt
from agents.llm_metrics import record_from_response
from agents.llm_metrics import summarize as summarize_metrics
from agents.nudge_agent import nudge_agent_node
from agents.payslip_agent import payslip_agent_node
from agents.regulatory_agent import regulatory_agent_node
from agents.state import PayNexusState
from compression.context_compressor import cap_session_history, compress_in_session
from config import config

logger = logging.getLogger(__name__)
_client = OpenAI(api_key=config.OPENAI_API_KEY)

_INTENT_SYSTEM_PROMPT = """Classify a PayNexus user question by which agents must answer it. \
Agents: "payslip" (explaining THIS ONE active payslip — pay changes, HRA/TDS/regime math for the \
current month only, not a multi-month pattern), "regulatory" (about tax law / budget changes / \
general rules, not this user's own numbers or situation), "nudge" (suggestions, savings/\
investment opportunities, 80C/80D/24(b) deduction-gap questions, or ANYTHING about a pattern, \
change, or comparison across more than one month/session — "trend," "increasing," "compare my \
payslips," "over time," "concerning pattern," etc. all mean nudge, even though the word \
"payslip(s)" appears in them, because analyzing multiple payslips together is the Nudge agent's \
job, not the single-payslip agent's), "unsupported" (see the strict test below — reserved for an \
actual instruction to change stored data, not any question that happens to mention data that's \
stored).

The word "payslip" alone doesn't mean the "payslip" agent — what matters is whether the question \
is about the one active payslip (→ payslip) or about several payslips / a pattern across them \
(→ nudge). "Do you see any concerning trends in my payslips?" is nudge, not payslip, despite \
containing the word "payslips," because "trends" and "concerning" signal a multi-month pattern \
question.

A question can need more than one agent — e.g. "should I switch regimes" needs both payslip and \
nudge; "how much more can I invest to save tax" is nudge alone, not regulatory, because it's \
asking about this user's own remaining room, not the general rule.

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

If recent conversation is given below, use it to resolve what a short follow-up is actually \
about — "consider the payslip history," "what about that," "yes, factor that in" etc. carry no \
topic of their own and must be classified against whatever the previous question/answer in the \
conversation was about, not read as a fresh, unrelated request. E.g. if the prior turn asked for \
a regime recommendation and the new message says "can you consider the payslip history," that's \
still a regime question (payslip, possibly plus nudge) — not a brand-new nudge-only request.

Respond with JSON: {"agents": ["payslip"|"regulatory"|"nudge"|"unsupported", ...]}."""

_AGENT_KEY_TO_NODE = {
    "payslip": "payslip_agent",
    "regulatory": "regulatory_agent",
    "nudge": "nudge_agent",
    "unsupported": "capability_gap_node",
}
_ALL_AGENT_NODES = list(_AGENT_KEY_TO_NODE.values())


def orchestrator_node(state: PayNexusState) -> dict:
    """Classifies intent — using this session's recent conversation to
    resolve follow-ups, not just the new message in isolation — and, if
    enabled, applies Level 1 sliding-window compression (§6) to that same
    conversation before any agent sees it. (Previously this compression
    was applied to session_history — the cross-session summaries — by
    mistake; §6 always meant it for live in-session exchanges, which is
    what `conversation` is.) Also caps how many past session summaries
    stay in play (cap_session_history) — GET /payslip/history returns
    every summary a user has ever had with no limit, so without this,
    session_history grows every session, forever. Three things the
    Orchestrator does before fan-out (§4)."""
    conversation = state.get("conversation") or []
    if config.ENABLE_CONTEXT_COMPRESSION and conversation:
        conversation = compress_in_session(conversation)

    session_history = cap_session_history(state.get("session_history") or [])

    classifier_input = state["user_query"]
    conversation_block = format_conversation_for_prompt(conversation)
    if conversation_block:
        classifier_input = f"{conversation_block}\n\nNew question: {state['user_query']}"

    start = time.perf_counter()
    response = _client.chat.completions.create(
        model=config.ORCHESTRATOR_MODEL,
        messages=[
            {"role": "system", "content": _INTENT_SYSTEM_PROMPT},
            {"role": "user", "content": classifier_input},
        ],
        response_format={"type": "json_object"},
    )
    latency_ms = (time.perf_counter() - start) * 1000
    metrics = record_from_response(
        agent="orchestrator_classifier", model=config.ORCHESTRATOR_MODEL, response=response, latency_ms=latency_ms
    )

    agent_keys: list[str] = []
    try:
        parsed = json.loads(response.choices[0].message.content or "{}")
        agent_keys = [a for a in parsed.get("agents", []) if a in _AGENT_KEY_TO_NODE]
    except (json.JSONDecodeError, TypeError, AttributeError):
        pass

    if not agent_keys:
        logger.warning("Intent classification returned nothing usable — defaulting to payslip agent.")
        agent_keys = ["payslip"]

    return {
        "intent": "multi" if len(agent_keys) > 1 else agent_keys[0],
        "agents_to_invoke": [_AGENT_KEY_TO_NODE[k] for k in agent_keys],
        "conversation": conversation,
        "session_history": session_history,
        "orchestrator_llm_calls": [metrics],
    }


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
    just answered a different, unrelated question instead."""
    return {
        "unsupported_response": (
            "I can't add, edit, or delete your saved data from a chat message — that's kept as "
            "an explicit action you take, not something an agent decides on its own. Open the "
            "Payslip history section in the sidebar: each saved month has its own delete button, "
            "and a \"Remove duplicates\" button clears out repeat entries for the same month, "
            "keeping the most recently saved one."
        )
    }


def route_to_agents(state: PayNexusState) -> list[str]:
    """Conditional edge: fans out to every agent the orchestrator selected,
    in parallel. LangGraph runs each returned node in the same super-step
    and holds the shared downstream node (assembler) until all of them
    finish — standard fan-out/fan-in, no extra join logic needed here."""
    return state.get("agents_to_invoke") or ["payslip_agent"]


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
        parts.append("\n".join(f"• {s}" for s in suggestions))
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
    ):
        seen_tables[json.dumps(table, sort_keys=True)] = table
    tables = list(seen_tables.values())

    # Every LLM call this turn actually made, aggregated — see
    # agents/llm_metrics.py. orchestrator_llm_calls is always present (the
    # intent classifier runs every turn); the other three only when that
    # agent actually ran, per route_to_agents' fan-out.
    all_calls = (
        (state.get("orchestrator_llm_calls") or [])
        + (state.get("payslip_llm_calls") or [])
        + (state.get("regulatory_llm_calls") or [])
        + (state.get("nudge_llm_calls") or [])
    )

    return {
        "final_response": final,
        "active_agent": ",".join(active),
        "nudge_card": nudge_card,
        "tables": tables,
        "token_usage": summarize_metrics(all_calls),
    }


def build_graph():
    graph = StateGraph(PayNexusState)
    graph.add_node("orchestrator", orchestrator_node)
    graph.add_node("payslip_agent", payslip_agent_node)
    graph.add_node("regulatory_agent", regulatory_agent_node)
    graph.add_node("nudge_agent", nudge_agent_node)
    graph.add_node("capability_gap_node", capability_gap_node)
    graph.add_node("assembler", assembler_node)

    graph.set_entry_point("orchestrator")
    graph.add_conditional_edges("orchestrator", route_to_agents, _ALL_AGENT_NODES)
    for agent_node in _ALL_AGENT_NODES:
        graph.add_edge(agent_node, "assembler")
    graph.add_edge("assembler", END)

    return graph.compile()


# Compiled once at import time — the API layer (Phase 4) imports this
# directly: `from agents.orchestrator import paynexus_graph`.
paynexus_graph = build_graph()
