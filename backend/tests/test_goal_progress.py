"""Unit tests for analytics/goal_progress.py — pure Python target-vs-saved
math, no LLM, no network.
"""

from datetime import date

from analytics.goal_progress import (
    compute_goal_progress,
    goal_progress_table,
    months_to_target_at_contribution,
)
from analytics.spending_trends import average_monthly_net_savings


def _goal(name, category, target, saved, target_date=None):
    return {"name": name, "category": category, "targetAmount": target, "savedAmount": saved, "targetDate": target_date}


class TestComputeGoalProgress:
    def test_progress_percentage_computed(self):
        result = compute_goal_progress([_goal("Goa Trip", "Trip", 100000, 25000)])
        assert result[0].progress_pct == 25.0

    def test_progress_capped_at_100_even_if_saved_exceeds_target(self):
        result = compute_goal_progress([_goal("Emergency Fund", "Emergency Fund", 50000, 80000)])
        assert result[0].progress_pct == 100.0

    def test_zero_target_amount_does_not_divide_by_zero(self):
        result = compute_goal_progress([_goal("Vague Goal", "Other", 0, 0)])
        assert result[0].progress_pct == 0.0

    def test_target_date_in_future_computes_days_remaining_and_required_pace(self):
        today = date(2026, 8, 15)
        result = compute_goal_progress(
            [_goal("Goa Trip", "Trip", 120000, 30000, target_date="2026-11-15")], today=today
        )
        r = result[0]
        assert r.days_remaining == 92  # Aug 15 -> Nov 15, 2026
        # Remaining 90,000 over ~3 months -> roughly 30,000/month
        assert 28000 < r.required_monthly_savings < 32000

    def test_target_date_already_passed_gives_no_days_remaining_or_pace(self):
        today = date(2026, 8, 15)
        result = compute_goal_progress(
            [_goal("Old Goal", "Other", 50000, 10000, target_date="2026-01-01")], today=today
        )
        r = result[0]
        assert r.days_remaining is None
        assert r.required_monthly_savings is None

    def test_no_target_date_gives_no_pace_figure(self):
        result = compute_goal_progress([_goal("Open-ended", "Other", 50000, 10000)])
        assert result[0].days_remaining is None
        assert result[0].required_monthly_savings is None

    def test_malformed_target_date_treated_as_no_date_not_an_error(self):
        result = compute_goal_progress([_goal("Bad Date", "Other", 50000, 10000, target_date="not-a-date")])
        assert result[0].days_remaining is None


class TestGoalProgressTable:
    def test_empty_goals_returns_none(self):
        assert goal_progress_table([]) is None

    def test_table_has_one_row_per_goal(self):
        table = goal_progress_table([_goal("Trip", "Trip", 100000, 25000), _goal("Home", "Home", 500000, 100000)])
        assert len(table["rows"]) == 2
        assert table["headers"] == ["Goal", "Category", "Saved", "Target", "Progress", "Target date"]


class TestMonthsToTargetAtContribution:
    def test_computes_months_from_remaining_and_rate(self):
        assert months_to_target_at_contribution(90000, 30000) == 3.0

    def test_zero_remaining_means_already_met(self):
        assert months_to_target_at_contribution(0, 5000) == 0.0

    def test_negative_remaining_treated_as_already_met(self):
        assert months_to_target_at_contribution(-100, 5000) == 0.0

    def test_zero_contribution_returns_none(self):
        assert months_to_target_at_contribution(90000, 0) is None

    def test_negative_contribution_returns_none(self):
        assert months_to_target_at_contribution(90000, -100) is None


class TestAverageMonthlyNetSavings:
    def test_none_with_no_transactions(self):
        assert average_monthly_net_savings([]) is None

    def test_averages_net_cashflow_across_periods(self):
        transactions = [
            {"date": "2026-06-01", "amount": 75000, "statement_period": "2026-06"},
            {"date": "2026-06-05", "amount": -50000, "statement_period": "2026-06"},
            {"date": "2026-07-01", "amount": 75000, "statement_period": "2026-07"},
            {"date": "2026-07-05", "amount": -60000, "statement_period": "2026-07"},
        ]
        # June net: 25,000. July net: 15,000. Average: 20,000.
        assert average_monthly_net_savings(transactions) == 20000

    def test_prorates_a_multi_month_period_before_averaging(self):
        """The real bug found in testing: a single 46-day statement
        (~1.5 months) reported its FULL net savings as the 'average
        monthly' figure — ~1.5x the real per-month rate. GoalTracker then
        compared that inflated number against a goal's required monthly
        contribution, which could make an under-saving user look
        comfortably on track."""
        period = "2026-07 to 2026-08"
        transactions = [
            {"date": "2026-07-01", "amount": 150000, "statement_period": period},
            {"date": "2026-08-15", "amount": -60000, "statement_period": period},
        ]
        # Raw net for the period: 90,000. Period spans ~1.51 months, so the
        # real per-month rate is ~90,000 / 1.51 ≈ 59,600 — meaningfully
        # less than the unprorated 90,000 the old code would have returned.
        result = average_monthly_net_savings(transactions)
        assert 55000 < result < 65000

    def test_single_calendar_month_period_is_unaffected(self):
        """A period that's genuinely ~1 month long shouldn't change at
        all — this locks in that the fix doesn't regress the common case
        the existing averaging test above already covers."""
        transactions = [
            {"date": "2026-06-01", "amount": 75000, "statement_period": "2026-06"},
            {"date": "2026-06-05", "amount": -50000, "statement_period": "2026-06"},
        ]
        assert average_monthly_net_savings(transactions) == 25000
