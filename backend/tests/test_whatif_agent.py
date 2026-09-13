"""Tests for agents/whatif_agent.py. The no-signal fallback is a pure-
Python-plus-one-LLM-extraction-call path — still marked integration since
extract_scenario itself is a real OpenAI call, but assertable without a
computed scenario. The real per-domain simulation tests are marked
`integration` individually and hit OpenAI twice per test (extraction, then
narration) — same reasoning as test_spending_agent.py/test_goal_agent.py/
test_budget_agent.py: verifying the model actually quotes precomputed
before/after figures rather than re-deriving them needs a real call.
"""

import json

import pytest

from agents.llm_metrics import LLMCallMetrics
from agents.whatif_agent import _simulate_tax_scenario, whatif_agent_node

_EXTRACTION_METRICS = LLMCallMetrics(
    agent="whatif_extraction", model="gpt-4.1-mini", input_tokens=200, output_tokens=30, cost_usd=0.0002, latency_ms=400
)
_NARRATION_METRICS = LLMCallMetrics(
    agent="whatif_agent", model="gpt-4o", input_tokens=1000, output_tokens=150, cost_usd=0.01, latency_ms=3000
)

_EMPTY_SCENARIO = {
    "regime_switch": False, "additional_80c": None, "additional_80d": None, "additional_24b": None,
    "budget_category": None, "budget_delta": None, "goal_name": None, "goal_extra_monthly": None,
}


def _fake_extract(scenario: dict):
    """extract_scenario is async (agent_complete-backed) — a plain lambda
    returning a tuple isn't awaitable, so this needs to actually be a
    coroutine function, same reasoning as test_regulatory_agent.py's
    _fake_text_call."""

    async def fake(user_query, conversation, goal_names):
        return scenario, _EXTRACTION_METRICS

    return fake


def _fake_narration(response_json: str):
    async def fake(*args, **kwargs):
        return response_json, _NARRATION_METRICS

    return fake


@pytest.mark.integration
class TestNoSignalFallback:
    def test_vague_question_declines_rather_than_guessing(self):
        state = {"user_query": "what if I made some changes to my finances?", "goals": [], "conversation": []}
        result = whatif_agent_node(state)
        parsed = json.loads(result["scenario_response"])
        assert "specific" in parsed["explanation"].lower()
        # extract_scenario is a real, billed call even when it finds nothing
        # to simulate — it must never be silently missing from token_usage.
        # (Used to assert the opposite; see whatif_extraction.py's module
        # docstring for the real gap that was.)
        assert len(result["scenario_llm_calls"]) == 1
        assert result["scenario_llm_calls"][0].agent == "whatif_extraction"


def _base_state(question: str) -> dict:
    return {
        "user_query": question,
        "payslip_data": {"month": "2026-07", "basic": 70_000, "hra": 28_000, "specialAllowance": 10_000},
        "payslip_history": [],
        "financial_profile": {"elssMutualFunds": 50_000},
        "transactions": [],
        "budgets": {},
        "goals": [],
        "conversation": [],
    }


@pytest.mark.integration
class TestTaxScenario:
    def test_regime_switch_question_states_a_conclusion(self):
        state = _base_state("What if I switched to the new tax regime?")
        result = whatif_agent_node(state)
        parsed = json.loads(result["scenario_response"])
        explanation = parsed["explanation"].lower()
        assert "regime" in explanation
        if result["scenario_tables"]:
            assert "tax scenario" in result["scenario_tables"][0]["title"].lower()

    def test_additional_80c_question_cites_reduced_tax(self):
        state = _base_state("What if I invested an additional ₹50,000 in ELSS for 80C?")
        result = whatif_agent_node(state)
        parsed = json.loads(result["scenario_response"])
        explanation = parsed["explanation"].lower()
        assert "50,000" in explanation.replace(",", ",") or "50000" in explanation.replace(",", "")


class TestTaxScenarioRegimeAvailability:
    """_simulate_tax_scenario called directly with a hand-built scenario
    dict — no LLM extraction involved, so this doesn't need real
    credentials, unlike the rest of this file. Covers the same historical
    guard as tax_slabs.regime_choice_available, one level up: a regime-
    switch what-if for a payslip that predates the new regime's existence
    (Union Budget 2020, FY2020-21) should decline that part rather than
    silently running today's slabs against it."""

    _payslip_data = {"month": "2019-06", "basic": 70_000, "hra": 28_000, "specialAllowance": 10_000}

    def test_regime_switch_declined_for_a_pre_2020_payslip(self):
        scenario = {"regime_switch": True, "additional_80c": None, "additional_80d": None, "additional_24b": None}
        text, table = _simulate_tax_scenario(scenario, self._payslip_data, [], {})
        assert "didn't exist" in text
        assert "2019-06" in text
        assert table is None

    def test_pure_deduction_scenario_still_works_for_a_pre_2020_payslip(self):
        """The old regime itself did exist before 2020 — only the SWITCH
        half of a scenario is anachronistic, not a plain deduction what-if."""
        scenario = {"regime_switch": False, "additional_80c": 50_000, "additional_80d": None, "additional_24b": None}
        text, table = _simulate_tax_scenario(scenario, self._payslip_data, [], {})
        assert "didn't exist" not in text
        assert table is not None

    def test_regime_switch_allowed_for_a_post_2020_payslip(self):
        payslip_data = {**self._payslip_data, "month": "2026-07"}
        scenario = {"regime_switch": True, "additional_80c": None, "additional_80d": None, "additional_24b": None}
        text, table = _simulate_tax_scenario(scenario, payslip_data, [], {})
        assert "didn't exist" not in text


