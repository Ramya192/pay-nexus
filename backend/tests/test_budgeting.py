"""Unit tests for budgeting/budgets.py — pure Python, no LLM, no network."""

from budgeting.budgets import (
    bracket_for_monthly_income,
    budget_vs_actual_table,
    check_overspending,
    format_budget_summary_for_prompt,
    latest_period,
    simulate_category_adjustment,
    suggested_budgets_for_salary_bracket,
)


def _txn(date, description, amount, category, statement_period):
    return {"date": date, "description": description, "amount": amount, "category": category, "statement_period": statement_period}


class TestBracketForMonthlyIncome:
    def test_boundaries(self):
        assert bracket_for_monthly_income(20000) == "Below 30k"
        assert bracket_for_monthly_income(45000) == "30k-60k"
        assert bracket_for_monthly_income(80000) == "60k-100k"
        assert bracket_for_monthly_income(120000) == "100k-150k"
        assert bracket_for_monthly_income(200000) == "150k+"

    def test_exact_ceiling_falls_into_next_bracket(self):
        assert bracket_for_monthly_income(30000) == "30k-60k"


class TestSuggestedBudgets:
    def test_baseline_bracket_matches_defaults_exactly(self):
        suggested = suggested_budgets_for_salary_bracket("60k-100k")
        assert suggested["Rent"] == 18000

    def test_lower_bracket_scales_down(self):
        suggested = suggested_budgets_for_salary_bracket("Below 30k")
        assert suggested["Rent"] == 18000 * 0.4

    def test_unknown_bracket_defaults_to_1x_multiplier(self):
        suggested = suggested_budgets_for_salary_bracket("not a real bracket")
        assert suggested["Rent"] == 18000


class TestLatestPeriod:
    def test_none_with_no_transactions(self):
        assert latest_period([]) is None

    def test_returns_most_recent_period(self):
        transactions = [
            _txn("2026-06-01", "SWIGGY", -500, "Food & Dining", "2026-06"),
            _txn("2026-07-01", "SWIGGY", -500, "Food & Dining", "2026-07"),
        ]
        assert latest_period(transactions) == "2026-07"


