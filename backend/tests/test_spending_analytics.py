"""Unit tests for analytics/spending_trends.py and analytics/recurring.py —
plain Python aggregation, no LLM, no network. Transactions here are plain
dicts, matching how they travel through PayNexusState (agents/state.py).
"""

from analytics.recurring import find_recurring_merchants, subscriptions_table
from analytics.spending_trends import (
    net_savings_by_period,
    net_savings_projection_chart_data,
    period_span_months,
    project_net_savings,
    spending_by_category,
    spending_by_category_and_period,
    spending_by_period,
)


def _txn(
    date,
    description,
    amount,
    category=None,
    statement_period=None,
    counts_toward_category_spend=None,
    counts_toward_net_savings=None,
):
    txn = {
        "date": date,
        "description": description,
        "amount": amount,
        "category": category,
        "statement_period": statement_period,
    }
    # Only set when the caller actually passes a value — unlike
    # statement_period above (read via `.get(...) or fallback`, so an
    # explicit None is harmless), _expenses()/net_savings_by_period() read
    # these via `.get(key, True)`, where an explicit None key would BE the
    # value returned (not the True default) and incorrectly exclude the
    # transaction. Every pre-existing test call site never passes these
    # kwargs at all, so the key stays genuinely absent for them, exactly
    # like a real transaction dict from before this feature existed.
    if counts_toward_category_spend is not None:
        txn["counts_toward_category_spend"] = counts_toward_category_spend
    if counts_toward_net_savings is not None:
        txn["counts_toward_net_savings"] = counts_toward_net_savings
    return txn


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


class TestCreditCardBillingCycleSplit:
    """Itemized credit-card purchases and a statement's synthetic bill-
    payment record sit on opposite corners of category-spend vs.
    net-savings: a purchase should count toward "where did the money go"
    for its real billing-cycle period, but NOT toward "how much cash did I
    actually save" until the statement is paid — that's the payment
    record's job, dated at the real due date. See spending_trends.py's
    module docstring for the full reasoning."""

    def test_itemized_purchases_count_toward_category_and_period_not_net_savings(self):
        transactions = [
            _txn(
                "2026-03-22", "GROCERY STORE", -2000, "Groceries",
                statement_period="16 Mar 2026 to 14 Apr 2026", counts_toward_net_savings=False,
            ),
            _txn(
                "2026-04-05", "AMAZON.IN", -3000, "Shopping",
                statement_period="16 Mar 2026 to 14 Apr 2026", counts_toward_net_savings=False,
            ),
        ]
        period = "16 Mar 2026 to 14 Apr 2026"
        assert spending_by_category_and_period(transactions)[period] == {"Groceries": 2000, "Shopping": 3000}
        assert spending_by_period(transactions)[0].total_spent == 5000
        # The whole point: this billing cycle's real purchases must NOT
        # register as a cash-flow event of their own.
        net_periods = {p.period: p.total_spent for p in net_savings_by_period(transactions)}
        assert period not in net_periods

    def test_synthetic_payment_counts_toward_net_savings_not_category_spend(self):
        payment = _txn(
            "2026-05-05", "Credit Card Bill Payment", -5000,
            statement_period="2026-05", counts_toward_category_spend=False,
        )
        assert spending_by_category([payment]) == []
        assert spending_by_period([payment]) == []
        assert spending_by_category_and_period([payment]) == {}
        net_periods = {p.period: p.total_spent for p in net_savings_by_period([payment])}
        assert net_periods == {"2026-05": -5000}

    def test_full_scenario_payment_month_nets_correctly_without_double_counting(self):
        """The concrete reported case: a Mar15-Apr14 statement due May 5th
        must reduce MAY's net savings, not March's/April's — while March/
        April's category breakdown still reflects the real purchases, and
        May's category breakdown does NOT also show the payment as a new
        "purchase" category."""
        billing_period = "16 Mar 2026 to 14 Apr 2026"
        transactions = [
            _txn(
                "2026-03-22", "GROCERY STORE", -2000, "Groceries",
                statement_period=billing_period, counts_toward_net_savings=False,
            ),
            _txn(
                "2026-04-05", "AMAZON.IN", -3000, "Shopping",
                statement_period=billing_period, counts_toward_net_savings=False,
            ),
            _txn(
                "2026-05-05", "Credit Card Bill Payment", -5000,
                statement_period="2026-05", counts_toward_category_spend=False,
            ),
            _txn("2026-05-01", "SALARY CREDIT", 80000, "Income", statement_period="2026-05"),
        ]
        # Category breakdown: the billing cycle keeps its real purchases...
        by_period = spending_by_category_and_period(transactions)
        assert by_period[billing_period] == {"Groceries": 2000, "Shopping": 3000}
        # ...and May shows no "Uncategorized"/payment-driven category bucket.
        assert "2026-05" not in by_period

        # Net savings: May nets salary against ONLY the payment, not the
        # itemized total again (that would double the same rupees).
        net_periods = {p.period: p.total_spent for p in net_savings_by_period(transactions)}
        assert net_periods["2026-05"] == 80000 - 5000
        assert billing_period not in net_periods

    def test_defaults_preserve_existing_behavior_when_flags_absent(self):
        """Every pre-existing transaction shape (no flags at all) must
        behave identically to before this feature existed — proves the
        `.get(key, True)` fallback is a true no-op, not just a happy-path
        default."""
        transactions = [
            _txn("2026-07-01", "SALARY CREDIT", 75000, "Income"),
            _txn("2026-07-02", "SWIGGY", -500, "Food & Dining"),
            _txn("2026-07-03", "SWIGGY", -300, "Food & Dining"),
            _txn("2026-07-04", "RENT PAYMENT", -18000, "Rent"),
        ]
        result = spending_by_category(transactions)
        assert [c.category for c in result] == ["Rent", "Food & Dining"]
        assert result[1].total_spent == 800
        net_periods = {p.period: p.total_spent for p in net_savings_by_period(transactions)}
        assert net_periods["2026-07"] == 75000 - 500 - 300 - 18000


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


