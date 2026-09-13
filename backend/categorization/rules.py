"""Keyword/merchant-based categorization — the fast, deterministic first
pass, checked before agents/spending_agent.py's LLM fallback ever runs (see
that module's docstring for the full three-tier order: rules -> LLM ->
"Uncategorized"). Ported from expense-simplifier/categorization/rules.py,
case-insensitive substring match against the transaction description.

Dict order matters: categories are checked top to bottom, and the first
match wins. "Subscriptions" is listed before "Shopping" so
"AMAZON PRIME MEMBERSHIP" matches "AMAZON PRIME" (Subscriptions) rather
than the broader "AMAZON" keyword (Shopping) catching it first.
"""

from __future__ import annotations

RULES: dict[str, list[str]] = {
    "Income": ["SALARY", "PAYROLL", "NEFT CREDIT", "IMPS CREDIT"],
    "Rent": ["RENT PAYMENT"],
    "Food & Dining": ["SWIGGY", "ZOMATO", "DOMINOS", "STARBUCKS"],
    "Groceries": ["BIGBASKET", "DMART", "RELIANCE FRESH", "BLINKIT", "ZEPTO"],
    "Transport": ["UBER", "OLA", "METRO CARD", "RAPIDO"],
    "Subscriptions": ["NETFLIX", "SPOTIFY", "AMAZON PRIME", "HOTSTAR", "YOUTUBE PREMIUM"],
    "Shopping": ["AMAZON", "FLIPKART", "MYNTRA"],
    "Utilities": ["ELECTRICITY BOARD", "WATER DEPT", "BROADBAND", "AIRTEL", "JIO"],
}


def apply_rules(description: str) -> str | None:
    upper = description.upper()
    for category, keywords in RULES.items():
        for keyword in keywords:
            if keyword in upper:
                return category
    return None