class TestCheckOverspending:
    def test_category_within_budget_not_flagged(self):
        transactions = [_txn("2026-07-01", "SWIGGY", -1500, "Food & Dining", "2026-07")]
        budgets = {"Food & Dining": 2000}
        assert check_overspending(transactions, budgets, "2026-07") == []

    def test_category_over_budget_flagged_with_exact_figures(self):
        transactions = [_txn("2026-07-01", "SWIGGY", -2500, "Food & Dining", "2026-07")]
        budgets = {"Food & Dining": 2000}
        alerts = check_overspending(transactions, budgets, "2026-07")
        assert len(alerts) == 1
        assert alerts[0]["spent"] == 2500
        assert alerts[0]["over_by"] == 500
        assert alerts[0]["over_pct"] == 25.0

    def test_worst_overage_sorted_first(self):
        transactions = [
            _txn("2026-07-01", "SWIGGY", -2100, "Food & Dining", "2026-07"),  # 5% over
            _txn("2026-07-02", "AMAZON.IN", -10000, "Shopping", "2026-07"),  # 100% over
        ]
        budgets = {"Food & Dining": 2000, "Shopping": 5000}
        alerts = check_overspending(transactions, budgets, "2026-07")
        assert [a["category"] for a in alerts] == ["Shopping", "Food & Dining"]

    def test_only_checks_the_given_period_not_the_whole_history(self):
        """A credit card cycle isn't split by calendar month (statement_
        period grouping) — this test locks in that check_overspending only
        looks at the ONE period asked for, not all periods combined."""
        transactions = [
            _txn("2026-06-01", "SWIGGY", -5000, "Food & Dining", "2026-06"),
            _txn("2026-07-01", "SWIGGY", -500, "Food & Dining", "2026-07"),
        ]
        budgets = {"Food & Dining": 2000}
        assert check_overspending(transactions, budgets, "2026-07") == []
        assert len(check_overspending(transactions, budgets, "2026-06")) == 1

    def test_multi_month_period_prorates_budget_instead_of_false_flagging(self):
        """The real bug found in testing: a statement spanning 01 Jul-15
        Aug (46 days, ~1.51 months) made spend that's genuinely within a
        proportionally-scaled monthly rate look 'over budget' purely from
        covering extra days. ₹3,000 across 46 days against a ₹2,000/month
        target is well within a ~1.51-month budget (~₹3,022) — the exact
        naive (unprorated) comparison would flag this as ₹1,000 over."""
        period = "2026-07 to 2026-08"
        transactions = [
            _txn("2026-07-01", "SWIGGY ORDER", -1500, "Food & Dining", period),
            _txn("2026-08-15", "ZOMATO ORDER", -1500, "Food & Dining", period),
        ]
        budgets = {"Food & Dining": 2000}
        assert check_overspending(transactions, budgets, period) == []

    def test_multi_month_period_still_flags_a_genuine_overspend(self):
        """Proration shouldn't blind the check to real overspending — it
        should just compare against the correctly-scaled target, not a
        flat monthly figure. Three rent payments (₹54,000) across a
        ~1.51-month period against an ₹18,000/month budget (~₹27,201
        prorated) is still genuinely over, just by less than the naive
        (unprorated) ₹36,000-over figure would say."""
        period = "2026-07 to 2026-08"
        transactions = [
            _txn("2026-07-01", "RENT PAYMENT", -18000, "Rent", period),
            _txn("2026-08-01", "RENT PAYMENT", -18000, "Rent", period),
            _txn("2026-08-15", "RENT PAYMENT", -18000, "Rent", period),
        ]
        budgets = {"Rent": 18000}
        alerts = check_overspending(transactions, budgets, period)
        assert len(alerts) == 1
        assert alerts[0]["spent"] == 54000
        assert 27000 < alerts[0]["budget"] < 27500  # ~18,000 * 1.51 months, not a flat 18,000
        assert alerts[0]["over_by"] < 54000 - 18000  # less than the naive/buggy comparison would say
        assert 1.4 <= alerts[0]["period_months"] <= 1.6


class TestSimulateCategoryAdjustment:
    def test_cutting_spend_can_fix_an_overage(self):
        transactions = [_txn("2026-07-01", "SWIGGY", -2500, "Food & Dining", "2026-07")]
        budgets = {"Food & Dining": 2000}
        result = simulate_category_adjustment(transactions, budgets, "2026-07", "Food & Dining", -1000)
        assert result["actual_spent"] == 2500
        assert result["actual_over_by"] == 500
        assert result["scenario_spent"] == 1500
        assert result["scenario_over_by"] == 0.0

    def test_raising_spend_can_create_a_new_overage(self):
        transactions = [_txn("2026-07-01", "SWIGGY", -1500, "Food & Dining", "2026-07")]
        budgets = {"Food & Dining": 2000}
        result = simulate_category_adjustment(transactions, budgets, "2026-07", "Food & Dining", 1000)
        assert result["actual_over_by"] == 0.0
        assert result["scenario_spent"] == 2500
        assert result["scenario_over_by"] == 500

    def test_scenario_spend_never_goes_negative(self):
        transactions = [_txn("2026-07-01", "SWIGGY", -500, "Food & Dining", "2026-07")]
        budgets = {"Food & Dining": 2000}
        result = simulate_category_adjustment(transactions, budgets, "2026-07", "Food & Dining", -10000)
        assert result["scenario_spent"] == 0.0

    def test_category_not_in_budget_returns_none(self):
        transactions = [_txn("2026-07-01", "SWIGGY", -500, "Food & Dining", "2026-07")]
        budgets = {"Rent": 18000}
        assert simulate_category_adjustment(transactions, budgets, "2026-07", "Food & Dining", -100) is None

    def test_budget_is_prorated_for_a_multi_month_period(self):
        period = "2026-07 to 2026-08"
        transactions = [
            _txn("2026-07-01", "SWIGGY", -1500, "Food & Dining", period),
            _txn("2026-08-15", "ZOMATO", -1500, "Food & Dining", period),
        ]
        budgets = {"Food & Dining": 2000}
        result = simulate_category_adjustment(transactions, budgets, period, "Food & Dining", 0)
        assert result["budget"] > 2000  # scaled up from the flat monthly figure, not left at 2000
        assert result["actual_over_by"] == 0.0  # within the (correctly scaled) budget


