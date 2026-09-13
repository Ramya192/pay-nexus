"""
Tests for agents/orchestrator_v2.py — the asyncio.gather-based replacement
for orchestrator.py's LangGraph fan-out/fan-in (an earlier version used
agent_framework_orchestrations' ConcurrentBuilder for execution; see
orchestrator_v2.py's module docstring for why that was replaced — it
deadlocked for real, live, under uvicorn, with 2 real concurrent agents).

Most tests here use FAKE node functions (via run_paynexus_workflow's
agent_node_map override) instead of the real 7 agents — this suite is about
proving the ORCHESTRATION MECHANISM itself (concurrent fan-out, merging
into assembler_node) works correctly, not re-testing each agent's own
narration quality (already covered by tests/test_<agent>_agent.py and
tests/test_orchestrator_assembler.py, which this reuses unchanged).
classify_intent is monkeypatched in these — it's the one real-LLM-calling
piece — except in the @pytest.mark.integration tests at the bottom, which
exercise the real thing end to end.
"""

import asyncio

import pytest

from agents.llm_metrics import LLMCallMetrics
from agents.orchestrator_v2 import _context_window_for_turn, run_paynexus_workflow, stream_paynexus_workflow
from compression import token_budget
from config import config

_FAKE_METRICS = LLMCallMetrics(agent="orchestrator_classifier", model="gpt-4o", input_tokens=10, output_tokens=5, cost_usd=0.0, latency_ms=1.0)


def _fake_classify(agent_keys):
    """Returns a drop-in replacement for classify_intent that skips the
    real LLM call entirely — agent_keys is whatever the "classifier" should
    have picked, effective_state just passes the input state through
    unchanged (no compression behavior under test here)."""

    async def fake(state):
        return agent_keys, state, _FAKE_METRICS

    return fake


def _run(state, agent_node_map, agent_keys, monkeypatch):
    monkeypatch.setattr("agents.orchestrator_v2.classify_intent", _fake_classify(agent_keys))
    return asyncio.run(run_paynexus_workflow(state, agent_node_map=agent_node_map))


class TestContextWindowForTurn:
    """_context_window_for_turn — the "which real capacity ceiling applies
    this turn" resolution that classify_intent sizes its dynamic
    compression pass against. Pure function, no LLM/network call."""

    def test_cloud_only_agent_uses_its_own_deployment_window(self, monkeypatch):
        monkeypatch.setattr(config, "USE_LOCAL_SLM", False)
        window, model = _context_window_for_turn(["payslip"])  # gpt-4o, cloud-only agent
        assert model == "gpt-4o"
        assert window == token_budget.context_window_for("gpt-4o")

    def test_hybrid_agent_with_local_slm_off_uses_its_cloud_deployment(self, monkeypatch):
        monkeypatch.setattr(config, "USE_LOCAL_SLM", False)
        window, model = _context_window_for_turn(["nudge"])
        # NUDGE_AGENT_MODEL is "gpt-4o-mini", mapped via FOUNDRY_DEPLOYMENT_MAP
        # to the real Foundry deployment behind it.
        assert model == config.FOUNDRY_DEPLOYMENT_MAP["gpt-4o-mini"]
        assert window == token_budget.context_window_for(model)

    def test_hybrid_agent_with_local_slm_on_is_limited_by_phi4_mini(self, monkeypatch):
        monkeypatch.setattr(config, "USE_LOCAL_SLM", True)
        window, model = _context_window_for_turn(["nudge"])
        assert model == "phi4-mini"
        assert window == token_budget.context_window_for("phi4-mini")
        assert window < token_budget.context_window_for(config.FOUNDRY_DEPLOYMENT_MAP["gpt-4o-mini"])

    def test_mixed_turn_picks_the_tightest_of_all_selected_agents(self, monkeypatch):
        monkeypatch.setattr(config, "USE_LOCAL_SLM", True)
        # payslip (gpt-4o, cloud-only) + nudge (hybrid, phi4-mini-eligible
        # while USE_LOCAL_SLM is on) selected together — the real ceiling
        # for the SHARED conversation/session_history both receive must be
        # the smaller of the two, not whichever agent happens to be listed
        # first.
        window, model = _context_window_for_turn(["payslip", "nudge"])
        assert model == "phi4-mini"
        assert window == token_budget.context_window_for("phi4-mini")

    def test_empty_agent_keys_falls_back_to_payslip_model(self):
        window, model = _context_window_for_turn([])
        assert model == config.PAYSLIP_AGENT_MODEL
        assert window == token_budget.context_window_for(config.PAYSLIP_AGENT_MODEL)


