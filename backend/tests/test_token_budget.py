"""
Unit tests for compression/token_budget.py — the pre-call token estimator
and capacity-aware trim logic behind context_compressor.py's dynamic mode.
Pure Python, no LLM/network call anywhere in this module, so none of this
needs @pytest.mark.integration.
"""

from compression import token_budget


class TestCountTokens:
    def test_empty_string_is_zero(self):
        assert token_budget.count_tokens("") == 0

    def test_real_model_uses_tiktoken_not_chars_over_4(self):
        # tiktoken is a real dependency in this environment (requirements.txt) —
        # confirm the real encoder path actually runs, not just the fallback.
        # The ₹ symbol alone is 2-3 BPE tokens under o200k_base but a single
        # character, so an exact tiktoken count and the naive chars/4 guess
        # diverge noticeably on real text containing one — that gap is what
        # distinguishes "the real encoder ran" from "silently using the
        # fallback despite tiktoken being installed."
        text = "₹" * 20
        exact = token_budget.count_tokens(text, model="gpt-4o")
        naive_fallback = max(1, len(text) // token_budget._CHARS_PER_TOKEN_ESTIMATE)
        assert exact > naive_fallback

    def test_unknown_model_falls_back_to_chars_estimate(self, monkeypatch):
        # Forcing _encoding_for to report "no real encoding" (as it does for
        # phi4-mini in practice — not a tiktoken/BPE model at all) without
        # needing to actually uninstall tiktoken for the test.
        monkeypatch.setattr(token_budget, "_encoding_for", lambda model: None)
        text = "x" * 40
        assert token_budget.count_tokens(text, model="phi4-mini") == 10  # 40 // 4

    def test_never_raises_on_encode_failure(self, monkeypatch):
        class _BoomEncoding:
            def encode(self, text):
                raise RuntimeError("boom")

        monkeypatch.setattr(token_budget, "_encoding_for", lambda model: _BoomEncoding())
        # Falls back to the chars/4 estimate instead of propagating the error.
        assert token_budget.count_tokens("abcd", model="gpt-4o") == 1


class TestContextWindowFor:
    def test_known_models(self):
        assert token_budget.context_window_for("gpt-4o") == 128_000
        assert token_budget.context_window_for("phi4-mini") == 4_096

    def test_unknown_model_uses_conservative_default(self):
        assert token_budget.context_window_for("some-future-model") == token_budget._DEFAULT_CONTEXT_WINDOW


class TestHeadroomTokens:
    def test_large_window_leaves_real_headroom(self):
        headroom = token_budget.headroom_tokens(128_000)
        assert headroom > 100_000  # most of a 128K window should still be free

    def test_tiny_window_floors_at_zero_rather_than_negative(self):
        # A window smaller than FIXED_OVERHEAD_TOKENS + RESERVED_OUTPUT_TOKENS
        # alone (3,000 combined) has genuinely nothing left over — zero, not
        # a negative number of tokens.
        assert token_budget.headroom_tokens(2_000) == 0

    def test_phi4_mini_window_leaves_only_a_thin_margin(self):
        # phi4-mini's real 4,096-token window (MODEL_CONTEXT_WINDOW) is only
        # just above the fixed overhead — confirms the formula leaves a
        # small but genuine allowance here, not a full-window's worth.
        headroom = token_budget.headroom_tokens(token_budget.context_window_for("phi4-mini"))
        assert 0 < headroom < 1_000

    def test_scales_with_window_size(self):
        assert token_budget.headroom_tokens(128_000) > token_budget.headroom_tokens(16_000)


class TestTrimToHeadroom:
    @staticmethod
    def _render(item):
        return item["text"]

    def test_empty_input_returns_empty(self):
        assert token_budget.trim_to_headroom([], self._render, 1000) == []

    def test_keeps_everything_when_headroom_is_generous(self):
        items = [{"text": f"turn {i}"} for i in range(5)]
        result = token_budget.trim_to_headroom(items, self._render, headroom=10_000, max_keep=20)
        assert result == items

    def test_drops_oldest_first_under_tight_headroom(self):
        # Each item is ~1 token ("turn N"); headroom of a handful of tokens
        # should keep only the most recent few, oldest dropped first.
        items = [{"text": f"t{i}"} for i in range(10)]
        result = token_budget.trim_to_headroom(items, self._render, headroom=3, model="gpt-4o", max_keep=None)
        assert result == items[-len(result):]  # whatever's kept is a suffix (most recent)
        assert len(result) < len(items)

    def test_min_keep_floor_even_when_it_does_not_fit(self):
        items = [{"text": "a very long turn " * 50}, {"text": "another very long turn " * 50}]
        result = token_budget.trim_to_headroom(items, self._render, headroom=1, min_keep=1)
        assert len(result) == 1
        assert result[0] == items[-1]  # the floor keeps the MOST RECENT one

    def test_max_keep_ceiling_even_with_huge_headroom(self):
        items = [{"text": f"turn {i}"} for i in range(50)]
        result = token_budget.trim_to_headroom(items, self._render, headroom=1_000_000, max_keep=5)
        assert len(result) == 5
        assert result == items[-5:]

    def test_order_preserved_oldest_first(self):
        items = [{"text": f"turn {i}"} for i in range(5)]
        result = token_budget.trim_to_headroom(items, self._render, headroom=1_000_000, max_keep=3)
        assert [r["text"] for r in result] == ["turn 2", "turn 3", "turn 4"]
