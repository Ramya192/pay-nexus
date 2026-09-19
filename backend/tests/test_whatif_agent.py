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
from agents.whatif_agent import _simulate_payslip_scenario, _simulate_tax_scenario, whatif_agent_node
from whatif_extraction import has_any_signal

_EXTRACTION_METRICS = LLMCallMetrics(
    agent="whatif_extraction", model="gpt-4.1-mini", input_tokens=200, output_tokens=30, cost_usd=0.0002, latency_ms=400
)
_NARRATION_METRICS = LLMCallMetrics(
    agent="whatif_agent", model="gpt-4o", input_tokens=1000, output_tokens=150, cost_usd=0.01, latency_ms=3000
)

_EMPTY_SCENARIO = {
    "regime_switch": False, "additional_80c": None, "additional_80d": None, "additional_24b": None,
    "budget_category": None, "budget_delta": None, "goal_name": None, "goal_extra_monthly": None,
    "payslip_field": None, "payslip_new_value": None, "payslip_delta_amount": None,
    "payslip_delta_percent_of_basic": None,
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


class TestPayslipScenario:
    """_simulate_payslip_scenario called directly with a hand-built scenario
    dict — same no-real-credentials pattern as TestTaxScenarioRegimeAvailability
    above. The motivating real question this whole feature answers: "what
    would my net pay be if I contributed 2% more to PF?" (2026-09-15)."""

    _payslip = {"month": "2026-07", "basic": 50_000, "hra": 20_000, "pfEmployee": 6_000, "tds": 3_000}

    def _scenario(self, **overrides) -> dict:
        base = {"payslip_field": None, "payslip_new_value": None, "payslip_delta_amount": None, "payslip_delta_percent_of_basic": None}
        return {**base, **overrides}

    def test_pf_percent_of_basic_reduces_net_pay_and_old_regime_tax(self):
        scenario = self._scenario(payslip_field="pfEmployee", payslip_delta_percent_of_basic=2.0)
        text, table = _simulate_payslip_scenario(scenario, self._payslip, [], {"elssMutualFunds": 0})

        assert table is not None
        # 2% of 50,000 basic = 1,000 extra PF -> net pay drops by exactly 1,000.
        assert "1,000" in text
        net_row = next(r for r in table["rows"] if r[0] == "Net pay (computed)")
        baseline_net = 50_000 + 20_000 - 6_000 - 3_000  # gross - baseline PF - TDS
        assert net_row[1] == f"₹{baseline_net:,.0f}"
        assert net_row[2] == f"₹{baseline_net - 1_000:,.0f}"
        # PF is old-regime 80C -- more PF means less old-regime tax, not more.
        assert any(row[0] == "Old-regime tax (computed)" for row in table["rows"])

    def test_basic_salary_change_affects_net_pay_and_annual_income(self):
        scenario = self._scenario(payslip_field="basic", payslip_new_value=60_000)
        text, table = _simulate_payslip_scenario(scenario, self._payslip, [], {})
        net_row = next(r for r in table["rows"] if r[0] == "Net pay (computed)")
        # baseline: (50,000 + 20,000) - (6,000 PF + 3,000 TDS) = 61,000
        # scenario: (60,000 + 20,000) - (6,000 PF + 3,000 TDS) = 71,000 -- +10,000 basic flows straight through
        assert net_row[1] == "₹61,000"
        assert net_row[2] == "₹71,000"
        assert "full year" in text  # the stated 12-month assumption is disclosed, not silent
        assert any(row[0] == "Old-regime tax (computed)" for row in table["rows"])

    def test_no_field_returns_none(self):
        assert _simulate_payslip_scenario(self._scenario(), self._payslip, [], {}) is None

    def test_no_payslip_on_file(self):
        scenario = self._scenario(payslip_field="basic", payslip_new_value=60_000)
        text, table = _simulate_payslip_scenario(scenario, {}, [], {})
        assert "No payslip is on file" in text
        assert table is None

    def test_unrecognized_field_is_declined_not_crashed(self):
        scenario = self._scenario(payslip_field="notARealField", payslip_new_value=1)
        text, table = _simulate_payslip_scenario(scenario, self._payslip, [], {})
        assert "isn't a payslip component" in text
        assert table is None

    def test_professional_tax_change_does_not_touch_annual_income_or_tax_table(self):
        # Professional tax reduces net pay directly but isn't a GROSS_PAY
        # field and isn't PF -- shouldn't trigger the old-regime tax branch.
        scenario = self._scenario(payslip_field="professionalTax", payslip_delta_amount=100)
        text, table = _simulate_payslip_scenario(scenario, self._payslip, [], {})
        assert not any(row[0] == "Old-regime tax (computed)" for row in table["rows"])


class TestPayslipScenarioSignal:
    def test_pf_percent_question_is_a_real_signal(self):
        scenario = {**_EMPTY_SCENARIO, "payslip_field": "pfEmployee", "payslip_delta_percent_of_basic": 2.0}
        assert has_any_signal(scenario) is True

    def test_field_without_any_amount_is_not_a_signal(self):
        scenario = {**_EMPTY_SCENARIO, "payslip_field": "basic"}
        assert has_any_signal(scenario) is False


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