class TestExtractionMetricsTracking:
    """Offline coverage for the actual thing whatif_extraction.py's
    2026-09-12 migration to agent_complete() fixed — extract_scenario's own
    real, billed call used to be completely invisible in scenario_llm_calls,
    including on the "nothing to simulate" early-return path where it's the
    ONLY call that turn makes. Monkeypatches extract_scenario/agent_complete
    directly (same pattern as test_regulatory_agent.py) — no real LLM or
    network call, no @pytest.mark.integration needed. Also the first
    non-integration coverage this file has ever had for whatif_agent_node's
    own wiring (every other test here needs real credentials) — a genuine
    gap this migration made possible to close, not just a side effect.
    """

    def test_no_signal_path_still_reports_the_extraction_call(self, monkeypatch):
        monkeypatch.setattr("agents.whatif_agent.extract_scenario", _fake_extract(_EMPTY_SCENARIO))
        state = {"user_query": "what if I made some changes?", "goals": [], "conversation": []}

        result = whatif_agent_node(state)

        assert result["scenario_llm_calls"] == [_EXTRACTION_METRICS]
        assert "specific" in json.loads(result["scenario_response"])["explanation"].lower()

    def test_signal_path_reports_both_extraction_and_narration_calls_in_order(self, monkeypatch):
        scenario = {**_EMPTY_SCENARIO, "regime_switch": True}
        monkeypatch.setattr("agents.whatif_agent.extract_scenario", _fake_extract(scenario))
        monkeypatch.setattr(
            "agents.whatif_agent.agent_complete",
            _fake_narration(json.dumps({"explanation": "x", "tables": [], "follow_up_suggestions": []})),
        )
        state = {
            "user_query": "What if I switched regimes?",
            "payslip_data": {"month": "2026-07", "basic": 70_000, "hra": 28_000, "specialAllowance": 10_000},
            "payslip_history": [],
            "financial_profile": {},
            "goals": [],
            "conversation": [],
        }

        result = whatif_agent_node(state)

        # Order matters for anyone reading token_usage's calls list — the
        # extraction call genuinely happened first, chronologically.
        assert result["scenario_llm_calls"] == [_EXTRACTION_METRICS, _NARRATION_METRICS]


@pytest.mark.integration
class TestBudgetScenario:
    def test_cutting_category_that_fixes_overspending(self):
        state = _base_state("What if I cut my Food & Dining budget by ₹1,000?")
        state["budgets"] = {"Food & Dining": 2000}
        state["transactions"] = [
            {"date": "2026-07-05", "description": "SWIGGY", "amount": -2500, "category": "Food & Dining", "statement_period": "2026-07"}
        ]
        result = whatif_agent_node(state)
        explanation = json.loads(result["scenario_response"])["explanation"].lower()
        assert "food" in explanation


@pytest.mark.integration
class TestGoalScenario:
    def test_extra_contribution_cites_months_to_target(self):
        state = _base_state("What if I saved an extra ₹30,000 a month for my Goa Trip goal?")
        state["goals"] = [{"name": "Goa Trip", "category": "Trip", "targetAmount": 120000, "savedAmount": 30000, "targetDate": None}]
        result = whatif_agent_node(state)
        explanation = json.loads(result["scenario_response"])["explanation"].lower()
        # Remaining 90,000 / 30,000 per month = 3 months.
        assert "3" in explanation

    def test_unknown_goal_name_says_not_found_rather_than_guessing(self):
        state = _base_state("What if I saved an extra ₹500 a month for my Mars Vacation goal?")
        state["goals"] = [{"name": "Goa Trip", "category": "Trip", "targetAmount": 120000, "savedAmount": 30000, "targetDate": None}]
        result = whatif_agent_node(state)
        explanation = json.loads(result["scenario_response"])["explanation"].lower()
        assert "no" in explanation or "not" in explanation or "don't have" in explanation or "couldn't find" in explanation
