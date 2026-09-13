"""
Orchestrator — replaces the original agents/orchestrator.py's LangGraph
StateGraph fan-out/fan-in with agent_framework_orchestrations'
ConcurrentBuilder + custom, privacy-scoped executors.

Deliberately reuses agents/orchestrator.py's assembler_node/
capability_gap_node UNCHANGED rather than reimplementing them — those are
pure-Python merge/formatting logic with zero LLM calls, already covered by
tests/test_orchestrator_assembler.py, and completely orthogonal to *how*
the agents that feed them actually ran. Only the orchestration mechanism
(intent classification, concurrent fan-out) changes here; every agent node
function is called exactly as it was before.

Why a custom executor instead of bare Agent participants in ConcurrentBuilder:
ConcurrentBuilder's default dispatcher broadcasts ONE shared input message
to every participant, but each PayNexus agent needs a different,
privacy-scoped slice of state (e.g. regulatory_agent must never see
financial data at all). Each _AgentExecutor below ignores the broadcast
entirely and instead runs its own node function against a closure-captured
state dict.

Why asyncio.to_thread inside the executor: every node function stays
synchronous — it bridges to its own async Agent Framework call via
asyncio.run() internally. This executor's own handler must be async
(Workflow requirement), and asyncio.run() cannot be called from inside an
already-running event loop — asyncio.to_thread runs the sync node function
in a worker thread instead, sidestepping that exactly the way
api/routes/chat.py's FastAPI threadpool already does.

Why AgentExecutorResponse carries JSON text, not a real chat exchange:
ConcurrentBuilder's fan-in only knows how to carry AgentExecutorResponse/
Message objects between participants and the aggregator. What's actually
flowing here isn't a chat message at all — it's a state-partial dict (e.g.
{"budget_response": ..., "budget_tables": ..., "budget_llm_calls": [...]})
— so each executor JSON-encodes its dict into a single assistant message's
text, and the custom aggregator is the only thing that ever decodes it
back out.
"""

import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Callable, Literal

from agent_framework import (
    AgentExecutorRequest,
    AgentExecutorResponse,
    AgentResponse,
    Executor,
    Message,
    WorkflowContext,
    handler,
)
from agent_framework_orchestrations import ConcurrentBuilder
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
# raw graph step-dict keys). Reused here as each _AgentExecutor's `id`, so
# the workflow's own "executor_completed" events (see
# stream_paynexus_workflow below) naturally carry the identical names — a
# frontend watching for "budget_agent" in the SSE stream sees no difference
# from before.
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
    """
    conversation = state.get("conversation") or []
    if config.ENABLE_CONTEXT_COMPRESSION and conversation:
        conversation = compress_in_session(conversation)
    session_history = cap_session_history(state.get("session_history") or [])

    classifier_input = state["user_query"]
    conversation_block = format_conversation_for_prompt(conversation)
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

    effective_state: PayNexusState = {**state, "conversation": conversation, "session_history": session_history}
    return agent_keys, effective_state, metrics


class _AgentExecutor(Executor):
    """See module docstring for why this ignores the broadcast input and
    why it carries a plain dict through as JSON message text."""

    def __init__(self, id: str, node_fn: Callable[[PayNexusState], dict], state: PayNexusState) -> None:
        super().__init__(id)
        self._node_fn = node_fn
        self._state = state

    @handler
    async def run(self, request: AgentExecutorRequest, ctx: WorkflowContext[AgentExecutorResponse]) -> None:
        result: dict = await asyncio.to_thread(self._node_fn, self._state)
        text = json.dumps(result, default=lambda o: o.model_dump() if hasattr(o, "model_dump") else str(o))
        await ctx.send_message(
            AgentExecutorResponse(
                executor_id=self.id,
                agent_response=AgentResponse(messages=[Message("assistant", [text])]),
                full_conversation=[],
            )
        )


def _aggregate(classifier_metrics: LLMCallMetrics):
    """Merges every participant's state-partial dict (decoded back out of
    the JSON each _AgentExecutor smuggled through as message text) into one
    dict, adds the classifier's own metrics under the same
    "orchestrator_llm_calls" key orchestrator_node always set, and hands
    the result to the EXISTING, unchanged assembler_node — see module
    docstring for why that's reused rather than reimplemented."""

    def aggregate(results: list[AgentExecutorResponse]) -> dict:
        merged: dict = {"orchestrator_llm_calls": [classifier_metrics]}
        for r in results:
            text = r.agent_response.messages[-1].text if r.agent_response.messages else "{}"
            partial = json.loads(text)
            # json.loads() only ever produces plain dicts — LLMCallMetrics
            # objects lost their type crossing the JSON-text boundary (see
            # _AgentExecutor.run()) and need re-hydrating, or
            # llm_metrics.summarize()'s `c.agent`/`c.input_tokens` attribute
            # access blows up on what's now a dict instead of a model.
            for key, value in partial.items():
                if key.endswith("_llm_calls"):
                    partial[key] = [LLMCallMetrics.model_validate(v) for v in value]
            merged.update(partial)
        return assembler_node(merged)

    return aggregate