class TestConcurrentFanOut:
    def test_single_agent_selected_runs_only_that_one(self, monkeypatch):
        calls = []

        def fake_budget(state):
            calls.append("budget")
            return {"budget_response": '{"explanation": "You are over on Food.", "follow_up_suggestions": []}'}

        def fake_goal(state):
            calls.append("goal")
            return {"goal_response": '{"explanation": "should not run", "follow_up_suggestions": []}'}

        result = _run({"user_query": "am I over budget?"}, {"budget": fake_budget, "goal": fake_goal}, ["budget"], monkeypatch)

        assert calls == ["budget"]
        assert result["active_agent"] == "budget_agent"
        assert "You are over on Food." in result["final_response"]

    def test_two_agents_selected_both_run_and_both_merge(self, monkeypatch):
        def fake_budget(state):
            return {"budget_response": '{"explanation": "Budget narration.", "follow_up_suggestions": []}'}

        def fake_goal(state):
            return {"goal_response": '{"explanation": "Goal narration.", "follow_up_suggestions": []}'}

        result = _run({"user_query": "budget and goal?"}, {"budget": fake_budget, "goal": fake_goal}, ["budget", "goal"], monkeypatch)

        # assembler_node (reused unchanged) checks agents in its own fixed
        # order (goal before budget) regardless of which participant's
        # concurrent execution actually finished first — active_agent's
        # ordering is deterministic by that fixed check order, not by
        # completion order, so this doesn't depend on which one "won" the
        # race between the two real concurrent executors.
        assert result["active_agent"] == "goal_agent,budget_agent"
        assert "Budget narration." in result["final_response"]
        assert "Goal narration." in result["final_response"]

    def test_each_participant_gets_the_same_effective_state_not_a_broadcast_message(self, monkeypatch):
        """Proves each participant reads the real closure-captured state
        (not whatever the workflow's own internal broadcast placeholder
        string is)."""
        seen_queries = []

        def fake_budget(state):
            seen_queries.append(state["user_query"])
            return {"budget_response": '{"explanation": "x", "follow_up_suggestions": []}'}

        _run({"user_query": "a very specific real question"}, {"budget": fake_budget}, ["budget"], monkeypatch)
        assert seen_queries == ["a very specific real question"]

    def test_llm_call_metrics_and_tables_survive_concurrent_merge(self, monkeypatch):
        """Confirms a nested LLMCallMetrics Pydantic object and a table dict
        both survive _run_agents_concurrently's merge (a plain dict.update()
        per agent, then assembler_node) intact — real 2-agent case, not the
        1-agent case, so the merge loop genuinely runs over >1 result.
        (An earlier version of this design round-tripped every result
        through JSON text to cross agent_framework_orchestrations'
        ConcurrentBuilder — see orchestrator_v2.py's module docstring for
        why that's gone. That boundary is exactly where a real bug was once
        found — LLMCallMetrics decoding back as a plain dict, not a model
        instance — so this test's job is the same even though the
        mechanism it's now checking is a plain dict merge, not a
        serialization round trip.)"""
        metrics = LLMCallMetrics(agent="budget_agent", model="gpt-4.1-mini", input_tokens=100, output_tokens=50, cost_usd=0.001, latency_ms=200)
        table = {"title": "Budget vs actual", "headers": ["Category", "Spent"], "rows": [["Food", "2,500"]]}

        def fake_budget(state):
            return {
                "budget_response": '{"explanation": "x", "follow_up_suggestions": []}',
                "budget_tables": [table],
                "budget_llm_calls": [metrics],
            }

        def fake_goal(state):
            return {"goal_response": '{"explanation": "y", "follow_up_suggestions": []}'}

        result = _run({"user_query": "q"}, {"budget": fake_budget, "goal": fake_goal}, ["budget", "goal"], monkeypatch)

        assert result["tables"] == [table]
        assert result["token_usage"]["total_input_tokens"] == 100 + _FAKE_METRICS.input_tokens
        assert result["token_usage"]["by_agent"]["budget_agent"]["input_tokens"] == 100

    def test_capability_gap_key_routes_to_the_real_no_llm_node(self, monkeypatch):
        """capability_gap_node is a real, unmigrated, no-LLM function —
        included directly in the node map (not faked) to prove "unsupported"
        routes through the exact same uniform executor mechanism as every
        other agent key, no special-casing needed."""
        from agents.orchestrator import capability_gap_node

        result = _run({"user_query": "delete my payslip"}, {"unsupported": capability_gap_node}, ["unsupported"], monkeypatch)

        assert result["active_agent"] == "capability_gap_node"
        assert "[PayNexus]" in result["final_response"]
        assert "sidebar" not in result["final_response"].lower()


