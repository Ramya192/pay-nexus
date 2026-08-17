"""
Budget suggestion and overspending detection for BudgetPlanner (V2).
Adapted from expense-simplifier/budgeting/budgets.py's logic — the default
figures and salary-bracket multipliers are ported as-is (they were already
Indian-cost-of-living calibrated), but salary bracket is now derived from
tax_slabs.estimate_annual_gross_income's real annual-income estimate
(payslip_data + payslip_history) instead of a separate user_profile.py
field PayNexus has no equivalent of — one less thing for the user to enter
that this codebase can already compute.

check_overspending is period-based (analytics/spending_trends.py's
spending_by_category_and_period), not calendar-month based — same
statement-period reasoning as SpendingAnalyser, so a credit card's
16th-to-15th cycle is checked as one period, not split across two.

Every DEFAULT_MONTHLY_BUDGETS figure (and anything a user sets via
PUT /budget) is a MONTHLY target, but a statement period isn't always
exactly one month — see spending_trends.period_span_months's docstring for
why. Every comparison below prorates the budget by that period's real
month-span before comparing, rather than comparing a period's full spend
against a flat monthly number regardless of how long the period actually
is — found as a real bug in testing (a 46-day statement made a
₹18,000/month rent budget look 100% over, from two real, on-budget rent
payments).
"""

from __future__ import annotations

from analytics.spending_trends import period_span_months, spending_by_category_and_period, spending_by_period

# Starting points, editable by the user via PUT /budget — not meant to be
# authoritative, just a reasonable default so the Budget tab isn't empty on
# first load. Calibrated against the "60k-100k" monthly-gross bracket.
DEFAULT_MONTHLY_BUDGETS: dict[str, float] = {
    "Rent": 18000,
    "Groceries": 5000,
    "Food & Dining": 2000,
    "Transport": 1000,
    "Subscriptions": 1000,
    "Shopping": 5000,
    "Utilities": 2500,
}

SALARY_BRACKETS = ["Below 30k", "30k-60k", "60k-100k", "100k-150k", "150k+"]

# Scales DEFAULT_MONTHLY_BUDGETS relative to the "60k-100k" bracket it was
# calibrated against — a rough, honestly-labeled starting point (still
# editable afterward), not a claim of real financial modeling.
_SALARY_BRACKET_MULTIPLIERS: dict[str, float] = {
    "Below 30k": 0.4,
    "30k-60k": 0.7,
    "60k-100k": 1.0,
    "100k-150k": 1.5,
    "150k+": 2.2,
}
assert set(_SALARY_BRACKET_MULTIPLIERS) == set(SALARY_BRACKETS)

_BRACKET_MONTHLY_CEILINGS = [(30_000, "Below 30k"), (60_000, "30k-60k"), (100_000, "60k-100k"), (150_000, "100k-150k")]


def bracket_for_monthly_income(monthly_gross: float) -> str:
    for ceiling, bracket in _BRACKET_MONTHLY_CEILINGS:
        if monthly_gross < ceiling:
            return bracket
    return "150k+"


def suggested_budgets_for_salary_bracket(salary_bracket: str) -> dict[str, float]:
    multiplier = _SALARY_BRACKET_MULTIPLIERS.get(salary_bracket, 1.0)
    return {category: round(amount * multiplier, -2) for category, amount in DEFAULT_MONTHLY_BUDGETS.items()}


def latest_period(transactions: list[dict]) -> str | None:
    """Most recent statement period present, or None with no transactions
    at all — the period agents/budget_agent.py checks by default."""
    periods = spending_by_period(transactions)
    return periods[-1].period if periods else None


def check_overspending(transactions: list[dict], budgets: dict[str, float], period: str) -> list[dict]:
    """Categories over budget for one specific period, worst overage first.
    `period` should be one of the periods spending_by_period(transactions)
    reports — the caller (agents/budget_agent.py) defaults to the most
    recent one when not otherwise specified.

    Each category's monthly budget is prorated by that period's real
    month-span (period_span_months) before comparing — see this module's
    own docstring for why. Every alert carries the prorated `budget`
    actually used (not the raw monthly figure) so a caller can show
    self-consistent numbers, plus `period_months` so it can explain the
    scaling rather than silently changing what "budget" means.
    """
    by_period = spending_by_category_and_period(transactions)
    this_period = by_period.get(period, {})
    months = period_span_months(transactions, period)

    alerts = []
    for category, monthly_budget in budgets.items():
        budget = monthly_budget * months
        spent = this_period.get(category, 0.0)
        if spent > budget:
            alerts.append(
                {
                    "category": category,
                    "spent": spent,
                    "budget": budget,
                    "over_by": spent - budget,
                    "over_pct": (spent - budget) / budget * 100 if budget > 0 else float("inf"),
                    "period_months": months,
                }
            )
    return sorted(alerts, key=lambda a: a["over_by"], reverse=True)


