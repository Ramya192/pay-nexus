"""
Integration tests that hit the real OpenAI API — the small subset of fixes
this build's regression list could only actually be verified with a real
LLM call, because the bug was in how the model narrated correct numbers,
not in the numbers themselves:

1. The Savings Advisor (nudge_agent) and Payslip Reasoning Agent
   (payslip_agent) both computing the exact same regime numbers and STILL
   inverting which one is "cheaper" in their own prose, in a real
   conversation, not just in the pre-computed table.
2. The Payslip Reasoning Agent conflating "zero tax" with "zero taxable
   income" when narrating a real answer.
3. The Regulatory Agent's over-hedging on a basic, stable concept.

Skipped automatically unless OPENAI_API_KEY is set (see conftest.py). The
Regulatory Agent test additionally needs a live pgvector index
(DATABASE_URL + rag/build_index.py already run) — skipped on its own if
that's not available, since it's a strictly stronger requirement than the
other two tests in this file.
"""

import json
import os

import pytest

from agents.nudge_agent import nudge_agent_node
from agents.payslip_agent import payslip_agent_node
from agents.regulatory_agent import regulatory_agent_node

pytestmark = pytest.mark.integration


def _base_state(question: str) -> dict:
    return {
        "user_query": question,
        "payslip_data": {"month": "2026-03", "basic": 70_000, "hra": 28_000, "specialAllowance": 10_000},
        "payslip_history": [],
        "financial_profile": {"elssMutualFunds": 150_000, "homeLoanInterestPaid": 50_000},
        "session_history": [],
        "conversation": [],
    }


class TestRegimeConsistencyAcrossAgents:
    """Fixture numbers hand-verified in tests/test_tax_slabs.py's style:
    ₹12,96,000 gross, ₹2,00,000 declared deductions → new regime tax
    ₹21,840 vs old regime ₹1,31,352 — the NEW regime is unambiguously
    cheaper here. Both agents share this exact computation
    (tax_slabs.compute_old_regime_tax/compute_new_regime_tax, called with
    the same resolve_effective_payslip'd payslip_data and the same
    tax_calculations.compute_all_gaps total) — this test's job is to catch
    a regression in the PROSE, not the numbers, which were already
    consistent before this fix and could look consistent again while the
    narration silently disagrees."""

    def test_payslip_agent_recommends_new_regime_in_prose(self):
        state = _base_state("Which tax regime should I choose, old or new, and why?")
        result = payslip_agent_node(state)
        parsed = json.loads(result["payslip_response"])
        explanation = parsed["explanation"].lower()
        assert "new" in explanation
        # Must not tell the user to switch TO the old regime, or claim the
        # old regime is cheaper/better — the exact inversion bug reported.
        assert "old regime is cheaper" not in explanation
        assert "recommend the old regime" not in explanation

    def test_nudge_agent_recommends_new_regime_in_prose(self):
        state = _base_state("Which tax regime should I choose, old or new, and why?")
        result = nudge_agent_node(state)
        parsed = json.loads(result["nudge_response"])
        detail = parsed["detail"].lower()
        assert "new" in detail
        assert "old regime is cheaper" not in detail
        assert "recommend the old regime" not in detail


class TestTaxableIncomeDistinctFromTax:
    """₹10,77,600 annual gross, no deductions → new regime taxable income
    ₹10,02,600 but total tax ₹0 (below the ₹12L rebate threshold) — the
    exact scenario that produced the reported bug: an agent said "the new
    regime results in zero taxable income" when only the TAX was zero."""

    def test_payslip_agent_does_not_conflate_zero_tax_with_zero_taxable_income(self):
        state = _base_state("What is my taxable income under the new regime?")
        state["payslip_data"] = {"month": "2026-03", "basic": 65_000, "hra": 24_800, "specialAllowance": 0}
        state["financial_profile"] = {}
        result = payslip_agent_node(state)
        explanation = json.loads(result["payslip_response"])["explanation"].lower()
        assert "zero taxable income" not in explanation
        assert "no taxable income" not in explanation
        assert "₹10,02,600" in explanation.replace(" ", "") or "1,002,600" in explanation.replace(" ", "")


class TestRegulatoryAgentDoesNotOverHedge:
    def test_basic_definitional_question_answered_without_disclaimer(self):
        if not os.getenv("DATABASE_URL"):
            pytest.skip("DATABASE_URL not set — this test also needs the live pgvector index")
        state = _base_state("What is taxable income?")
        result = regulatory_agent_node(state)
        answer = result["regulatory_response"].lower()
        assert "taxable income" in answer
        # The exact undercutting disclaimer this fix removed for basic,
        # stable concepts (still fine for a Budget-dependent figure).
        assert "consult the income tax act" not in answer
        assert "for a precise definition" not in answer