async def run_paynexus_workflow(
    state: PayNexusState, agent_node_map: dict[str, Callable[[PayNexusState], dict]] = None
) -> dict:
    """Top-level replacement for `paynexus_graph.invoke(state)` — classifies
    intent, fans out concurrently to whichever agents were selected (via
    ConcurrentBuilder), and returns the exact same
    {final_response, active_agent, nudge_card, tables, token_usage} shape
    assembler_node always produced. `agent_node_map` defaults to
    DEFAULT_AGENT_NODE_MAP; tests override it with fakes to exercise the
    orchestration/fan-out/merge logic itself without 7 real LLM calls."""
    node_map = agent_node_map if agent_node_map is not None else DEFAULT_AGENT_NODE_MAP

    agent_keys, effective_state, classifier_metrics = await classify_intent(state)

    # ConcurrentBuilder's FanOutEdgeGroup hard-requires at least 2 targets
    # (agent_framework's own constraint, not a PayNexus design choice) —
    # and a single selected agent is the COMMON case here (most questions
    # route to exactly one agent; "multi" is the exception, per
    # orchestrator.py's own intent field: "multi" only when len(agent_keys)
    # > 1). Rather than pad a real 1-agent turn with a fake extra
    # participant just to satisfy the library, run that one node function
    # directly and feed it straight into assembler_node — same aggregation
    # logic either way, just without a pointless concurrent fan-out over a
    # single item.
    if len(agent_keys) == 1:
        key = agent_keys[0]
        node_result = await asyncio.to_thread(node_map[key], effective_state)
        return assembler_node({"orchestrator_llm_calls": [classifier_metrics], **node_result})

    participants = [
        _AgentExecutor(id=AGENT_KEY_TO_DISPLAY_ID[key], node_fn=node_map[key], state=effective_state)
        for key in agent_keys
    ]
    workflow = ConcurrentBuilder(participants=participants).with_aggregator(_aggregate(classifier_metrics)).build()
    result = await workflow.run(
        "Broadcast placeholder — every participant ignores this; see module docstring."
    )
    outputs = result.get_outputs()
    return outputs[0]


_BROADCAST_PLACEHOLDER = "Broadcast placeholder — every participant ignores this; see module docstring."


async def stream_paynexus_workflow(
    state: PayNexusState, agent_node_map: dict[str, Callable[[PayNexusState], dict]] = None
) -> AsyncGenerator[dict, None]:
    """Streaming counterpart to run_paynexus_workflow() — the direct
    replacement for api/routes/chat.py's `paynexus_graph.stream(state,
    stream_mode="updates")`. Yields plain dicts, not SSE-formatted text;
    the API layer's own _sse() formatting is unchanged (see chat.py) — this
    module stays free of HTTP-specific concerns.

    Yields exactly the same two logical events the old LangGraph-based
    route did: {"kind": "agent_active", "agent": <display id>} once per
    selected agent as it actually finishes (real completion order, not
    selection order — matches the old system's "as each node completes"
    semantics), then exactly one {"kind": "final", **assembler_node's
    output} at the end.
    """
    node_map = agent_node_map if agent_node_map is not None else DEFAULT_AGENT_NODE_MAP
    agent_keys, effective_state, classifier_metrics = await classify_intent(state)

    if len(agent_keys) == 1:
        # Same single-participant short-circuit as run_paynexus_workflow()
        # (ConcurrentBuilder can't run with fewer than 2) — only one
        # agent_active event is possible here anyway, so hand-emitting it
        # loses nothing relative to the real Workflow event stream below.
        key = agent_keys[0]
        display_id = AGENT_KEY_TO_DISPLAY_ID[key]
        yield {"kind": "agent_active", "agent": display_id}
        node_result = await asyncio.to_thread(node_map[key], effective_state)
        final = assembler_node({"orchestrator_llm_calls": [classifier_metrics], **node_result})
        yield {"kind": "final", **final}
        return

    participants = [
        _AgentExecutor(id=AGENT_KEY_TO_DISPLAY_ID[key], node_fn=node_map[key], state=effective_state)
        for key in agent_keys
    ]
    display_ids = {AGENT_KEY_TO_DISPLAY_ID[key] for key in agent_keys}
    workflow = ConcurrentBuilder(participants=participants).with_aggregator(_aggregate(classifier_metrics)).build()

    response_stream = workflow.run(_BROADCAST_PLACEHOLDER, stream=True)
    async for event in response_stream:
        # "executor_completed" fires for every executor in the graph,
        # including the builder's own internal "dispatcher"/"aggregate"
        # nodes — display_ids scopes this to the real participants only,
        # confirmed via direct inspection of a real streamed run (not
        # assumed from the SDK's docs, which don't enumerate event types).
        if event.type == "executor_completed" and event.executor_id in display_ids:
            yield {"kind": "agent_active", "agent": event.executor_id}

    final_result = await response_stream.get_final_response()
    outputs = final_result.get_outputs()
    yield {"kind": "final", **outputs[0]}
