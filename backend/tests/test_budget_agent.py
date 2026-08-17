"""Tests for agents/budget_agent.py. The no-budget fallback is a pure-Python
unit test (no LLM call) and runs unconditionally. The real-narration tests
below are marked `integration` individually and hit OpenAI (via the
Ollama-or-cloud hybrid path, agents/llm.py) — same reasoning as
test_spending_agent.py / test_goal_agent.py.
"""

import json

import pytest

from agents.budget_agent import budget_agent_node


class TestNoBudgetFallback:
    def test_no_budget_returns_fallback_without_llm_call(self):
        state = {"user_query": "am I over budget?", "budgets": {}, "transactions": []}
        result = budget_agent_node(state)
        parsed = json.loads(result["budget_response"])
        assert "budget" in parsed["explanation"].lower()
        assert "budget_llm_calls" not in result


def _sample_transactions() -> list[dict]:
    return [
        {"date": "2026-07-03", "description": "SWIGGY", "amount": -2500, "category": "Food & Dining", "statement_period": "2026-07"},
        {"date": "2026-07-05", "description": "BIGBASKET", "amount": -1500, "category": "Groceries", "statement_period": "2026-07"},
    ]


@pytest.mark.integration
class TestBudgetAgentNarratesPrecomputedFigures:
    def test_overspending_question_cites_correct_category(self):
        state = {
            "user_query": "Am I over budget this period?",
            "budgets": {"Food & Dining": 2000, "Groceries": 5000},
            "transactions": _sample_transactions(),
            "conversation": [],
        }
        result = budget_agent_node(state)
        explanation = json.loads(result["budget_response"])["explanation"].lower()
        # Food & Dining is over (₹2,500 spent vs ₹2,000 budget); Groceries is not.
        assert "food" in explanation
        assert "groceries" not in explanation or "over" not in explanation.split("groceries")[1][:50]
