"""
Genuine offline unit tests for agents/agent_framework_llm.py's wiring —
using tests/fakes.py's FakeChatClient instead of a real Foundry call. This
covers something no existing test did: agent_complete()'s retry-on-
suspicious-response logic had zero deterministic test coverage before
this — only ever observed live, under real API load. No network call, no
Azure credentials, no cost.
"""

import asyncio

import pytest
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


class TestFoundryCallTimeout:
    """Real, observed root cause (2026-09-11): a slow/hung Foundry call had
    no timeout anywhere, so it just hung the whole request forever — no
    error, no fallback. This is the first deterministic, offline
    reproduction of that failure mode and the fix (_run_with_timeout).

    All tests here patch the backoff constants down to near-zero — the real
    defaults (1.5s base + up to 1.5s jitter, per attempt) are deliberately
    sized for real Foundry contention, not for keeping an offline unit test
    fast; see _run_with_timeout's docstring for why they're non-zero at all."""

    @pytest.fixture(autouse=True)
    def _fast_backoff(self, monkeypatch):
        monkeypatch.setattr(agent_framework_llm, "_TIMEOUT_RETRY_BACKOFF_BASE_S", 0.01)
        monkeypatch.setattr(agent_framework_llm, "_TIMEOUT_RETRY_BACKOFF_JITTER_S", 0.0)

    def test_a_call_that_always_times_out_raises_foundry_unavailable_after_the_retry(self, monkeypatch):
        """Both the original attempt AND the built-in automatic retry see
        the same permanently-slow fake — exercises the "genuinely
        exhausted, not just unlucky once" path, and asserts the SPECIFIC
        exception type (not just any TimeoutError) so api/routes/chat.py's
        dedicated high-demand message stays reachable if this ever
        regresses."""
        canned = _DummyResponse(explanation="never actually returned in time, with ₹1")
        fake = FakeChatClient(canned, delay_seconds=999)
        monkeypatch.setattr(agent_framework_llm, "_clients", {"gpt-4.1-mini": fake})
        monkeypatch.setattr(agent_framework_llm.config, "FOUNDRY_CALL_TIMEOUT_SECONDS", 0.05)

        with pytest.raises(agent_framework_llm.FoundryUnavailableError):
            asyncio.run(
                agent_framework_llm.agent_complete(
                    "system", "user", model="gpt-4o-mini", response_model=_DummyResponse, agent="test_agent"
                )
            )

    def test_a_timeout_on_the_first_attempt_recovers_automatically_on_retry(self, monkeypatch):
        """The actual point of the 2026-09-12 addition, found live: a call
        that times out once should recover on its own, not force the user
        to notice the failure and re-ask themselves. First invocation
        hangs past the timeout; the automatic retry hits a fast, healthy
        fake and the turn succeeds with no error ever reaching the caller."""
        good = _DummyResponse(explanation="Your total is ₹1,002,600.")
        fake = FakeChatClient(good, delay_seconds=0)
        monkeypatch.setattr(agent_framework_llm, "_clients", {"gpt-4.1-mini": fake})
        monkeypatch.setattr(agent_framework_llm.config, "FOUNDRY_CALL_TIMEOUT_SECONDS", 0.05)

        invocation_count = {"n": 0}

        async def _slow_first_invocation_only(*, messages, stream, options, **kwargs):
            invocation_count["n"] += 1
            if invocation_count["n"] == 1:
                await asyncio.sleep(999)
            return await FakeChatClient._inner_get_response(fake, messages=messages, stream=stream, options=options, **kwargs)

        monkeypatch.setattr(fake, "_inner_get_response", _slow_first_invocation_only)

        raw, _ = asyncio.run(
            agent_framework_llm.agent_complete(
                "system", "user", model="gpt-4o-mini", response_model=_DummyResponse, agent="test_agent"
            )
        )

        assert raw == good.model_dump_json()
        assert invocation_count["n"] == 2  # confirms the retry actually happened, not a fluke first-attempt pass

    def test_a_hung_content_retry_call_also_times_out(self, monkeypatch):
        """The retry-on-suspicious-response path (agent_complete's second
        runner.run(), triggered by bad CONTENT — a different mechanism
        from this file's own timeout-retry) needs the same timeout guard
        as the first call — a slow content-retry shouldn't be able to hang
        forever just because it's already past the first call."""
        bad = _DummyResponse(explanation="Based on your data.")  # no rupee figure — triggers the content retry
        fake = FakeChatClient(bad, delay_seconds=0)
        monkeypatch.setattr(agent_framework_llm, "_clients", {"gpt-4.1-mini": fake})
        monkeypatch.setattr(agent_framework_llm.config, "FOUNDRY_CALL_TIMEOUT_SECONDS", 0.05)

        async def _slow_after_first(*, messages, stream, options, **kwargs):
            if fake.calls:  # first call already recorded → this is the content-retry
                await asyncio.sleep(999)
            return await FakeChatClient._inner_get_response(fake, messages=messages, stream=stream, options=options, **kwargs)

        monkeypatch.setattr(fake, "_inner_get_response", _slow_after_first)

        with pytest.raises(agent_framework_llm.FoundryUnavailableError):
            asyncio.run(
                agent_framework_llm.agent_complete(
                    "system", "user", model="gpt-4o-mini", response_model=_DummyResponse, agent="test_agent"
                )
            )

    def test_a_fast_call_within_the_timeout_is_unaffected(self, monkeypatch):
        canned = _DummyResponse(explanation="Your total is ₹1,002,600.")
        fake = FakeChatClient(canned, delay_seconds=0.01)
        monkeypatch.setattr(agent_framework_llm, "_clients", {"gpt-4.1-mini": fake})
        monkeypatch.setattr(agent_framework_llm.config, "FOUNDRY_CALL_TIMEOUT_SECONDS", 5)

        raw, _ = asyncio.run(
            agent_framework_llm.agent_complete(
                "system", "user", model="gpt-4o-mini", response_model=_DummyResponse, agent="test_agent"
            )
        )

        assert raw == canned.model_dump_json()


