"""Unit tests for analytics/spending_trends.py and analytics/recurring.py —
plain Python aggregation, no LLM, no network. Transactions here are plain
dicts, matching how they travel through PayNexusState (agents/state.py).
"""

from analytics.recurring import find_recurring_merchants, subscriptions_table
from analytics.spending_trends import (
    period_span_months,
    spending_by_category,
    spending_by_category_and_period,
    spending_by_period,
)


def _txn(date, description, amount, category=None, statement_period=None):
    return {
        "date": date,
        "description": description,
        "amount": amount,
        "category": category,
        "statement_period": statement_period,
    }


class TestSpendingByCategory:
    def test_totals_expenses_only_sorted_highest_first(self):
        transactions = [
            _txn("2026-07-01", "SALARY CREDIT", 75000, "Income"),
            _txn("2026-07-02", "SWIGGY", -500, "Food & Dining"),
            _txn("2026-07-03", "SWIGGY", -300, "Food & Dining"),
            _txn("2026-07-04", "RENT PAYMENT", -18000, "Rent"),
        ]
        result = spending_by_category(transactions)
        assert [c.category for c in result] == ["Rent", "Food & Dining"]
        assert result[1].total_spent == 800

    def test_missing_category_bucketed_as_uncategorized(self):
        transactions = [_txn("2026-07-01", "UNKNOWN SHOP", -100, None)]
        result = spending_by_category(transactions)
        assert result[0].category == "Uncategorized"

    def test_no_expenses_returns_empty_list(self):
        transactions = [_txn("2026-07-01", "SALARY CREDIT", 75000, "Income")]
        assert spending_by_category(transactions) == []


class TestSpendingByPeriod:
    def test_totals_per_calendar_month_when_no_statement_period_given(self):
        """Fallback path — transactions with no statement_period (e.g. old
        saved data, hand-entered rows) still bucket by calendar month."""
        transactions = [
            _txn("2026-07-15", "SWIGGY", -500, "Food & Dining"),
            _txn("2026-06-10", "SWIGGY", -300, "Food & Dining"),
            _txn("2026-06-20", "DMART", -1000, "Groceries"),
        ]
        result = spending_by_period(transactions)
        assert [p.period for p in result] == ["2026-06", "2026-07"]
        assert result[0].total_spent == 1300
        assert result[1].total_spent == 500


class TestStatementPeriodGrouping:
    """The exact reported gap: a credit card's 16th-to-15th billing cycle
    spans two calendar months. Grouping by the transaction's own date would
    silently split one statement's spend across two "months" even though
    the user uploaded and labeled it as a single period — these tests lock
    in that a shared statement_period keeps it as one bucket instead."""

    def test_billing_cycle_crossing_calendar_months_stays_one_period(self):
        transactions = [
            _txn("2026-07-20", "AMAZON.IN", -2000, "Shopping", statement_period="16 Jul 2026 to 15 Aug 2026"),
            _txn("2026-08-10", "SWIGGY", -500, "Food & Dining", statement_period="16 Jul 2026 to 15 Aug 2026"),
        ]
        result = spending_by_period(transactions)
        assert len(result) == 1
        assert result[0].period == "16 Jul 2026 to 15 Aug 2026"
        assert result[0].total_spent == 2500

    def test_two_statements_with_distinct_period_labels_stay_separate(self):
        transactions = [
            _txn("2026-07-20", "SWIGGY", -500, "Food & Dining", statement_period="2026-07"),
            _txn("2026-08-10", "SWIGGY", -700, "Food & Dining", statement_period="2026-08"),
        ]
        result = spending_by_category_and_period(transactions)
        assert result["2026-07"]["Food & Dining"] == 500
        assert result["2026-08"]["Food & Dining"] == 700

    def test_mixed_statement_period_and_fallback_transactions(self):
        """A transaction with an explicit statement_period and one without
        (falling back to its own calendar month) can coexist without
        colliding."""
        transactions = [
            _txn("2026-07-20", "AMAZON.IN", -2000, "Shopping", statement_period="16 Jul 2026 to 15 Aug 2026"),
            _txn("2026-07-05", "DMART", -1000, "Groceries"),  # no statement_period -> falls back to "2026-07"
        ]
        result = spending_by_period(transactions)
        periods = {p.period: p.total_spent for p in result}
        assert periods == {"16 Jul 2026 to 15 Aug 2026": 2000, "2026-07": 1000}


