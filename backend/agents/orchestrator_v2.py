"""
Orchestrator — replaces the original agents/orchestrator.py's LangGraph
StateGraph fan-out/fan-in with Agent Framework's structured-output intent
classifier + plain asyncio concurrency for the fan-out itself.

Deliberately reuses agents/orchestrator.py's assembler_node/
capability_gap_node UNCHANGED rather than reimplementing them — those are
pure-Python merge/formatting logic with zero LLM calls, already covered by
tests/test_orchestrator_assembler.py, and completely orthogonal to *how*
the agents that feed them actually ran. Only the orchestration mechanism
(intent classification, concurrent fan-out) changes here; every agent node
function is called exactly as it was before.

**Multi-agent execution does NOT use agent_framework_orchestrations'
ConcurrentBuilder, despite an earlier version of this module doing exactly
that.** Found via live reproduction, not assumed: running 2 real agents
(payslip_agent + nudge_agent, both internally bridging to their own
asyncio.run() call via asyncio.to_thread, same pattern every agent node
uses) through a real ConcurrentBuilder Workflow deadlocked completely
inside the actual FastAPI/uvicorn server — a genuine hang, not slowness,
confirmed via a direct curl against the live server that produced both
"agent_active" events and then nothing for 90+ seconds, with the process's
own thread count staying flat (ruling out a thread leak/exhaustion
explanation). The exact same 2-agent combination run in an isolated
`asyncio.run(main())` script outside uvicorn did NOT hang — the agent
logic itself completed correctly in ~14 seconds — pointing at an
interaction between ConcurrentBuilder's own Workflow/dispatcher engine and
an already-running event loop (uvicorn's) specifically, not a bug in
PayNexus's own agent logic. Root cause not chased further into
agent_framework_orchestrations' internals (third-party library, out of
scope) once a reliable fix was in hand.

**Fix**: run every selected agent directly via `asyncio.gather` over
`asyncio.to_thread` (see `_run_agents_concurrently` below) — same real
concurrency (each agent's own Foundry call genuinely overlaps in wall
time), zero ConcurrentBuilder/Workflow engine anywhere in the picture.
Bonus: this also deletes the old `_AgentExecutor`/`_aggregate` machinery's
entire reason for existing — that machinery's JSON-text-message round trip
was only needed because ConcurrentBuilder's fan-in could only carry chat
messages between participants, not a plain Python dict; a direct
asyncio.gather already hands back real dicts with real LLMCallMetrics
objects inside, so nothing needs to serialize through JSON at all anymore.
Also removed the old ConcurrentBuilder-specific single-vs-multi-agent
special-casing (its FanOutEdgeGroup hard-required ≥2 participants, which
no longer applies to anything since nothing here uses it) — one agent or
several now go through the exact same code path.
"""

import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Callable, Literal

from pydantic import BaseModel

from agents.agent_framework_llm import agent_complete
from agents.budget_agent import budget_agent_node
from agents.conversation import format_conversation_for_prompt
from agents.goal_agent import goal_agent_node
from agents.llm_metrics import LLMCallMetrics
from agents.nudge_agent import nudge_agent_node
from agents.orchestrator import _INTENT_SYSTEM_PROMPT, assembler_node, capability_gap_node
from agents.payslip_agent import payslip_agent_node
from agents.regulatory_agent import regulatory_agent_node
from agents.spending_agent import spending_agent_node
from agents.state import PayNexusState
from agents.whatif_agent import whatif_agent_node
from compression import token_budget
from compression.context_compressor import cap_session_history, compress_in_session
from config import config

AgentKey = Literal["payslip", "regulatory", "nudge", "spending", "goal", "budget", "whatif", "unsupported"]