class TestWebSearchCompleteText:
    """Real, live bug (2026-09-12, found via code inspection, not a test
    failure — no prior test exercised this function at all): this call
    site was missed when the other 4 _run_with_timeout call sites were
    converted from a bare coroutine to a coro_factory lambda, so it passed
    `runner.run(user_prompt)` — an already-created coroutine — straight
    through as `coro_factory`. `_run_with_timeout` then does
    `coro_factory()`, which raises `TypeError: 'coroutine' object is not
    callable` on every single call, before any real network request even
    happens. This would have made the regulatory agent's entire
    web-search-fallback path (module docstring's "live web-search fallback
    for a genuine RAG miss") unconditionally crash instead of ever
    answering a RAG-miss question — the exact code path this session was
    hardening. First test of web_search_complete_text at all."""

    @pytest.fixture(autouse=True)
    def _fast_backoff(self, monkeypatch):
        monkeypatch.setattr(agent_framework_llm, "_TIMEOUT_RETRY_BACKOFF_BASE_S", 0.01)
        monkeypatch.setattr(agent_framework_llm, "_TIMEOUT_RETRY_BACKOFF_JITTER_S", 0.0)

    def test_a_fast_web_search_call_returns_the_canned_answer(self, monkeypatch):
        fake = FakeChatClient("Found it: see pib.gov.in.", delay_seconds=0.01)
        monkeypatch.setattr(agent_framework_llm, "_clients", {"gpt-4o": fake})
        monkeypatch.setattr(agent_framework_llm.config, "FOUNDRY_WEB_SEARCH_TIMEOUT_SECONDS", 5)

        text, metrics = asyncio.run(
            agent_framework_llm.web_search_complete_text(
                "system", "user", agent="regulatory_agent", allowed_domains=["pib.gov.in"]
            )
        )

        assert text == "Found it: see pib.gov.in."
        assert metrics.agent == "regulatory_agent"

    def test_a_web_search_call_that_times_out_once_still_recovers_via_retry(self, monkeypatch):
        """Proves coro_factory() is actually re-invocable here (a fresh
        coroutine per attempt) — the exact thing a bare coroutine object
        can't do, and the reason this call site's bug would have broken
        the retry, not just the happy path."""
        good = "Found it on the retry."
        fake = FakeChatClient(good, delay_seconds=0)
        monkeypatch.setattr(agent_framework_llm, "_clients", {"gpt-4o": fake})
        monkeypatch.setattr(agent_framework_llm.config, "FOUNDRY_WEB_SEARCH_TIMEOUT_SECONDS", 0.05)

        invocation_count = {"n": 0}

        async def _slow_first_invocation_only(*, messages, stream, options, **kwargs):
            invocation_count["n"] += 1
            if invocation_count["n"] == 1:
                await asyncio.sleep(999)
            return await FakeChatClient._inner_get_response(fake, messages=messages, stream=stream, options=options, **kwargs)

        monkeypatch.setattr(fake, "_inner_get_response", _slow_first_invocation_only)

        text, _ = asyncio.run(
            agent_framework_llm.web_search_complete_text(
                "system", "user", agent="regulatory_agent", allowed_domains=["pib.gov.in"]
            )
        )

        assert text == good
        assert invocation_count["n"] == 2
