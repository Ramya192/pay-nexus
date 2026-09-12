"""
Unit tests for compression/context_compressor.py's Level 1 (sliding window)
and Level 2 (cap_session_history) logic — the pure-Python halves of context
compression that don't need a real LLM call. compress_session_summary's
actual OpenAI call is exercised separately under @pytest.mark.integration;
its no-exchanges early-return path (no network call at all) is covered here
since that's the exact "None means absence, not a free call" distinction
compression/eval.py's cost-savings harness depends on.
"""

import pytest

from compression.context_compressor import (
    _MAX_SESSIONS,
    _SLIDING_WINDOW,
    cap_session_history,
    compress_in_session,
    compress_session_summary,
)
from config import config


@pytest.fixture(autouse=True)
def _compression_enabled(monkeypatch):
    # Both functions early-return the input unchanged when compression is
    # off — pin it on for these tests regardless of the real .env value, and
    # restore automatically after each test since monkeypatch reverts it.
    monkeypatch.setattr(config, "ENABLE_CONTEXT_COMPRESSION", True)


class TestCompressInSession:
    def test_keeps_only_last_n_exchanges(self):
        exchanges = [{"turn": i} for i in range(10)]
        result = compress_in_session(exchanges)
        assert len(result) == _SLIDING_WINDOW
        assert result == exchanges[-_SLIDING_WINDOW:]

    def test_fewer_than_window_returned_unchanged(self):
        exchanges = [{"turn": 1}]
        assert compress_in_session(exchanges) == exchanges

    def test_disabled_returns_everything(self, monkeypatch):
        monkeypatch.setattr(config, "ENABLE_CONTEXT_COMPRESSION", False)
        exchanges = [{"turn": i} for i in range(10)]
        assert compress_in_session(exchanges) == exchanges


class TestCompressInSessionDynamic:
    """headroom_tokens given — the capacity-aware mode (2026-09-12), sized
    against a real context window instead of the old flat _SLIDING_WINDOW."""

    def test_generous_headroom_keeps_more_than_the_old_fixed_window(self):
        exchanges = [{"query": f"q{i}", "response": f"a{i}"} for i in range(10)]
        result = compress_in_session(exchanges, headroom_tokens=100_000)
        assert len(result) > _SLIDING_WINDOW
        assert result == exchanges[-len(result):]  # still a suffix — oldest dropped first

    def test_tiny_headroom_still_keeps_the_floor(self):
        exchanges = [{"query": "a very long question " * 50, "response": "a very long answer " * 50}] * 5
        result = compress_in_session(exchanges, headroom_tokens=1)
        assert len(result) == 1
        assert result[0] == exchanges[-1]

    def test_never_exceeds_the_dynamic_ceiling(self):
        exchanges = [{"query": f"q{i}", "response": f"a{i}"} for i in range(50)]
        result = compress_in_session(exchanges, headroom_tokens=10_000_000)
        from compression.context_compressor import _MAX_KEPT_EXCHANGES

        assert len(result) == _MAX_KEPT_EXCHANGES

    def test_disabled_ignores_headroom_and_returns_everything(self, monkeypatch):
        monkeypatch.setattr(config, "ENABLE_CONTEXT_COMPRESSION", False)
        exchanges = [{"query": f"q{i}", "response": f"a{i}"} for i in range(10)]
        assert compress_in_session(exchanges, headroom_tokens=1) == exchanges


