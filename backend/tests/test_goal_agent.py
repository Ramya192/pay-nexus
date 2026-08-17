"""Tests for agents/goal_agent.py. The empty-goals fallback is a pure-Python
unit test (no LLM call) and runs unconditionally. The real-narration tests
below are marked `integration` individually and hit OpenAI (via the
Ollama-or-cloud hybrid path, agents/llm.py) — same reasoning as
test_spending_agent.py: verifying the model actually quotes precomputed
figures rather than re-deriving its own needs a real call.
"""

import json

import pytest

from agents.goal_agent import goal_agent_node


class TestNoGoalsFallback:
    def test_no_goals_returns_fallback_without_llm_call(self):
        state = {"user_query": "how am I doing on my goals?", "goals": []}
        result = goal_agent_node(state)
        parsed = json.loads(result["goal_response"])
        assert "add" in parsed["explanation"].lower()
        assert "goal_llm_calls" not in result


def _sample_goals() -> list[dict]:
    return [
        {
            "name": "Goa Trip",
            "category": "Trip",
            "targetAmount": 120000,
            "savedAmount": 30000,
            "targetDate": "2026-11-15",
        },
        {
            "name": "Emergency Fund",
            "category": "Emergency Fund",
            "targetAmount": 300000,
            "savedAmount": 300000,
            "targetDate": None,
        },
    ]


@pytest.mark.integration
class TestGoalAgentNarratesPrecomputedFigures:
    def test_progress_question_cites_correct_percentages(self):
        state = {
            "user_query": "How am I doing on my goals?",
            "goals": _sample_goals(),
            "transactions": [],
            "conversation": [],
        }
        result = goal_agent_node(state)
        parsed = json.loads(result["goal_response"])
        explanation = parsed["explanation"].lower()
        # Goa Trip: 30,000/120,000 = 25%. Emergency Fund: fully met (100%).
        assert "25%" in explanation or "25 %" in explanation or "25 percent" in explanation
        assert "emergency fund" in explanation

    def test_acknowledges_no_live_price_tracking_for_market_growth_question(self):
        state = {
            "user_query": "How much will my Emergency Fund grow if it's in a fixed deposit?",
            "goals": _sample_goals(),
            "transactions": [],
            "conversation": [],
        }
        result = goal_agent_node(state)
        # Normalize curly apostrophes (’) to straight ones (') before
        # matching — a real run phrased it "isn’t available" with a
        # typographic quote, which silently failed a straight-quote "n't"
        # check despite being a fully correct, on-message answer.
        explanation = json.loads(result["goal_response"])["explanation"].lower().replace("’", "'")
        # Must decline to project a market/FD return it has no real source
        # for, per the system prompt's instruction — not fabricate a rate.
        # Wide net of phrasing stems, not an exact string.
        assert any(
            phrase in explanation
            for phrase in (
                "available",  # "not/isn't/unavailable" — paired with the negation check below
                "don't have",
                "doesn't have",
                "can't provide",
                "cannot provide",
                "not track",
                "no live",
                "not accessible",
                "not able to",
            )
        )
        assert "n't" in explanation or "not" in explanation or "no " in explanation  # some negation is present
