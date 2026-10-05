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

import re
from collections import Counter
from dataclasses import dataclass

_RAIL_PREFIXES = ("UPI", "POS", "ECOM", "ACH", "NACH", "ECS", "SI")
_NOISE_TOKENS = {"COM", "LLP", "LTD", "LIMITED", "PVT", "PRIVATE", "INC", "INDIA", "CO"}


def normalize_merchant(description: str) -> str:
    """A stable grouping key for one merchant across the different shapes the same charge
    takes on a statement ("UPI-NETFLIX COM-NETFLIXUPI.PAYU@HDFCBANK-...", "UPI-NETFLIX COM"):
    drop the payment-rail prefix, take the merchant segment (the first one that has letters
    and isn't a UPI handle), then drop corporate-suffix noise and bare numbers. Falls back to
    the cleaned-up description itself, so unrecognised shapes just keep their own group."""
    segments = [seg.strip() for seg in re.split(r"[-/]", description.upper()) if seg.strip()]
    if segments and segments[0] in _RAIL_PREFIXES:
        segments = segments[1:]
    merchant = next((seg for seg in segments if re.search(r"[A-Z]", seg) and "@" not in seg), None)
    if merchant is None:
        return description.strip().upper()
    tokens = [t for t in merchant.split() if t not in _NOISE_TOKENS and not t.isdigit()]
    return " ".join(tokens) or merchant


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
        by_description.setdefault(normalize_merchant(t["description"]), []).append(t)

    results = []
    for description, group in by_description.items():
        if len(group) < min_occurrences:
            continue
        merchant_category = Counter(t.get("category") or "Uncategorized" for t in group).most_common(1)[0][0]
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