class TestCapSessionHistory:
    def test_keeps_only_most_recent_n(self):
        # newest-first, per GET /payslip/history ordering — a head-slice,
        # not a re-sort.
        history = [{"session": i} for i in range(15)]
        result = cap_session_history(history)
        assert len(result) == _MAX_SESSIONS
        assert result == history[:_MAX_SESSIONS]

    def test_fewer_than_cap_returned_unchanged(self):
        history = [{"session": 1}, {"session": 2}]
        assert cap_session_history(history) == history

    def test_disabled_returns_everything(self, monkeypatch):
        monkeypatch.setattr(config, "ENABLE_CONTEXT_COMPRESSION", False)
        history = [{"session": i} for i in range(15)]
        assert cap_session_history(history) == history

    def test_summary_never_embeds_full_payslip_snapshot(self):
        """Regression test for the actual reported bug: a summary must
        carry payslip_month only, never the full snapshot object — checked
        structurally (key absence), not by re-running the cost harness."""
        history = [
            {"payslip_month": "2026-03", "key_changes": [], "nudges_given": [], "regime_recommendation": "new"}
        ]
        result = cap_session_history(history)
        assert "payslip_snapshot" not in result[0]
        assert result[0]["payslip_month"] == "2026-03"


class TestCapSessionHistoryDynamic:
    """headroom_tokens given — same capacity-aware mode as
    TestCompressInSessionDynamic, mirrored for the newest-first
    session_history ordering (see cap_session_history's own docstring for
    why it reverses before/after calling trim_to_headroom)."""

    def test_generous_headroom_still_respects_the_max_sessions_ceiling(self):
        # Unlike compress_in_session's dynamic ceiling (_MAX_KEPT_EXCHANGES,
        # deliberately higher than the old fixed _SLIDING_WINDOW),
        # cap_session_history's dynamic ceiling reuses _MAX_SESSIONS itself
        # (see context_compressor.py's comment on _MAX_KEPT_SESSIONS) — so
        # generous headroom reaches that same cap, not more than it.
        history = [{"session": i} for i in range(20)]
        result = cap_session_history(history, headroom_tokens=100_000)
        assert len(result) == _MAX_SESSIONS
        assert result == history[:_MAX_SESSIONS]  # still newest-first, still a prefix

    def test_tight_headroom_keeps_fewer_than_the_fixed_cap(self):
        # This is where the dynamic mode actually differs from the fixed
        # one for session summaries — trimming BELOW _MAX_SESSIONS when
        # headroom genuinely doesn't stretch that far, instead of always
        # keeping exactly _MAX_SESSIONS regardless of size.
        history = [{"session": i, "key_changes": ["a fairly long note here"] * 20} for i in range(20)]
        result = cap_session_history(history, headroom_tokens=200)
        assert 0 < len(result) < _MAX_SESSIONS
        assert result == history[: len(result)]

    def test_tiny_headroom_still_keeps_the_floor_and_the_newest_one(self):
        history = [{"session": i, "key_changes": ["x"] * 200} for i in range(5)]
        result = cap_session_history(history, headroom_tokens=1)
        assert len(result) == 1
        assert result[0] == history[0]  # newest-first — index 0 is the most recent

    def test_never_exceeds_the_max_sessions_ceiling_even_with_huge_headroom(self):
        history = [{"session": i} for i in range(50)]
        result = cap_session_history(history, headroom_tokens=10_000_000)
        assert len(result) == _MAX_SESSIONS

    def test_disabled_ignores_headroom_and_returns_everything(self, monkeypatch):
        monkeypatch.setattr(config, "ENABLE_CONTEXT_COMPRESSION", False)
        history = [{"session": i} for i in range(15)]
        assert cap_session_history(history, headroom_tokens=1) == history


class TestCompressSessionSummaryNoExchanges:
    def test_no_exchanges_returns_default_summary_with_no_llm_call(self):
        """No network call happens here at all (not a call that costs $0 —
        an actual absence of one), which is why metrics must come back
        None rather than a zero-cost LLMCallMetrics."""
        summary, metrics = compress_session_summary([], {"month": "2026-04"})
        assert metrics is None
        assert summary == {
            "payslip_month": "2026-04",
            "key_changes": [],
            "nudges_given": [],
            "regime_recommendation": "",
        }

    def test_no_exchanges_no_payslip_month_defaults_to_empty_string(self):
        summary, metrics = compress_session_summary([], {})
        assert metrics is None
        assert summary["payslip_month"] == ""
