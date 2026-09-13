"""Unit tests for categorization/rules.py — pure keyword matching, no LLM
call, no network. categorize.py's LLM-fallback path is exercised in
test_spending_agent.py's integration tests instead (it needs a real
OpenAI call to test meaningfully).
"""

from categorization.rules import apply_rules


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
