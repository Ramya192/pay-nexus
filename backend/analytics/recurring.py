"""Recurring-merchant detection: surfaces merchants that appear more than
once in the loaded transactions, ranked by total spend. Adapted from
expense-simplifier/analytics/recurring.py's logic, rewritten without pandas
to match this codebase's convention (see analytics/spending_trends.py's
module docstring).

Deliberately doesn't claim to detect "subscriptions" specifically via
interval-regularity statistics — with only a couple of months of statement
data there's often just one interval per merchant, not enough to say
anything statistically meaningful about cadence. What this *can* say
honestly: these merchants recurred, here's the total, here's the average
interval. (Merchants categorization already tagged "Subscriptions" —
categorization/rules.py — are a more precise, complementary slice.)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RecurringMerchant:
    description: str
    category: str
    occurrences: int
    total_spent: float
    avg_amount: float
    avg_interval_days: float | None


def find_recurring_merchants(
    transactions: list[dict], min_occurrences: int = 2, category: str | None = None
) -> list[RecurringMerchant]:
    """`category`, when given, restricts results to merchants tagged with
    that exact category — e.g. category="Subscriptions" for "what
    subscriptions am I paying for", the precise, complementary slice this
    module's own docstring already called out as missing. Leave it None
    for the broader "what are my recurring charges" question, which
    legitimately means every repeat merchant regardless of category (a
    grocery store or ride-hailing app charged twice is still worth
    surfacing there, just not as a "subscription")."""
    by_description: dict[str, list[dict]] = {}
    for t in transactions:
        if t.get("amount", 0) >= 0:
            continue
        by_description.setdefault(t["description"], []).append(t)

    results = []
    for description, group in by_description.items():
        if len(group) < min_occurrences:
            continue
        merchant_category = group[0].get("category") or "Uncategorized"
        if category is not None and merchant_category != category:
            continue
        dates = sorted(t["date"] for t in group)  # "YYYY-MM-DD" strings sort chronologically
        intervals = [
            (_date_diff_days(dates[i + 1], dates[i])) for i in range(len(dates) - 1)
        ]
        total_spent = -sum(t["amount"] for t in group)
        results.append(
            RecurringMerchant(
                description=description,
                category=merchant_category,
                occurrences=len(group),
                total_spent=total_spent,
                avg_amount=total_spent / len(group),
                avg_interval_days=(sum(intervals) / len(intervals)) if intervals else None,
            )
        )

    return sorted(results, key=lambda r: r.total_spent, reverse=True)


def _date_diff_days(later: str, earlier: str) -> int:
    from datetime import date

    return (date.fromisoformat(later) - date.fromisoformat(earlier)).days


def recurring_merchants_table(transactions: list[dict], min_occurrences: int = 2) -> dict | None:
    merchants = find_recurring_merchants(transactions, min_occurrences)
    if not merchants:
        return None
    return {
        "title": "Recurring merchants",
        "headers": ["Merchant", "Category", "Charges", "Total spent", "Avg amount"],
        "rows": [
            [m.description, m.category, str(m.occurrences), f"₹{m.total_spent:,.0f}", f"₹{m.avg_amount:,.0f}"]
            for m in merchants
        ],
    }


def subscriptions_table(transactions: list[dict], min_occurrences: int = 2) -> dict | None:
    """The "what subscriptions am I paying for" answer — recurring
    merchants filtered to category="Subscriptions" only, unlike
    recurring_merchants_table's everything-that-repeated list (which would
    otherwise mix in a grocery store or ride-hailing app charged twice,
    neither of which anyone would call a subscription)."""
    merchants = find_recurring_merchants(transactions, min_occurrences, category="Subscriptions")
    if not merchants:
        return None
    return {
        "title": "Recurring subscriptions",
        "headers": ["Merchant", "Charges", "Total spent", "Avg amount"],
        "rows": [
            [m.description, str(m.occurrences), f"₹{m.total_spent:,.0f}", f"₹{m.avg_amount:,.0f}"]
            for m in merchants
        ],
    }
