"""Tests for agents/spending_agent.py. The empty-transactions fallback is a
pure-Python unit test (no LLM call) and runs unconditionally. The
real-narration tests below are marked `integration` individually (not at
module level, so the fallback test above isn't skipped alongside them) and
hit OpenAI — same reasoning and skip behavior as test_integration_agents.py:
verifying that the model actually quotes the precomputed figures rather
than re-deriving its own can't be done without a real call.
"""

import json

import pytest

from agents.spending_agent import spending_agent_node


class TestNoTransactionsFallback:
    def test_no_transactions_returns_fallback_without_llm_call(self):
        state = {"user_query": "where is my money going?", "transactions": []}
        result = spending_agent_node(state)
        parsed = json.loads(result["spending_response"])
        assert "upload" in parsed["explanation"].lower()
        assert "spending_llm_calls" not in result


def _sample_transactions() -> list[dict]:
    return [
        {"date": "2026-06-01", "description": "SALARY CREDIT", "amount": 75000, "category": "Income"},
        {"date": "2026-06-05", "description": "RENT PAYMENT", "amount": -18000, "category": "Rent"},
        {"date": "2026-06-10", "description": "SWIGGY", "amount": -500, "category": "Food & Dining"},
        {"date": "2026-07-01", "description": "SALARY CREDIT", "amount": 75000, "category": "Income"},
        {"date": "2026-07-05", "description": "RENT PAYMENT", "amount": -18000, "category": "Rent"},
        {"date": "2026-07-10", "description": "SWIGGY", "amount": -900, "category": "Food & Dining"},
        {"date": "2026-07-12", "description": "SWIGGY", "amount": -600, "category": "Food & Dining"},
    ]


@pytest.mark.integration
class TestSpendingAgentNarratesPrecomputedFigures:
    def test_top_category_question_cites_rent(self):
        state = {
            "user_query": "What's my biggest spending category?",
            "transactions": _sample_transactions(),
            "conversation": [],
        }
        result = spending_agent_node(state)
        parsed = json.loads(result["spending_response"])
        assert "rent" in parsed["explanation"].lower()

    def test_spending_trend_question_notes_increase(self):
        """Food & Dining spend: ₹500 in June, ₹1,500 in July — must narrate
        an increase, not a decrease or "unchanged," and should select the
        category_trend table (this question is about one category, not the
        period_trend table's all-categories-combined total)."""
        state = {
            "user_query": "Is my food spending going up month over month?",
            "transactions": _sample_transactions(),
            "conversation": [],
        }
        result = spending_agent_node(state)
        parsed = json.loads(result["spending_response"])
        explanation = parsed["explanation"].lower()
        # Stems ("increas", "ris") rather than exact words — "increase" is
        # not a substring of "increasing" ("increasi" vs "increase" diverge
        # at the 8th character), and a real run hit exactly that phrasing.
        assert "up" in explanation or "increas" in explanation or "more" in explanation or "ris" in explanation
        assert "down" not in explanation and "decreas" not in explanation and "fell" not in explanation
