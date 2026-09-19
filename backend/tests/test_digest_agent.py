"""
Unit tests for agents/digest_agent.py's prompt-building logic — mocked
`agent_complete`, no real LLM call, no network. Verifies the wiring (state
in, correct sections included/skipped, correct state keys out), not answer
quality — same offline-test-double approach as
tests/test_agent_framework_llm.py uses for the retry heuristic.
"""

import json

from agents.digest_agent import digest_agent_node
from agents.llm_metrics import LLMCallMetrics


def _fake_metrics() -> LLMCallMetrics:
    return LLMCallMetrics(agent="digest_agent", model="gpt-4o", input_tokens=100, output_tokens=20, cost_usd=0.001, latency_ms=500.0)


class TestDigestAgentNode:
    def test_returns_the_expected_state_keys(self, monkeypatch):
        metrics = _fake_metrics()

        async def fake_agent_complete(system_prompt, user_prompt, model, response_model, agent):
            return json.dumps({"explanation": "You saved ₹5,000 this month.", "tables": []}), metrics

        monkeypatch.setattr("agents.digest_agent.agent_complete", fake_agent_complete)

        state = {
            "user_query": "how did I do this month?",
            "payslip_history": [],
            "transactions": [],
            "goals": [],
            "budgets": {},
            "conversation": [],
        }
        result = digest_agent_node(state)

        assert "digest_response" in result
        assert "digest_tables" in result
        assert "digest_llm_calls" in result
        assert result["digest_llm_calls"] == [metrics]
        parsed = json.loads(result["digest_response"])
        assert parsed["explanation"] == "You saved ₹5,000 this month."

    def test_budget_section_skipped_when_no_budgets_set(self, monkeypatch):
        captured = {}

        async def fake_agent_complete(system_prompt, user_prompt, model, response_model, agent):
            captured["user_prompt"] = user_prompt
            return json.dumps({"explanation": "recap", "tables": []}), _fake_metrics()

        monkeypatch.setattr("agents.digest_agent.agent_complete", fake_agent_complete)

        state = {
            "user_query": "how did I do this month?",
            "payslip_history": [],
            "transactions": [],
            "goals": [],
            "budgets": {},  # empty -- no budget section should be built
            "conversation": [],
        }
        digest_agent_node(state)
        assert "Budget check" not in captured["user_prompt"]

    def test_budget_section_included_when_budgets_are_set(self, monkeypatch):
        captured = {}

        async def fake_agent_complete(system_prompt, user_prompt, model, response_model, agent):
            captured["user_prompt"] = user_prompt
            return json.dumps({"explanation": "recap", "tables": []}), _fake_metrics()

        monkeypatch.setattr("agents.digest_agent.agent_complete", fake_agent_complete)

        state = {
            "user_query": "how did I do this month?",
            "payslip_history": [],
            "transactions": [
                {"date": "2026-07-05", "description": "RENT PAYMENT", "amount": -18000, "category": "Rent", "statement_period": "2026-07"}
            ],
            "goals": [],
            "budgets": {"Rent": 20000},
            "conversation": [],
        }
        digest_agent_node(state)
        assert "Budget check" in captured["user_prompt"]

    def test_all_four_domains_present_when_data_exists_for_each(self, monkeypatch):
        captured = {}

        async def fake_agent_complete(system_prompt, user_prompt, model, response_model, agent):
            captured["user_prompt"] = user_prompt
            return json.dumps({"explanation": "recap", "tables": []}), _fake_metrics()

        monkeypatch.setattr("agents.digest_agent.agent_complete", fake_agent_complete)

        state = {
            "user_query": "how did I do this month?",
            "payslip_history": [
                {"month": "2026-06", "basic": 50000, "tds": 5000, "hra": 20000},
                {"month": "2026-07", "basic": 52000, "tds": 5500, "hra": 20000},
            ],
            "transactions": [
                {"date": "2026-07-05", "description": "RENT PAYMENT", "amount": -18000, "category": "Rent", "statement_period": "2026-07"}
            ],
            "goals": [{"name": "Goa Trip", "category": "Trip", "targetAmount": 50000, "savedAmount": 12500}],
            "budgets": {"Rent": 20000},
            "conversation": [],
        }
        digest_agent_node(state)
        prompt = captured["user_prompt"]
        assert "Payslip trends" in prompt
        assert "Spending summary" in prompt
        assert "Budget check" in prompt
        assert "Goals" in prompt

    def test_uses_the_cloud_only_digest_model(self, monkeypatch):
        captured = {}

        async def fake_agent_complete(system_prompt, user_prompt, model, response_model, agent):
            captured["model"] = model
            captured["agent"] = agent
            return json.dumps({"explanation": "recap", "tables": []}), _fake_metrics()

        monkeypatch.setattr("agents.digest_agent.agent_complete", fake_agent_complete)

        state = {"user_query": "recap", "payslip_history": [], "transactions": [], "goals": [], "budgets": {}}
        digest_agent_node(state)
        assert captured["agent"] == "digest_agent"
        from config import config

        assert captured["model"] == config.DIGEST_AGENT_MODEL