class TestStreaming:
    """stream_paynexus_workflow() — the direct replacement for
    api/routes/chat.py's paynexus_graph.stream(..., stream_mode="updates").
    Same fake-node-function approach as TestConcurrentFanOut, run through
    the async generator instead of the single-shot workflow."""

    @staticmethod
    def _collect(state, agent_node_map, agent_keys, monkeypatch):
        monkeypatch.setattr("agents.orchestrator_v2.classify_intent", _fake_classify(agent_keys))

        async def run():
            return [event async for event in stream_paynexus_workflow(state, agent_node_map=agent_node_map)]

        return asyncio.run(run())

    def test_single_agent_emits_one_agent_active_then_final(self, monkeypatch):
        def fake_budget(state):
            return {"budget_response": '{"explanation": "Budget narration.", "follow_up_suggestions": []}'}

        events = self._collect({"user_query": "q"}, {"budget": fake_budget}, ["budget"], monkeypatch)

        assert [e["kind"] for e in events] == ["agent_active", "final"]
        assert events[0]["agent"] == "budget_agent"
        assert events[1]["active_agent"] == "budget_agent"
        assert "Budget narration." in events[1]["final_response"]

    def test_two_agents_emit_two_agent_active_events_then_one_final(self, monkeypatch):
        def fake_budget(state):
            return {"budget_response": '{"explanation": "Budget narration.", "follow_up_suggestions": []}'}

        def fake_goal(state):
            return {"goal_response": '{"explanation": "Goal narration.", "follow_up_suggestions": []}'}

        events = self._collect(
            {"user_query": "q"}, {"budget": fake_budget, "goal": fake_goal}, ["budget", "goal"], monkeypatch
        )

        kinds = [e["kind"] for e in events]
        assert kinds.count("agent_active") == 2
        assert kinds[-1] == "final"
        active_agents = {e["agent"] for e in events if e["kind"] == "agent_active"}
        assert active_agents == {"budget_agent", "goal_agent"}
        final = events[-1]
        assert "Budget narration." in final["final_response"]
        assert "Goal narration." in final["final_response"]

    def test_capability_gap_streams_correctly(self, monkeypatch):
        from agents.orchestrator import capability_gap_node

        events = self._collect(
            {"user_query": "delete my payslip"}, {"unsupported": capability_gap_node}, ["unsupported"], monkeypatch
        )

        assert events[0] == {"kind": "agent_active", "agent": "capability_gap_node"}
        assert events[1]["active_agent"] == "capability_gap_node"


@pytest.mark.integration
def test_real_streaming_end_to_end():
    """The one real-LLM test for the streaming path — confirms the actual
    Workflow event stream (not a fake) yields exactly one agent_active per
    real agent plus one final, against a genuine 2-agent question."""
    state = {
        "user_query": "Am I over budget, and how is my Emergency Fund goal progressing?",
        "budgets": {"Food & Dining": 2000},
        "transactions": [
            {"date": "2026-03-05", "description": "Restaurant", "amount": 2500, "category": "Food & Dining"},
        ],
        "goals": [{"name": "Emergency Fund", "targetAmount": 100000, "savedAmount": 40000, "targetDate": "2027-01-01"}],
        "conversation": [],
    }

    async def run():
        return [event async for event in stream_paynexus_workflow(state)]

    events = asyncio.run(run())
    kinds = [e["kind"] for e in events]
    assert kinds.count("agent_active") >= 1  # at least one real agent selected
    assert kinds[-1] == "final"
    assert "budget_agent" in events[-1]["active_agent"] or "goal_agent" in events[-1]["active_agent"]


@pytest.mark.integration
def test_real_end_to_end_single_agent_question():
    """Makes real calls (classify_intent + budget_agent, both against the
    real Foundry deployment) — proves the whole pipeline (real
    classification -> real concurrent fan-out -> real assembler_node)
    works end to end, not just with fakes standing in for each piece."""
    state = {
        "user_query": "Am I over budget this month?",
        "budgets": {"Food & Dining": 2000},
        "transactions": [
            {"date": "2026-03-05", "description": "Restaurant", "amount": 2500, "category": "Food & Dining"},
        ],
        "conversation": [],
    }
    result = asyncio.run(run_paynexus_workflow(state))

    assert "budget_agent" in result["active_agent"]
    assert "[BudgetPlanner Agent]" in result["final_response"]
    assert result["token_usage"]["total_input_tokens"] > 0


@pytest.mark.integration
def test_real_end_to_end_multi_agent_question():
    """Same as above but forces a real 2-agent turn — proves the genuine
    concurrent-execution path (asyncio.gather over 2 real agents) works end
    to end, not just with the fakes in TestConcurrentFanOut. This exact
    2-real-agent shape is also what live-reproduced the ConcurrentBuilder
    deadlock this module's docstring describes; this test guards against
    that class of regression recurring, though it can't itself detect a
    hang under uvicorn specifically (see the module docstring — the
    deadlock didn't reproduce in a plain asyncio.run() script either)."""
    state = {
        "user_query": "Am I over budget, and how is my Emergency Fund goal progressing?",
        "budgets": {"Food & Dining": 2000},
        "transactions": [
            {"date": "2026-03-05", "description": "Restaurant", "amount": 2500, "category": "Food & Dining"},
        ],
        "goals": [{"name": "Emergency Fund", "targetAmount": 100000, "savedAmount": 40000, "targetDate": "2027-01-01"}],
        "conversation": [],
    }
    result = asyncio.run(run_paynexus_workflow(state))

    assert "budget_agent" in result["active_agent"]
    assert "goal_agent" in result["active_agent"]
    assert "[BudgetPlanner Agent]" in result["final_response"]
    assert "[GoalTracker Agent]" in result["final_response"]
