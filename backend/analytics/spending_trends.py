"""
Spending analytics for SpendingAnalyser (and, Phase 2, BudgetPlanner):
category breakdown and period-over-period trend, computed here in Python
from `transactions` (plain dicts — same trust tier as payslip_data, see
agents/state.py) and handed to agents/spending_agent.py as already-correct
figures, same pattern as payslip_trends.py (compute_trends/trends_table) and
tax_calculations.py.

Adapted from expense-simplifier/analytics/trends.py's logic, but rewritten
without pandas (not a dependency of this codebase — see requirements.txt)
to match the hand-rolled-Python-plus-dataclasses convention every other
*_trends.py-style module here already uses.

`transactions` items are plain dicts shaped like models.Transaction
(date: "YYYY-MM-DD" string, description, amount, category), plus one field
this module reads that models.Transaction itself doesn't declare:
`statement_period` — the label the user gave that whole statement at save
time (frontend/src/components/StatementUploader/StatementUploader.tsx's
"Period label" field, e.g. "2026-07" for a calendar-aligned bank statement
or "16 Jul 2026 to 15 Aug 2026" for a credit card billing cycle), attached
to every transaction from that statement when store/transactionStore.ts
flattens saved statements for /chat.

Grouping by this instead of slicing the transaction date's calendar month
matters for real statements: a credit card cycle from the 16th to the 15th
would otherwise get split across two calendar-month buckets even though
it's one billing period the user is trying to track as a single unit. Falls
back to the transaction's own calendar month only when no statement_period
was given (e.g. hand-entered transactions, or older saved data from before
this field existed) — see _period_of below.

Expenses only (amount < 0) unless noted — income isn't a spending category.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as _date

_AVG_DAYS_PER_MONTH = 30.44  # average Gregorian month length


@dataclass
class CategoryTotal:
    category: str
    total_spent: float


@dataclass
class PeriodTotal:
    period: str  # a statement's own period_label, or "YYYY-MM" as a calendar-month fallback — see module docstring
    total_spent: float


@dataclass
class CategoryPeriodTrend:
    category: str
    first_period: str
    first_value: float
    last_period: str
    last_value: float
    delta: float
    direction: str  # "up" | "down" | "flat"


def _period_of(transaction: dict) -> str:
    """The statement period this transaction was saved under, falling back
    to its own calendar month (see module docstring) when no
    statement_period is present."""
    return transaction.get("statement_period") or transaction["date"][:7]


def _expenses(transactions: list[dict]) -> list[dict]:
    return [t for t in transactions if t.get("amount", 0) < 0]


def spending_by_category(transactions: list[dict]) -> list[CategoryTotal]:
    """Total spend (positive numbers) per category, sorted highest first."""
    totals: dict[str, float] = {}
    for t in _expenses(transactions):
        category = t.get("category") or "Uncategorized"
        totals[category] = totals.get(category, 0.0) + (-t["amount"])
    return sorted(
        (CategoryTotal(category, total) for category, total in totals.items()),
        key=lambda c: c.total_spent,
        reverse=True,
    )


def spending_by_period(transactions: list[dict]) -> list[PeriodTotal]:
    """Total spend per statement period present in the data, oldest first
    (string-sorted — statement_period labels a user typed freely won't
    always sort chronologically, but the calendar-month fallback shape
    "YYYY-MM" does, which covers the common case)."""
    totals: dict[str, float] = {}
    for t in _expenses(transactions):
        period = _period_of(t)
        totals[period] = totals.get(period, 0.0) + (-t["amount"])
    return sorted((PeriodTotal(period, total) for period, total in totals.items()), key=lambda p: p.period)


def net_savings_by_period(transactions: list[dict]) -> list[PeriodTotal]:
    """Net cashflow (income minus expenses — every transaction's signed
    amount, not _expenses()-filtered) per period, oldest first. Unlike
    spending_by_period, this includes income rows on purpose: "how much did
    I actually save" needs both sides, not spend alone. Used by
    agents/goal_agent.py to project whether a goal's current savings rate
    is enough to hit its target by its target date."""
    totals: dict[str, float] = {}
    for t in transactions:
        period = _period_of(t)
        totals[period] = totals.get(period, 0.0) + t.get("amount", 0)
    return sorted((PeriodTotal(period, total) for period, total in totals.items()), key=lambda p: p.period)


def average_monthly_net_savings(transactions: list[dict]) -> float | None:
    """Mean net savings per REAL MONTH across every period on file — a
    single number to project "at this rate, how long until a goal is
    reached." None with fewer than one period of data (nothing to
    average), not 0 — 0 would misleadingly say "you save nothing" when the
    honest answer is "not enough data yet."

    Each period's own net savings is divided by period_span_months(...)
    before averaging — a period isn't always exactly one real month (see
    that function's docstring), so treating every period's total as if it
    were "one month's savings" overstates the rate for any period longer
    than ~30 days. Found as a real bug in testing: a single 46-day
    statement (~1.5 months) made GoalTracker report the FULL period's net
    savings as the "average monthly" figure — about 1.5x the real
    per-month rate, which happened not to flip the specific pace
    conclusion shown (the real rate was still comfortably enough), but
    would in a closer case.
    """
    periods = net_savings_by_period(transactions)
    if not periods:
        return None
    monthly_equivalents = [p.total_spent / period_span_months(transactions, p.period) for p in periods]
    return sum(monthly_equivalents) / len(monthly_equivalents)


def period_span_months(transactions: list[dict], period: str) -> float:
    """How many real months long one statement period actually is — e.g.
    1.0 for a clean calendar-month statement or a ~30-day credit-card
    cycle, ~1.5 for a period spanning 46 days. Computed from the min-to-max
    transaction date among every transaction saved under that period
    (inclusive), divided by an average month length — not from the period
    LABEL, which is free text a user can type however they like and isn't
    reliably parseable as a date range.

    Exists specifically so budgeting/budgets.py can prorate a fixed MONTHLY
    budget cap before comparing it against a period's actual spend. Without
    this, a statement covering more than one real month (as opposed to a
    ~30-day billing cycle that merely crosses a calendar-month boundary,
    which this correctly leaves at ~1.0) always looks 'over budget' purely
    because more days' worth of spending landed in it than a strict
    30-day month would hold — found in testing: a statement spanning
    01 Jul-15 Aug (46 days, two real rent payments) flagged Rent as 100%
    over a ₹18,000/month budget, even though ₹18,000/month is exactly the
    real rate.

    Floored at 1.0 — a short period (a handful of days) never SHRINKS the
    effective budget below one full month's worth; it only ever scales up
    for periods genuinely longer than ~1 month. Falls back to 1.0 (no
    adjustment) if no transaction in this period has a parseable date, so a
    caller comparing against a monthly figure never divides by zero or
    raises.
    """
    date_strs = [t["date"] for t in transactions if _period_of(t) == period and t.get("date")]
    if not date_strs:
        return 1.0
    try:
        parsed = [_date.fromisoformat(d) for d in date_strs]
    except ValueError:
        return 1.0
    span_days = (max(parsed) - min(parsed)).days + 1
    return max(span_days / _AVG_DAYS_PER_MONTH, 1.0)


def spending_by_category_and_period(transactions: list[dict]) -> dict[str, dict[str, float]]:
    """period -> category -> total_spent. What Phase 2's budgeting/budgets.py
    compares against per-category budget caps."""
    result: dict[str, dict[str, float]] = {}
    for t in _expenses(transactions):
        period = _period_of(t)
        category = t.get("category") or "Uncategorized"
        by_category = result.setdefault(period, {})
        by_category[category] = by_category.get(category, 0.0) + (-t["amount"])
    return result


def category_period_trends(transactions: list[dict]) -> list[CategoryPeriodTrend]:
    """First-vs-last period spend, per category, for categories with data in
    at least two distinct periods — same "first-vs-last is a meaningful
    trend, not a full regression" scope limit as payslip_trends.py's
    compute_trends. This is what lets a question like "is my food spending
    going up" be answered from an exact number instead of the model
    guessing from spending_by_category's all-time total (which has no
    period dimension at all) or spending_by_period's totals (which are
    summed across every category, not this one). Sorted by largest absolute
    change first."""
    by_period = spending_by_category_and_period(transactions)
    per_category: dict[str, list[tuple[str, float]]] = {}
    for period in sorted(by_period):
        for category, total in by_period[period].items():
            per_category.setdefault(category, []).append((period, total))

    trends = []
    for category, points in per_category.items():
        if len(points) < 2:
            continue
        first_period, first_value = points[0]
        last_period, last_value = points[-1]
        delta = last_value - first_value
        direction = "up" if delta > 0 else "down" if delta < 0 else "flat"
        trends.append(
            CategoryPeriodTrend(category, first_period, first_value, last_period, last_value, delta, direction)
        )
    return sorted(trends, key=lambda t: abs(t.delta), reverse=True)


def format_spending_summary_for_prompt(transactions: list[dict]) -> str:
    by_category = spending_by_category(transactions)
    if not by_category:
        return "No expense transactions on file yet — nothing to summarize."

    total = sum(c.total_spent for c in by_category)
    lines = [
        (
            f"{len(transactions)} transaction(s) on file. Total spend across all categories: "
            f"₹{total:,.0f} (already computed — quote directly, do not recompute)."
        ),
        "By category, highest first:",
    ]
    lines.extend(f"  {c.category}: ₹{c.total_spent:,.0f}" for c in by_category)

    trend = spending_by_period(transactions)
    if len(trend) >= 2:
        first, last = trend[0], trend[-1]
        arrow = "↑" if last.total_spent > first.total_spent else "↓" if last.total_spent < first.total_spent else "→"
        lines.append(
            f"Period-over-period (all categories combined): {first.period} ₹{first.total_spent:,.0f} {arrow} "
            f"{last.period} ₹{last.total_spent:,.0f}"
        )

    category_trends = category_period_trends(transactions)
    if category_trends:
        lines.append("By category, first vs. last period on file (already computed — quote directly):")
        for t in category_trends:
            arrow = "↑" if t.direction == "up" else "↓" if t.direction == "down" else "→"
            lines.append(
                f"  {t.category}: ₹{t.first_value:,.0f} ({t.first_period}) {arrow} ₹{t.last_value:,.0f} "
                f"({t.last_period})"
            )
    return "\n".join(lines)


# --- Table builders, for the frontend's <DataTable> rendering — same
# rationale as payslip_trends.py's: built here in Python from the same data
# the format_*_for_prompt function above already renders as prose, never
# from the LLM, so a table and its narration can't disagree.


def spending_by_category_table(transactions: list[dict]) -> dict | None:
    by_category = spending_by_category(transactions)
    if not by_category:
        return None
    return {
        "title": "Spending by category",
        "headers": ["Category", "Total spent"],
        "rows": [[c.category, f"₹{c.total_spent:,.0f}"] for c in by_category],
    }


def period_trend_table(transactions: list[dict]) -> dict | None:
    trend = spending_by_period(transactions)
    if not trend:
        return None
    return {
        "title": "Spending trend by period",
        "headers": ["Period", "Total spent"],
        "rows": [[p.period, f"₹{p.total_spent:,.0f}"] for p in trend],
    }


def category_period_trend_table(transactions: list[dict]) -> dict | None:
    trends = category_period_trends(transactions)
    if not trends:
        return None
    return {
        "title": "Spending trend by category",
        "headers": ["Category", "First period", "Last period", "Change"],
        "rows": [
            [
                t.category,
                f"₹{t.first_value:,.0f} ({t.first_period})",
                f"₹{t.last_value:,.0f} ({t.last_period})",
                f"{'↑' if t.direction == 'up' else '↓' if t.direction == 'down' else '→'} ₹{abs(t.delta):,.0f}",
            ]
            for t in trends
        ],
    }