class TestBudgetVsActualTable:
    def test_none_with_no_budget_or_no_period(self):
        transactions = [_txn("2026-07-01", "SWIGGY", -500, "Food & Dining", "2026-07")]
        assert budget_vs_actual_table(transactions, {}, "2026-07") is None
        assert budget_vs_actual_table(transactions, {"Food & Dining": 2000}, None) is None

    def test_table_shape_and_status(self):
        transactions = [_txn("2026-07-01", "SWIGGY", -2500, "Food & Dining", "2026-07")]
        budgets = {"Food & Dining": 2000, "Rent": 18000}
        table = budget_vs_actual_table(transactions, budgets, "2026-07")
        assert table["headers"] == ["Category", "Spent", "Budget", "Status"]
        rows_by_category = {row[0]: row for row in table["rows"]}
        assert rows_by_category["Food & Dining"][3] == "Over"
        assert rows_by_category["Rent"][3] == "OK"

    def test_title_discloses_multi_month_span(self):
        period = "2026-07 to 2026-08"
        transactions = [
            _txn("2026-07-01", "SWIGGY", -500, "Food & Dining", period),
            _txn("2026-08-15", "SWIGGY", -500, "Food & Dining", period),
        ]
        table = budget_vs_actual_table(transactions, {"Food & Dining": 2000}, period)
        assert "months" in table["title"]

    def test_title_stays_plain_for_a_single_month_period(self):
        transactions = [_txn("2026-07-01", "SWIGGY", -500, "Food & Dining", "2026-07")]
        table = budget_vs_actual_table(transactions, {"Food & Dining": 2000}, "2026-07")
        assert table["title"] == "Budget vs. actual — 2026-07"

    def test_budget_column_shows_prorated_figure(self):
        period = "2026-07 to 2026-08"
        transactions = [
            _txn("2026-07-01", "SWIGGY", -500, "Food & Dining", period),
            _txn("2026-08-15", "SWIGGY", -500, "Food & Dining", period),
        ]
        table = budget_vs_actual_table(transactions, {"Food & Dining": 2000}, period)
        row = next(r for r in table["rows"] if r[0] == "Food & Dining")
        assert row[2] != "₹2,000"  # the raw monthly figure — should be scaled up


class TestFormatBudgetSummaryForPrompt:
    def test_no_budget_set(self):
        assert format_budget_summary_for_prompt([], {}, "2026-07") == "No budget is set yet — nothing to compare spending against."

    def test_budget_set_but_no_transactions(self):
        result = format_budget_summary_for_prompt([], {"Food & Dining": 2000}, None)
        assert "no transactions on file yet" in result

    def test_mentions_multi_month_scaling_when_relevant(self):
        period = "2026-07 to 2026-08"
        transactions = [
            _txn("2026-07-01", "RENT PAYMENT", -18000, "Rent", period),
            _txn("2026-08-15", "RENT PAYMENT", -18000, "Rent", period),
        ]
        result = format_budget_summary_for_prompt(transactions, {"Rent": 18000}, period)
        assert "months" in result

    def test_stays_silent_about_scaling_for_a_single_month_period(self):
        transactions = [_txn("2026-07-01", "RENT PAYMENT", -18000, "Rent", "2026-07")]
        result = format_budget_summary_for_prompt(transactions, {"Rent": 18000}, "2026-07")
        assert "spans about" not in result
