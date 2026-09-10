"""
Genuine offline unit tests for agents/agent_framework_llm.py's wiring —
using tests/fakes.py's FakeChatClient instead of a real Foundry call. This
covers something no existing test did: agent_complete()'s retry-on-
suspicious-response logic had zero deterministic test coverage before
this — only ever observed live, under real API load. No network call, no
Azure credentials, no cost.
"""

import asyncio

from pydantic import BaseModel

from agents import agent_framework_llm
from tests.fakes import FakeChatClient


class _DummyResponse(BaseModel):
    explanation: str
    tables: list[str] = []
    follow_up_suggestions: list[str] = []


def _install_fake(monkeypatch, canned_values):
    """agent_framework_llm._foundry_client() only constructs a real
    FoundryChatClient when the deployment isn't already in its module-level
    cache — pre-populating that cache with a fake is the seam this needs,
    no production code changes required to make it testable."""
    fake = FakeChatClient(canned_values)
    monkeypatch.setattr(agent_framework_llm, "_clients", {"gpt-4.1-mini": fake})
    return fake


class TestAgentCompleteWiring:
    def test_returns_the_canned_value_as_json(self, monkeypatch):
        canned = _DummyResponse(explanation="A grounded answer with ₹1,234.", tables=["gaps"])
        _install_fake(monkeypatch, canned)

        raw, metrics = asyncio.run(
            agent_framework_llm.agent_complete(
                "system prompt", "user prompt", model="gpt-4o-mini", response_model=_DummyResponse, agent="test_agent"
            )
        )

        assert raw == canned.model_dump_json()
        assert metrics.agent == "test_agent"

    def test_prompt_actually_reaches_the_client(self, monkeypatch):
        canned = _DummyResponse(explanation="x with ₹1,000")
        fake = _install_fake(monkeypatch, canned)

        asyncio.run(
            agent_framework_llm.agent_complete(
                "a distinctive system prompt", "a distinctive user prompt",
                model="gpt-4o-mini", response_model=_DummyResponse, agent="test_agent",
            )
        )

        assert len(fake.calls) == 1
        sent_texts = [c.text for m in fake.calls[0]["messages"] for c in m.contents if hasattr(c, "text")]
        assert any("a distinctive user prompt" in t for t in sent_texts)


class TestRetryOnSuspiciousResponse:
    """agent_complete()'s retry logic (agents/agent_framework_llm.py's
    _is_suspiciously_generic) was added after a real, observed failure mode
    under sustained load, but never tested deterministically before this —
    only ever caught live. This is the first test that can force both the
    bad-then-good and bad-then-bad cases on demand, offline."""

    def test_generic_first_answer_triggers_one_retry_and_uses_the_second(self, monkeypatch):
        bad = _DummyResponse(explanation="Based on your provided data.")  # no rupee figure — evasive
        good = _DummyResponse(explanation="Your total is ₹1,002,600.")
        fake = _install_fake(monkeypatch, [bad, good])

        raw, metrics = asyncio.run(
            agent_framework_llm.agent_complete(
                "system", "user", model="gpt-4o-mini", response_model=_DummyResponse, agent="test_agent"
            )
        )

        assert len(fake.calls) == 2  # confirms a retry actually happened
        assert raw == good.model_dump_json()  # the retry's (grounded) answer is what's kept
        assert metrics.agent == "test_agent"

    def test_grounded_first_answer_does_not_retry(self, monkeypatch):
        good = _DummyResponse(explanation="Your total is ₹1,002,600.")
        fake = _install_fake(monkeypatch, [good])

        asyncio.run(
            agent_framework_llm.agent_complete(
                "system", "user", model="gpt-4o-mini", response_model=_DummyResponse, agent="test_agent"
            )
        )

        assert len(fake.calls) == 1

    def test_check_for_generic_response_false_never_retries_even_on_a_short_answer(self, monkeypatch):
        """The exact false-positive orchestrator_v2.classify_intent hit —
        a short, correct classification like {"agents": ["budget"]} has no
        rupee figure and would otherwise misfire the retry check."""
        short_but_correct = _DummyResponse(explanation="ok")
        fake = _install_fake(monkeypatch, [short_but_correct])

        asyncio.run(
            agent_framework_llm.agent_complete(
                "system", "user", model="gpt-4o-mini", response_model=_DummyResponse, agent="test_agent",
                check_for_generic_response=False,
            )
        )

        assert len(fake.calls) == 1

    def test_two_bad_answers_in_a_row_still_returns_the_second_not_an_infinite_loop(self, monkeypatch):
        bad1 = _DummyResponse(explanation="Based on your data.")
        bad2 = _DummyResponse(explanation="I have presented the information.")
        fake = _install_fake(monkeypatch, [bad1, bad2])

        raw, _ = asyncio.run(
            agent_framework_llm.agent_complete(
                "system", "user", model="gpt-4o-mini", response_model=_DummyResponse, agent="test_agent"
            )
        )

        assert len(fake.calls) == 2  # exactly one retry, not more
        assert raw == bad2.model_dump_json()  # the retry's result is used regardless