class TestPeriodSpanMonths:
    def test_single_day_period_floored_at_one_month(self):
        transactions = [_txn("2026-07-01", "SWIGGY", -500, "Food & Dining", "2026-07")]
        assert period_span_months(transactions, "2026-07") == 1.0

    def test_clean_calendar_month_is_about_one(self):
        transactions = [
            _txn("2026-07-01", "SALARY", 75000, "Income", "2026-07"),
            _txn("2026-07-31", "RENT", -18000, "Rent", "2026-07"),
        ]
        assert 0.99 <= period_span_months(transactions, "2026-07") <= 1.02

    def test_thirty_day_billing_cycle_across_month_boundary_is_about_one(self):
        """The exact scenario the statement-period fix (not this proration
        fix) targets: a credit card's 16th-to-15th cycle. Confirms this
        function doesn't undo that fix by inflating a normal ~30-day cycle
        just because it touches two calendar months."""
        period = "16 Jul 2026 to 15 Aug 2026"
        transactions = [
            _txn("2026-07-16", "RENT", -18000, "Rent", period),
            _txn("2026-08-15", "AMAZON.IN", -1200, "Shopping", period),
        ]
        assert 0.95 <= period_span_months(transactions, period) <= 1.05

    def test_period_spanning_46_days_scales_up(self):
        """The real bug found in testing: a statement covering 01 Jul-15
        Aug (46 days) is genuinely ~1.5 months, not 1."""
        period = "2026-07 to 2026-08"
        transactions = [
            _txn("2026-07-01", "RENT", -18000, "Rent", period),
            _txn("2026-08-15", "RENT", -18000, "Rent", period),
        ]
        months = period_span_months(transactions, period)
        assert 1.4 <= months <= 1.6

    def test_only_considers_transactions_in_the_given_period(self):
        transactions = [
            _txn("2026-06-01", "SWIGGY", -500, "Food & Dining", "2026-06"),
            _txn("2026-06-30", "SWIGGY", -500, "Food & Dining", "2026-06"),
            _txn("2026-07-01", "SWIGGY", -500, "Food & Dining", "2026-07"),
        ]
        # "2026-06" spans 30 days (~1 month); "2026-07" has one transaction
        # (~1 month, floored) — neither should be inflated by the other.
        assert period_span_months(transactions, "2026-06") <= 1.05
        assert period_span_months(transactions, "2026-07") == 1.0

    def test_no_transactions_in_period_defaults_to_one(self):
        transactions = [_txn("2026-07-01", "SWIGGY", -500, "Food & Dining", "2026-07")]
        assert period_span_months(transactions, "2026-12") == 1.0

    def test_missing_date_field_does_not_crash(self):
        transactions = [{"description": "x", "amount": -1, "category": "Shopping", "statement_period": "2026-07"}]
        assert period_span_months(transactions, "2026-07") == 1.0


class TestFindRecurringMerchants:
    def test_merchant_below_min_occurrences_excluded(self):
        transactions = [_txn("2026-07-01", "ONE OFF SHOP", -200, "Shopping")]
        assert find_recurring_merchants(transactions) == []

    def test_recurring_merchant_ranked_by_total_spent(self):
        transactions = [
            _txn("2026-06-01", "NETFLIX", -500, "Subscriptions"),
            _txn("2026-07-01", "NETFLIX", -500, "Subscriptions"),
            _txn("2026-06-05", "SPOTIFY", -119, "Subscriptions"),
            _txn("2026-07-05", "SPOTIFY", -119, "Subscriptions"),
        ]
        result = find_recurring_merchants(transactions)
        assert [m.description for m in result] == ["NETFLIX", "SPOTIFY"]
        assert result[0].occurrences == 2
        assert result[0].total_spent == 1000
        assert result[0].avg_interval_days == 30

    def test_income_rows_never_counted_as_recurring(self):
        transactions = [
            _txn("2026-06-01", "SALARY CREDIT", 75000, "Income"),
            _txn("2026-07-01", "SALARY CREDIT", 75000, "Income"),
        ]
        assert find_recurring_merchants(transactions) == []

    def test_category_filter_excludes_non_matching_merchants(self):
        """The real gap this fixes: 'what subscriptions am I paying for'
        previously returned every repeat merchant (a grocery store, a
        ride-hailing app), not just ones actually tagged Subscriptions."""
        transactions = [
            _txn("2026-06-01", "NETFLIX", -500, "Subscriptions"),
            _txn("2026-07-01", "NETFLIX", -500, "Subscriptions"),
            _txn("2026-06-05", "DMART PURCHASE", -2000, "Groceries"),
            _txn("2026-07-05", "DMART PURCHASE", -2000, "Groceries"),
        ]
        result = find_recurring_merchants(transactions, category="Subscriptions")
        assert [m.description for m in result] == ["NETFLIX"]

    def test_category_filter_none_returns_everything(self):
        transactions = [
            _txn("2026-06-01", "NETFLIX", -500, "Subscriptions"),
            _txn("2026-07-01", "NETFLIX", -500, "Subscriptions"),
            _txn("2026-06-05", "DMART PURCHASE", -2000, "Groceries"),
            _txn("2026-07-05", "DMART PURCHASE", -2000, "Groceries"),
        ]
        result = find_recurring_merchants(transactions, category=None)
        assert {m.description for m in result} == {"NETFLIX", "DMART PURCHASE"}


class TestSubscriptionsTable:
    def test_none_when_no_recurring_subscription(self):
        transactions = [
            _txn("2026-06-05", "DMART PURCHASE", -2000, "Groceries"),
            _txn("2026-07-05", "DMART PURCHASE", -2000, "Groceries"),
        ]
        assert subscriptions_table(transactions) is None

    def test_only_includes_subscriptions_category(self):
        transactions = [
            _txn("2026-06-01", "NETFLIX", -500, "Subscriptions"),
            _txn("2026-07-01", "NETFLIX", -500, "Subscriptions"),
            _txn("2026-06-05", "UBER TRIP", -200, "Transport"),
            _txn("2026-07-05", "UBER TRIP", -200, "Transport"),
        ]
        table = subscriptions_table(transactions)
        assert table["title"] == "Recurring subscriptions"
        assert [row[0] for row in table["rows"]] == ["NETFLIX"]