def simulate_category_adjustment(
    transactions: list[dict], budgets: dict[str, float], period: str, category: str, delta: float
) -> dict | None:
    """What-If Simulator (V2): "if I cut Food & Dining by ₹1,000, would I
    still be over budget" — re-runs the same spend-vs-budget check
    check_overspending already does, just with one category's actual spend
    adjusted by `delta` (negative = cutting spend, positive = raising it).
    Wraps check_overspending/spending_by_category_and_period rather than
    reimplementing the comparison, so a scenario answer can never disagree
    with what the real BudgetPlanner would say about the same numbers.
    None if the category isn't in the budget at all — nothing to compare.
    """
    if category not in budgets:
        return None
    by_period = spending_by_category_and_period(transactions)
    actual_spent = by_period.get(period, {}).get(category, 0.0)
    scenario_spent = max(0.0, actual_spent + delta)
    budget = budgets[category] * period_span_months(transactions, period)
    return {
        "category": category,
        "period": period,
        "actual_spent": actual_spent,
        "scenario_spent": scenario_spent,
        "budget": budget,
        "actual_over_by": max(0.0, actual_spent - budget),
        "scenario_over_by": max(0.0, scenario_spent - budget),
    }


def format_budget_summary_for_prompt(transactions: list[dict], budgets: dict[str, float], period: str | None) -> str:
    if not budgets:
        return "No budget is set yet — nothing to compare spending against."
    if period is None:
        return "A budget is set, but there are no transactions on file yet to check it against."

    by_period = spending_by_category_and_period(transactions)
    this_period = by_period.get(period, {})
    months = period_span_months(transactions, period)
    alerts = check_overspending(transactions, budgets, period)

    lines = [f"Budget check for period {period} (already computed — quote directly, do not recompute):"]
    if months > 1.01:
        lines.append(
            f"This period spans about {months:.1f} months, so each category's monthly budget below has "
            f"already been scaled up by that factor before comparing — mention this if it's relevant to "
            f"why a figure looks larger than the user's usual monthly target."
        )
    for category, monthly_budget in budgets.items():
        budget = monthly_budget * months
        spent = this_period.get(category, 0.0)
        status = "OVER" if spent > budget else "within budget"
        lines.append(f"  {category}: ₹{spent:,.0f} spent of ₹{budget:,.0f} budgeted ({status})")

    if alerts:
        lines.append(f"{len(alerts)} categor{'y is' if len(alerts) == 1 else 'ies are'} over budget this period, worst first:")
        for a in alerts:
            lines.append(
                f"  {a['category']}: {a['over_pct']:.0f}% over — ₹{a['spent']:,.0f} spent vs ₹{a['budget']:,.0f} "
                f"budgeted (₹{a['over_by']:,.0f} over)"
            )
    else:
        lines.append("No category exceeded its budget this period.")
    return "\n".join(lines)


def budget_vs_actual_table(transactions: list[dict], budgets: dict[str, float], period: str | None) -> dict | None:
    if not budgets or period is None:
        return None
    by_period = spending_by_category_and_period(transactions)
    this_period = by_period.get(period, {})
    months = period_span_months(transactions, period)
    # Title discloses the scaling whenever it's actually in effect — the
    # "Budget" column below is the prorated figure, not the user's raw
    # monthly number, so this is the one place that difference gets
    # explained rather than just silently showing up.
    title = f"Budget vs. actual — {period}" + (f" (≈{months:.1f} months)" if months > 1.01 else "")
    return {
        "title": title,
        "headers": ["Category", "Spent", "Budget", "Status"],
        "rows": [
            [
                category,
                f"₹{this_period.get(category, 0.0):,.0f}",
                f"₹{monthly_budget * months:,.0f}",
                "Over" if this_period.get(category, 0.0) > monthly_budget * months else "OK",
            ]
            for category, monthly_budget in budgets.items()
        ],
    }
