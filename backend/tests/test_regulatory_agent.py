"""Tests for agents/regulatory_agent.py's RAG-then-web-search fallback (see
its module docstring for why this exists — a real, live-testing-found gap:
a genuine RAG miss got a hedged non-answer instead of an actual search
further). Offline — monkeypatches retrieve_with_scores/
hybrid_agent_complete_text/web_search_complete_text directly, no real
LLM/pgvector calls, so no @pytest.mark.integration needed here. The
underlying answer *quality* of each real call is covered by
test_integration_agents.py and manual live verification (see the module
docstring's "confirmed via direct testing" note) — this file is about the
branching logic: does a genuine miss trigger the fallback, does a real hit
not, and does cost accounting include every real call that happened.
"""

from langchain_core.documents import Document

from agents.llm_metrics import LLMCallMetrics
from agents.regulatory_agent import _WEB_SEARCH_MISS_SENTINEL, _WEB_SEARCH_SENTINEL, regulatory_agent_node

_FAKE_RESULTS = [(Document(page_content="Some retrieved text.", metadata={"source": "it_act_key_sections.md"}), 0.42)]

_RAG_METRICS = LLMCallMetrics(agent="regulatory_agent", model="gpt-4.1-mini", input_tokens=100, output_tokens=20, cost_usd=0.0005, latency_ms=500)
_WEB_METRICS = LLMCallMetrics(agent="regulatory_agent", model="gpt-4o", input_tokens=5000, output_tokens=300, cost_usd=0.02, latency_ms=8000)


def _patch_retrieval(monkeypatch):
    monkeypatch.setattr("agents.regulatory_agent.retrieve_with_scores", lambda query, k: _FAKE_RESULTS)


def _fake_text_call(text: str, metrics: LLMCallMetrics):
    """Both hybrid_agent_complete_text and web_search_complete_text are
    async (regulatory_agent_node awaits them via asyncio.run) — a plain
    lambda returning a tuple isn't awaitable, so every fake here needs to
    actually be a coroutine function."""

    async def fake(*args, **kwargs):
        return text, metrics

    return fake


class TestRealAnswerSkipsFallback:
    def test_a_real_answer_does_not_trigger_web_search(self, monkeypatch):
        _patch_retrieval(monkeypatch)
        monkeypatch.setattr(
            "agents.regulatory_agent.hybrid_agent_complete_text",
            _fake_text_call("Taxable income is the portion of your income subject to tax.", _RAG_METRICS),
        )
        called = []

        async def fake_web_search(*args, **kwargs):
            called.append(1)
            return "should not be called", _WEB_METRICS

        monkeypatch.setattr("agents.regulatory_agent.web_search_complete_text", fake_web_search)

        result = regulatory_agent_node({"user_query": "what is taxable income?", "conversation": []})

        assert called == []
        assert result["regulatory_response"] == "Taxable income is the portion of your income subject to tax."
        assert result["regulatory_llm_calls"] == [_RAG_METRICS]


class TestSentinelTriggersWebSearchFallback:
    def test_exact_sentinel_triggers_fallback(self, monkeypatch):
        _patch_retrieval(monkeypatch)
        monkeypatch.setattr(
            "agents.regulatory_agent.hybrid_agent_complete_text", _fake_text_call(_WEB_SEARCH_SENTINEL, _RAG_METRICS)
        )
        web_search_calls = []

        async def fake_web_search(system_prompt, query, agent, allowed_domains):
            web_search_calls.append((query, allowed_domains))
            return "The Income-tax Act 2025 renumbered salary TDS as Section 392.", _WEB_METRICS

        monkeypatch.setattr("agents.regulatory_agent.web_search_complete_text", fake_web_search)

        result = regulatory_agent_node(
            {"user_query": "what are the new payslip rules from 2026?", "conversation": []}
        )

        assert len(web_search_calls) == 1
        searched_query, allowed_domains = web_search_calls[0]
        assert searched_query == "what are the new payslip rules from 2026?"
        assert "incometax.gov.in" in allowed_domains
        # Real cost accounting: both the RAG-check call AND the web-search
        # call actually happened and cost real tokens — both must survive
        # into regulatory_llm_calls, not just whichever answer was kept
        # (same "don't silently drop a real call's cost" principle as
        # agent_framework_llm.py's retry-merging elsewhere).
        assert result["regulatory_llm_calls"] == [_RAG_METRICS, _WEB_METRICS]
        assert "🌐" in result["regulatory_response"]
        assert "Section 392" in result["regulatory_response"]

    def test_sentinel_with_stray_whitespace_still_triggers(self, monkeypatch):
        """Prefix match, not exact equality (see regulatory_agent_node's own
        comment on why) — a model wrapping the sentinel in incidental
        whitespace shouldn't silently fall through as if it were a real
        answer."""
        _patch_retrieval(monkeypatch)
        monkeypatch.setattr(
            "agents.regulatory_agent.hybrid_agent_complete_text",
            _fake_text_call(f"  {_WEB_SEARCH_SENTINEL}  ", _RAG_METRICS),
        )
        monkeypatch.setattr("agents.regulatory_agent.web_search_complete_text", _fake_text_call("real answer", _WEB_METRICS))

        result = regulatory_agent_node({"user_query": "q", "conversation": []})

        assert len(result["regulatory_llm_calls"]) == 2
        assert "real answer" in result["regulatory_response"]

    def test_a_partial_hedge_that_is_not_the_exact_sentinel_does_not_trigger(self, monkeypatch):
        """Guards the other direction: a real, if imperfect, narrative
        answer (not the fixed sentinel) should NOT be mistaken for a
        request to search further — only the exact instructed phrase does
        that, not any answer merely containing "no rules are mentioned" or
        similar phrasing a real completion might use."""
        _patch_retrieval(monkeypatch)
        hedge = "The excerpts don't mention specific new rules, but here's what's related: ..."
        monkeypatch.setattr("agents.regulatory_agent.hybrid_agent_complete_text", _fake_text_call(hedge, _RAG_METRICS))
        called = []

        async def fake_web_search(*args, **kwargs):
            called.append(1)
            return "x", _WEB_METRICS

        monkeypatch.setattr("agents.regulatory_agent.web_search_complete_text", fake_web_search)

        result = regulatory_agent_node({"user_query": "q", "conversation": []})

        assert called == []
        assert result["regulatory_response"] == hedge
        assert result["regulatory_llm_calls"] == [_RAG_METRICS]