class TestProjectNetSavings:
    def _income_and_expense(self, month, income, expense):
        return [
            _txn(f"{month}-01", "SALARY", income, "Income"),
            _txn(f"{month}-15", "RENT PAYMENT", -expense, "Rent"),
        ]

    def test_none_with_fewer_than_three_periods(self):
        transactions = self._income_and_expense("2026-06", 50000, 30000) + self._income_and_expense(
            "2026-07", 50000, 30000
        )
        assert project_net_savings(transactions) is None

    def test_projects_a_real_trend_with_enough_periods(self):
        # Net savings of 20000, 15000, 10000 -- a clean, declining trend.
        transactions = (
            self._income_and_expense("2026-05", 50000, 30000)
            + self._income_and_expense("2026-06", 50000, 35000)
            + self._income_and_expense("2026-07", 50000, 40000)
        )
        projection = project_net_savings(transactions, periods_ahead=1)
        assert projection is not None
        assert projection.slope_per_period < 0  # genuinely declining, not just non-positive
        assert projection.projected_values[0] < 10000  # continuing the decline past the last real value
        assert projection.historical_values == [20000, 15000, 10000]

    def test_chart_data_is_none_when_projection_is_none(self):
        transactions = self._income_and_expense("2026-06", 50000, 30000)
        assert net_savings_projection_chart_data(transactions) is None

    def test_chart_data_shape_matches_what_the_frontend_chart_expects(self):
        transactions = (
            self._income_and_expense("2026-05", 50000, 30000)
            + self._income_and_expense("2026-06", 50000, 30000)
            + self._income_and_expense("2026-07", 50000, 30000)
        )
        chart_data = net_savings_projection_chart_data(transactions)
        assert chart_data is not None
        assert set(chart_data.keys()) == {
            "historical_periods",
            "historical_values",
            "projected_periods",
            "projected_values",
            "r_squared",
        }
        assert len(chart_data["historical_periods"]) == len(chart_data["historical_values"]) == 3
