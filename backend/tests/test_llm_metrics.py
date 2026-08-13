"""
Unit tests for agents/llm_metrics.py — the Pydantic-validated LLM call
metrics that PayNexusState.token_usage was declared for but never actually
populated with before this build. record_from_response's real OpenAI-object
path is exercised via a minimal fake response (no network call needed —
usage is just an attribute read).
"""

import pytest
from pydantic import ValidationError

from agents.llm_metrics import LLMCallMetrics, compute_cost_usd, record_from_response, record_manual, summarize


class _FakeUsage:
    def __init__(self, prompt_tokens, completion_tokens):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _FakeResponse:
    def __init__(self, usage):
        self.usage = usage


class TestLLMCallMetricsModel:
    def test_valid_construction(self):
        m = LLMCallMetrics(agent="payslip_agent", model="gpt-4o-mini", input_tokens=100, output_tokens=50, cost_usd=0.001, latency_ms=200.0)
        assert m.agent == "payslip_agent"
        assert m.timestamp is not None  # default_factory populated it

    def test_negative_input_tokens_rejected(self):
        with pytest.raises(ValidationError):
            LLMCallMetrics(agent="x", model="gpt-4o-mini", input_tokens=-1, output_tokens=0, cost_usd=0, latency_ms=0)

    def test_negative_cost_rejected(self):
        with pytest.raises(ValidationError):
            LLMCallMetrics(agent="x", model="gpt-4o-mini", input_tokens=0, output_tokens=0, cost_usd=-0.01, latency_ms=0)


class TestComputeCostUsd:
    def test_known_model_priced_correctly(self):
        # gpt-4o-mini: $0.15/1M input, $0.60/1M output
        cost = compute_cost_usd("gpt-4o-mini", 1_000_000, 1_000_000)
        assert cost == pytest.approx(0.75)

    def test_unknown_model_returns_zero_not_a_guess(self):
        assert compute_cost_usd("some-future-model", 1_000_000, 1_000_000) == 0.0

    def test_local_ollama_model_is_free(self):
        assert compute_cost_usd("phi4-mini", 1_000_000, 1_000_000) == 0.0

    def test_zero_tokens_zero_cost(self):
        assert compute_cost_usd("gpt-4o", 0, 0) == 0.0


class TestRecordFromResponse:
    def test_reads_exact_usage_from_response(self):
        response = _FakeResponse(_FakeUsage(prompt_tokens=200, completion_tokens=80))
        metrics = record_from_response(agent="payslip_agent", model="gpt-4o-mini", response=response, latency_ms=350.0)
        assert metrics.input_tokens == 200
        assert metrics.output_tokens == 80
        assert metrics.cost_usd == compute_cost_usd("gpt-4o-mini", 200, 80)

    def test_missing_usage_defaults_to_zero_not_a_crash(self):
        response = _FakeResponse(usage=None)
        metrics = record_from_response(agent="x", model="gpt-4o-mini", response=response, latency_ms=1.0)
        assert metrics.input_tokens == 0
        assert metrics.output_tokens == 0


class TestRecordManual:
    def test_builds_metrics_from_caller_supplied_counts(self):
        metrics = record_manual(agent="payslip_agent", model="phi4-mini", input_tokens=500, output_tokens=300, latency_ms=900.0)
        assert metrics.input_tokens == 500
        assert metrics.cost_usd == 0.0  # phi4-mini is local/free


class TestSummarize:
    def test_empty_list(self):
        result = summarize([])
        assert result["total_input_tokens"] == 0
        assert result["total_cost_usd"] == 0.0
        assert result["by_agent"] == {}
        assert result["calls"] == []

    def test_aggregates_totals_across_calls(self):
        calls = [
            LLMCallMetrics(agent="payslip_agent", model="gpt-4o-mini", input_tokens=100, output_tokens=50, cost_usd=0.001, latency_ms=200),
            LLMCallMetrics(agent="nudge_agent", model="gpt-4o-mini", input_tokens=200, output_tokens=100, cost_usd=0.002, latency_ms=300),
        ]
        result = summarize(calls)
        assert result["total_input_tokens"] == 300
        assert result["total_output_tokens"] == 150
        assert result["total_cost_usd"] == pytest.approx(0.003)
        assert len(result["calls"]) == 2

    def test_groups_by_agent_separately_from_totals(self):
        calls = [
            LLMCallMetrics(agent="payslip_agent", model="gpt-4o-mini", input_tokens=100, output_tokens=50, cost_usd=0.001, latency_ms=200),
            LLMCallMetrics(agent="payslip_agent", model="gpt-4o-mini", input_tokens=50, output_tokens=25, cost_usd=0.0005, latency_ms=150),
            LLMCallMetrics(agent="nudge_agent", model="gpt-4o-mini", input_tokens=200, output_tokens=100, cost_usd=0.002, latency_ms=300),
        ]
        result = summarize(calls)
        assert result["by_agent"]["payslip_agent"]["calls"] == 2
        assert result["by_agent"]["payslip_agent"]["input_tokens"] == 150
        assert result["by_agent"]["nudge_agent"]["calls"] == 1

    def test_calls_serialized_as_json_safe_dicts(self):
        calls = [LLMCallMetrics(agent="x", model="gpt-4o-mini", input_tokens=10, output_tokens=5, cost_usd=0.0001, latency_ms=50)]
        result = summarize(calls)
        assert isinstance(result["calls"][0]["timestamp"], str)  # datetime serialized, not left as an object