# Same key set orchestrator.py's _AGENT_KEY_TO_NODE used, now mapping
# directly to the node function object instead of a LangGraph node-name
# string — "unsupported" maps to the same no-LLM capability_gap_node every
# other key maps to a real node, so no special-casing is needed anywhere
# below: every participant is uniformly "some sync PayNexusState -> dict
# callable," whether or not it happens to make an LLM call internally.
# Matches orchestrator.py's _AGENT_KEY_TO_NODE dict's VALUES exactly — the
# old LangGraph node names, which is what api/routes/chat.py's SSE
# "agent_active" events historically carried as their "agent" field (the
# raw graph step-dict keys) — so a frontend watching for "budget_agent" in
# the SSE stream sees no difference from before.
AGENT_KEY_TO_DISPLAY_ID: dict[str, str] = {
    "payslip": "payslip_agent",
    "regulatory": "regulatory_agent",
    "nudge": "nudge_agent",
    "spending": "spending_agent",
    "goal": "goal_agent",
    "budget": "budget_agent",
    "whatif": "whatif_agent",
    "unsupported": "capability_gap_node",
}

DEFAULT_AGENT_NODE_MAP: dict[str, Callable[[PayNexusState], dict]] = {
    "payslip": payslip_agent_node,
    "regulatory": regulatory_agent_node,
    "nudge": nudge_agent_node,
    "spending": spending_agent_node,
    "goal": goal_agent_node,
    "budget": budget_agent_node,
    "whatif": whatif_agent_node,
    "unsupported": capability_gap_node,
}


# Real (config-declared) model each agent key resolves to on its cloud
# path — used ONLY to size how much conversation/session-history headroom
# a turn actually has (compression/token_budget.py), never to route the
# real call: every agent module already reads its own config.*_AGENT_MODEL
# constant directly, unaffected by this dict. "unsupported" maps to
# capability_gap_node, which makes no LLM call at all — any real model
# name is inert there; PAYSLIP_AGENT_MODEL is picked only so this dict has
# no missing key to guard against.
AGENT_KEY_TO_MODEL: dict[str, str] = {
    "payslip": config.PAYSLIP_AGENT_MODEL,
    "regulatory": config.REGULATORY_AGENT_MODEL,
    "nudge": config.NUDGE_AGENT_MODEL,
    "spending": config.SPENDING_AGENT_MODEL,
    "goal": config.GOAL_AGENT_MODEL,
    "budget": config.BUDGET_AGENT_MODEL,
    "whatif": config.WHATIF_AGENT_MODEL,
    "unsupported": config.PAYSLIP_AGENT_MODEL,
}

# The hybrid-tier agents (agent_framework_llm.hybrid_agent_complete*) can
# be served by Ollama's local phi4-mini instead of their cloud model
# whenever config.USE_LOCAL_SLM is on — that's the actual routing this
# app does (agents/agent_framework_llm.py), unchanged here. Anything in
# this set is a candidate for phi4-mini's much smaller window this turn.
_HYBRID_TIER_MODELS = {config.REGULATORY_AGENT_MODEL, config.NUDGE_AGENT_MODEL, config.GOAL_AGENT_MODEL, config.BUDGET_AGENT_MODEL}


def _context_window_for_turn(agent_keys: list[str]) -> tuple[int, str]:
    """The tightest real context window any agent selected THIS turn could
    actually be served by — the real capacity ceiling compression should
    budget against, not a flat guess. Counts phi4-mini's window as a
    possibility for every hybrid-tier key whenever config.USE_LOCAL_SLM is
    on, since that's what actually forces headroom down to the small end
    when local routing is enabled — a coincidence of which agent got
    picked would otherwise silently give a hybrid-tier turn far more
    headroom than the model that might really serve it can support.
    Returns (window, model_name) — the model name purely for traceability
    (logging/debugging which model actually set the ceiling), same spirit
    as every other *_AS_OF/labeled-estimate constant in this codebase."""
    candidates: list[tuple[int, str]] = []
    for key in agent_keys:
        model = AGENT_KEY_TO_MODEL.get(key, config.PAYSLIP_AGENT_MODEL)
        deployment = config.FOUNDRY_DEPLOYMENT_MAP.get(model, model)
        candidates.append((token_budget.context_window_for(deployment), deployment))
        if config.USE_LOCAL_SLM and model in _HYBRID_TIER_MODELS:
            candidates.append((token_budget.context_window_for("phi4-mini"), "phi4-mini"))
    if not candidates:
        # classify_intent's own fallback already guarantees agent_keys is
        # never actually empty by the time this is called ("payslip" if
        # nothing usable came back) — this mirrors that same fallback
        # rather than assuming it, so this function stays correct even if
        # called standalone (e.g. from a test) with an empty list.
        candidates.append((token_budget.context_window_for(config.PAYSLIP_AGENT_MODEL), config.PAYSLIP_AGENT_MODEL))
    return min(candidates, key=lambda c: c[0])


