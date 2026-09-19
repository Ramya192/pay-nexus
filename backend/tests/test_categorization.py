"""Unit tests for categorization/rules.py — pure keyword matching, no LLM
call, no network. categorize.py's LLM-fallback path is exercised in
test_spending_agent.py's integration tests instead (it needs a real
OpenAI call to test meaningfully). ml_classifier.py's logistic regression
tier is pure scikit-learn, no LLM/network either -- covered directly below.
"""

from categorization.ml_classifier import (
    MIN_DISTINCT_CATEGORIES,
    MIN_TRAINING_EXAMPLES,
    predict_categories,
)
from categorization.rules import apply_rules

# A deliberately synthetic but internally-consistent training set -- real
# per-user data at runtime comes from the client's own decrypted history
# (see ml_classifier.py's docstring), not from anything like this fixture.
# Deliberately uses merchants NOT in rules.py's RULES dict (real ones like
# SWIGGY/UBER would get caught by the rules tier first, never reaching this
# one) -- these test the ML tier specifically, not rules.py.
_TRAINING_DATA: list[tuple[str, str]] = (
    [(f"CURRY HOUSE ORDER #{i}", "Food & Dining") for i in range(10)]
    + [(f"CITYCAB TRIP {i}", "Transport") for i in range(10)]
    + [(f"BOOKS BAZAAR ORDER {i}", "Shopping") for i in range(10)]
)


class TestApplyRules:
    def test_known_merchant_matched_case_insensitively(self):
        assert apply_rules("SWIGGY ORDER #1234") == "Food & Dining"
        assert apply_rules("swiggy order #1234") == "Food & Dining"

    def test_salary_credit_matched_to_income(self):
        assert apply_rules("SALARY CREDIT - ACME CORP") == "Income"

    def test_unknown_merchant_returns_none(self):
        assert apply_rules("SOME RANDOM LOCAL SHOP") is None

    def test_subscriptions_checked_before_shopping(self):
        """Dict order matters (rules.py's own docstring) — "AMAZON PRIME
        MEMBERSHIP" must match "AMAZON PRIME" (Subscriptions) rather than
        the broader "AMAZON" keyword (Shopping) catching it first."""
        assert apply_rules("AMAZON PRIME MEMBERSHIP RENEWAL") == "Subscriptions"

    def test_broader_amazon_purchase_falls_to_shopping(self):
        assert apply_rules("AMAZON.IN PURCHASE") == "Shopping"


class TestMlClassifier:
    def test_too_few_examples_skips_tier_entirely(self):
        tiny_training_set = _TRAINING_DATA[: MIN_TRAINING_EXAMPLES - 1]
        results = predict_categories(["CURRY HOUSE ORDER #99"], tiny_training_set)
        assert results == [(None, 0.0)]

    def test_single_category_skips_tier_even_with_enough_examples(self):
        assert MIN_DISTINCT_CATEGORIES > 1, "this test assumes the real threshold is >1"
        one_category_only = [(f"SWIGGY ORDER #{i}", "Food & Dining") for i in range(30)]
        results = predict_categories(["SWIGGY ORDER #99"], one_category_only)
        assert results == [(None, 0.0)]

    def test_empty_descriptions_returns_empty_list(self):
        assert predict_categories([], _TRAINING_DATA) == []

    def test_similar_description_confidently_matches_its_training_category(self):
        (category, confidence), = predict_categories(["CURRY HOUSE ORDER #999"], _TRAINING_DATA)
        assert category == "Food & Dining"
        assert confidence >= 0.6

    def test_dissimilar_description_falls_through_with_no_confident_category(self):
        """Genuinely unrelated to either training category -- the model
        should not force a confident-looking guess onto data it has no real
        basis for, same "don't force a bad match" principle categorize.py's
        LLM prompt already states explicitly."""
        (category, _confidence), = predict_categories(
            ["ELECTRICITY BOARD BILL PAYMENT XYZCORP"], _TRAINING_DATA
        )
        assert category is None

    def test_multiple_descriptions_predicted_independently_in_order(self):
        results = predict_categories(["CURRY HOUSE ORDER #1", "CITYCAB TRIP 1"], _TRAINING_DATA)
        assert len(results) == 2
        assert results[0][0] == "Food & Dining"
        assert results[1][0] == "Transport"


class TestCategorizeTransactionsTierOrdering:
    """categorize.py's own 3-tier orchestration (rules -> ml -> llm) --
    proves the ML tier genuinely short-circuits the LLM call when confident,
    not just that ml_classifier.py works correctly in isolation."""

    def test_confident_ml_match_never_calls_the_llm(self, monkeypatch):
        import categorization.categorize as categorize_module
        from models import Transaction

        def _fail_if_called(*args, **kwargs):
            raise AssertionError("LLM fallback should not have been called")

        monkeypatch.setattr(categorize_module._client.chat.completions, "create", _fail_if_called)

        txn = Transaction(
            transaction_id="t1",
            date=__import__("datetime").date(2026, 1, 1),
            description="CURRY HOUSE ORDER #999",
            amount=450.0,
            source_account="Test Bank",
        )
        result = categorize_module.categorize_transactions([txn], _TRAINING_DATA)
        assert result[0].category == "Food & Dining"
        assert result[0].category_source == "ml"

    def test_stale_invalid_historical_category_is_filtered_not_learned(self, monkeypatch):
        """historical_labels comes from the client -- old saved data could
        carry a category from before categories.py's CATEGORIES changed.
        The model must never be trained on (let alone predict) something
        outside the current closed set, or it could hand BudgetPlanner a
        category it doesn't recognize."""
        import categorization.categorize as categorize_module
        from models import Transaction

        def _fail_if_called(*args, **kwargs):
            raise AssertionError("LLM fallback should not have been called")

        monkeypatch.setattr(categorize_module._client.chat.completions, "create", _fail_if_called)

        poisoned_labels = _TRAINING_DATA + [
            (f"OLD STALE CATEGORY ROW {i}", "Discontinued Category") for i in range(15)
        ]
        txn = Transaction(
            transaction_id="t1",
            date=__import__("datetime").date(2026, 1, 1),
            description="OLD STALE CATEGORY ROW 999",
            amount=100.0,
            source_account="Test Bank",
        )
        # Should fall through to the (mocked, failing) LLM tier rather than
        # ever land on "Discontinued Category" -- proves the filter, not
        # just that predict_categories() was called correctly.
        try:
            categorize_module.categorize_transactions([txn], poisoned_labels)
        except AssertionError as exc:
            assert "LLM fallback" in str(exc)
        else:
            raise AssertionError("expected the mocked LLM call to raise")

    def test_rules_still_take_priority_over_the_ml_tier(self, monkeypatch):
        """A rules.py match (e.g. NETFLIX -> Subscriptions) should never
        even reach the ML tier, regardless of what historical_labels says --
        rules stay the fastest, most deterministic first pass."""
        import categorization.categorize as categorize_module
        from models import Transaction

        txn = Transaction(
            transaction_id="t1",
            date=__import__("datetime").date(2026, 1, 1),
            description="NETFLIX MONTHLY SUBSCRIPTION",
            amount=649.0,
            source_account="Test Bank",
        )
        result = categorize_module.categorize_transactions([txn], _TRAINING_DATA)
        assert result[0].category == "Subscriptions"
        assert result[0].category_source == "rule"