class TestWebSearchMissIsNotCached:
    """Real, observed cache-poisoning risk (2026-09-12, found while adding a
    curated RAG document for the "no such payslip rules exist" wrong-answer
    report): before _WEB_SEARCH_MISS_SENTINEL existed, cache_web_answer
    wrote WHATEVER the web-search call returned — including a confidently-
    worded "I couldn't find it" on a genuine search miss — into the same
    pgvector collection RAG reads from, at full trust, for the full 90-day
    TTL. See _WEB_SEARCH_MISS_SENTINEL's docstring in regulatory_agent.py
    for the full reasoning."""

    def test_a_genuine_miss_is_not_cached_and_gets_an_honest_message(self, monkeypatch):
        _patch_retrieval(monkeypatch)
        monkeypatch.setattr(
            "agents.regulatory_agent.hybrid_agent_complete_text", _fake_text_call(_WEB_SEARCH_SENTINEL, _RAG_METRICS)
        )
        monkeypatch.setattr(
            "agents.regulatory_agent.web_search_complete_text", _fake_text_call(_WEB_SEARCH_MISS_SENTINEL, _WEB_METRICS)
        )
        cache_calls = []
        monkeypatch.setattr(
            "agents.regulatory_agent.cache_web_answer", lambda query, answer: cache_calls.append((query, answer))
        )

        result = regulatory_agent_node({"user_query": "a question nothing covers", "conversation": []})

        assert cache_calls == []  # the whole point: a miss must never be written to the shared RAG collection
        assert _WEB_SEARCH_MISS_SENTINEL not in result["regulatory_response"]  # raw sentinel never shown to a user
        assert "couldn't find" in result["regulatory_response"].lower()
        # Both real calls still cost real tokens and must still be accounted for, even though neither answer
        # was cached or shown verbatim — same "don't silently drop a real call's cost" principle as elsewhere.
        assert result["regulatory_llm_calls"] == [_RAG_METRICS, _WEB_METRICS]

    def test_a_genuine_find_is_still_cached_as_before(self, monkeypatch):
        """Guards the other direction: the miss-sentinel check must not
        accidentally swallow a real, confident answer too."""
        _patch_retrieval(monkeypatch)
        monkeypatch.setattr(
            "agents.regulatory_agent.hybrid_agent_complete_text", _fake_text_call(_WEB_SEARCH_SENTINEL, _RAG_METRICS)
        )
        real_answer = "The Code on Wages (Central) Rules, 2026 prescribe Form V as the standard payslip format."
        monkeypatch.setattr(
            "agents.regulatory_agent.web_search_complete_text", _fake_text_call(real_answer, _WEB_METRICS)
        )
        cache_calls = []
        monkeypatch.setattr(
            "agents.regulatory_agent.cache_web_answer", lambda query, answer: cache_calls.append((query, answer))
        )

        result = regulatory_agent_node({"user_query": "what are the new payslip rules in 2026?", "conversation": []})

        assert cache_calls == [("what are the new payslip rules in 2026?", real_answer)]
        assert real_answer in result["regulatory_response"]