class IntentClassification(BaseModel):
    """Structured-output replacement for the original orchestrator_node
    manually json.loads()-ing the
    classifier's response and filtering to known keys by hand. A model
    that hallucinates an out-of-enum value now fails validation outright
    (surfaced as the same "nothing usable" fallback below) instead of
    silently passing through filtered by a plain `if a in _AGENT_KEY_TO_NODE`
    check."""

    agents: list[AgentKey]


async def classify_intent(state: PayNexusState) -> tuple[list[str], PayNexusState, LLMCallMetrics]:
    """Structured-output replacement for orchestrator_node's classification
    call. Same system prompt (imported unchanged from orchestrator.py),
    same conversation-history compression/capping applied BEFORE
    classification, same "default to payslip" fallback when nothing usable
    comes back.

    Returns (agent_keys, effective_state, classifier_metrics) — effective_state
    is `state` with `conversation`/`session_history` replaced by their
    compressed/capped versions, exactly what orchestrator_node used to merge
    back into LangGraph's shared state before fan-out; every agent's node
    function reads state["conversation"]/state["session_history"] directly,
    so this new state (not the raw input) is what gets handed to each
    participant executor below.

    Compression happens in two passes now (2026-09-12), not one: agent_keys
    don't exist yet at the point the classifier itself needs sized input,
    so that pass uses the old fixed window (compress_in_session's
    `headroom_tokens=None` mode) — ORCHESTRATOR_MODEL is gpt-4o (128K
    tokens), so a small fixed window here never risks actually running
    short for a request this size. Once agent_keys comes back, the SHARED
    conversation/session_history every fanned-out agent receives gets a
    second, dynamic pass sized against the tightest real context window
    among those specific agents (_context_window_for_turn) — trimmed from
    the RAW input, not from the classifier's already-trimmed copy, so this
    isn't compounding one trim on top of another.
    """
    raw_conversation = state.get("conversation") or []
    raw_session_history = state.get("session_history") or []

    conversation_for_classifier = compress_in_session(raw_conversation)
    classifier_input = state["user_query"]
    conversation_block = format_conversation_for_prompt(conversation_for_classifier)
    if conversation_block:
        classifier_input = f"{conversation_block}\n\nNew question: {state['user_query']}"

    raw, metrics = await agent_complete(
        _INTENT_SYSTEM_PROMPT,
        classifier_input,
        model=config.ORCHESTRATOR_MODEL,
        response_model=IntentClassification,
        agent="orchestrator_classifier",
        check_for_generic_response=False,
    )
    try:
        agent_keys = json.loads(raw).get("agents") or []
    except (json.JSONDecodeError, TypeError, AttributeError):
        agent_keys = []
    if not agent_keys:
        agent_keys = ["payslip"]

    context_window, limiting_model = _context_window_for_turn(agent_keys)
    headroom = token_budget.headroom_tokens(context_window)
    conversation = compress_in_session(raw_conversation, headroom_tokens=headroom, model=limiting_model)
    session_history = cap_session_history(raw_session_history, headroom_tokens=headroom, model=limiting_model)

    effective_state: PayNexusState = {**state, "conversation": conversation, "session_history": session_history}
    return agent_keys, effective_state, metrics


