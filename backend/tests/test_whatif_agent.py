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

from agents.whatif_agent import _simulate_tax_scenario, whatif_agent_node


@pytest.mark.integration
class TestNoSignalFallback:
    def test_vague_question_declines_rather_than_guessing(self):
        state = {"user_query": "what if I made some changes to my finances?", "goals": [], "conversation": []}
        result = whatif_agent_node(state)
        parsed = json.loads(result["scenario_response"])
        assert "specific" in parsed["explanation"].lower()
        assert "scenario_llm_calls" not in result


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
        assert table is not None


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
