"""
Agent 4 — Orchestrator. LangGraph StateGraph: classifies intent, compresses
session history, fans the query out to whichever of the three reasoning
agents it needs (in parallel), then merges their outputs at the assembler
node. See PROJECT_CONTEXT.md §8 for the state shape and graph sketch this
implements, and §11 for where this fits (backend/agents/orchestrator.py).

Not yet exercised end-to-end — no test harness or running Postgres/OpenAI
key in this environment, so treat `paynexus_graph.invoke(...)` as unverified
until it's run against real credentials.
"""

import json
import logging

from langgraph.graph import END, StateGraph
from openai import OpenAI

from agents.nudge_agent import nudge_agent_node
from agents.payslip_agent import payslip_agent_node
from agents.regulatory_agent import regulatory_agent_node
from agents.state import PayNexusState
from compression.context_compressor import compress_in_session
from config import config

logger = logging.getLogger(__name__)
_client = OpenAI(api_key=config.OPENAI_API_KEY)

_INTENT_SYSTEM_PROMPT = """Classify a PayNexus user question by which agents must answer it. \
Agents: "payslip" (needs the user's own payslip numbers — pay changes, HRA/TDS/regime math), \
"regulatory" (about tax law / budget changes / rules in general, not this user's numbers), \
"nudge" (asks for suggestions, opportunities, or references past sessions/trends). A question \
can need more than one — e.g. "should I switch regimes" needs both payslip and nudge. Respond \
with JSON: {"agents": ["payslip"|"regulatory"|"nudge", ...]}."""

_AGENT_KEY_TO_NODE = {
    "payslip": "payslip_agent",
    "regulatory": "regulatory_agent",
    "nudge": "nudge_agent",
}
_ALL_AGENT_NODES = list(_AGENT_KEY_TO_NODE.values())


def orchestrator_node(state: PayNexusState) -> dict:
    """Classifies intent and, if enabled, compresses session history before
    any agent sees it — the two things the Orchestrator does before
    fan-out (§4)."""
    response = _client.chat.completions.create(
        model=config.ORCHESTRATOR_MODEL,
        messages=[
            {"role": "system", "content": _INTENT_SYSTEM_PROMPT},
            {"role": "user", "content": state["user_query"]},
        ],
        response_format={"type": "json_object"},
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

    update: dict = {
        "intent": "multi" if len(agent_keys) > 1 else agent_keys[0],
        "agents_to_invoke": [_AGENT_KEY_TO_NODE[k] for k in agent_keys],
    }
    if config.ENABLE_CONTEXT_COMPRESSION and state.get("session_history"):
        update["session_history"] = compress_in_session(state["session_history"])
    return update


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
    return {"title": parsed["title"], "detail": parsed["detail"], "impact": parsed.get("impact")}


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
        sections.append(("Financial Nudge Agent", nudge_text))
        active.append("nudge_agent")

    if not sections:
        # Graceful fallback (§4) — an agent failing shouldn't surface a raw exception.
        final = (
            "Something went wrong reasoning over that — none of the agents returned a "
            "response. Try rephrasing the question."
        )
    else:
        final = "\n\n".join(f"[{name}]\n{content}" for name, content in sections)

    return {"final_response": final, "active_agent": ",".join(active), "nudge_card": nudge_card}


def build_graph():
    graph = StateGraph(PayNexusState)
    graph.add_node("orchestrator", orchestrator_node)
    graph.add_node("payslip_agent", payslip_agent_node)
    graph.add_node("regulatory_agent", regulatory_agent_node)
    graph.add_node("nudge_agent", nudge_agent_node)
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