async def _run_agents_concurrently(
    agent_keys: list[str],
    effective_state: PayNexusState,
    node_map: dict[str, Callable[[PayNexusState], dict]],
    classifier_metrics: LLMCallMetrics,
) -> dict:
    """Runs every selected agent's (synchronous) node function concurrently
    via asyncio.gather over asyncio.to_thread, merges their state-partial
    dicts, and hands the result to the EXISTING, unchanged assembler_node
    (see module docstring for why that's reused rather than reimplemented,
    and for why this exists instead of agent_framework_orchestrations'
    ConcurrentBuilder). Works identically for 1 agent or several — no
    special-casing needed, unlike the ConcurrentBuilder-based version this
    replaced."""
    node_results = await asyncio.gather(*(asyncio.to_thread(node_map[key], effective_state) for key in agent_keys))
    merged: dict = {"orchestrator_llm_calls": [classifier_metrics]}
    for node_result in node_results:
        merged.update(node_result)
    return assembler_node(merged)


async def run_paynexus_workflow(
    state: PayNexusState, agent_node_map: dict[str, Callable[[PayNexusState], dict]] = None
) -> dict:
    """Top-level replacement for `paynexus_graph.invoke(state)` — classifies
    intent, fans out concurrently to whichever agents were selected, and
    returns the exact same {final_response, active_agent, nudge_card,
    tables, token_usage} shape assembler_node always produced.
    `agent_node_map` defaults to DEFAULT_AGENT_NODE_MAP; tests override it
    with fakes to exercise the orchestration/fan-out/merge logic itself
    without real LLM calls."""
    node_map = agent_node_map if agent_node_map is not None else DEFAULT_AGENT_NODE_MAP
    agent_keys, effective_state, classifier_metrics = await classify_intent(state)
    return await _run_agents_concurrently(agent_keys, effective_state, node_map, classifier_metrics)


async def stream_paynexus_workflow(
    state: PayNexusState, agent_node_map: dict[str, Callable[[PayNexusState], dict]] = None
) -> AsyncGenerator[dict, None]:
    """Streaming counterpart to run_paynexus_workflow() — the direct
    replacement for api/routes/chat.py's `paynexus_graph.stream(state,
    stream_mode="updates")`. Yields plain dicts, not SSE-formatted text;
    the API layer's own _sse() formatting is unchanged (see chat.py) — this
    module stays free of HTTP-specific concerns.

    Yields exactly the same two logical events the old LangGraph-based
    route did: one {"kind": "agent_active", "agent": <display id>} per
    selected agent, then exactly one {"kind": "final", **assembler_node's
    output} at the end.

    Every "agent_active" event fires immediately, for the WHOLE selected set
    at once, before any of them actually run — not one-by-one as each agent
    *finishes* (an earlier version did that for the multi-agent case). That
    was real completion-order information, but genuinely misleading in the
    UI: a user watching a 2-agent turn would see a frozen "X reasoning…"
    label naming whichever agent happened to finish FIRST, with zero
    indication that a different, slower agent was the one actually still
    running — the label looked like live status but was actually a
    completion log entry. Emitting the whole known set upfront (which the
    single-agent case always did, since there was only ever one agent to
    name) makes the indicator honest for the multi-agent case too, at the
    cost of losing the real per-agent completion timing — a trade worth
    making since nothing downstream consumed that timing for anything but
    this misleading display.
    """
    node_map = agent_node_map if agent_node_map is not None else DEFAULT_AGENT_NODE_MAP
    agent_keys, effective_state, classifier_metrics = await classify_intent(state)
    for key in agent_keys:
        yield {"kind": "agent_active", "agent": AGENT_KEY_TO_DISPLAY_ID[key]}

    final = await _run_agents_concurrently(agent_keys, effective_state, node_map, classifier_metrics)
    yield {"kind": "final", **final}
