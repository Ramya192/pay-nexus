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
