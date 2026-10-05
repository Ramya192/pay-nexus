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
    "Transport": ["UBER", "w:OLA", "METRO CARD", "RAPIDO"],
    "Subscriptions": ["NETFLIX", "SPOTIFY", "AMAZON PRIME", "HOTSTAR", "YOUTUBE PREMIUM"],
    "Shopping": ["AMAZON", "FLIPKART", "MYNTRA"],
    # Mutual fund / SIP debits — saving, not spending.
    "Investments": ["RD THROUGH MOBILE", "RD CLOSURE", "MUTUAL FUND", "INDIAN CLEARING CORP", "BSE STAR", "NSE CLEARING", "ZERODHA", "GROWW", "KUVERA", " SIP "],
    "Credit Card Payment": ["CREDIT CARD", "CRED CLUB", "w:CRED", "w:CC PAYMENT"],
    "Loans & EMI": ["w:EMI", "LOAN"],
    # Last on purpose: person-to-person / own-account movement. Anything more
    # specific above (e.g. "IMPS-...-ZERODHA" -> Investments) wins first.
    "Transfers": ["IMPS-", "NEFT DR", "NEFT-", "RTGS", "w:TPT"],
    # After Transfers on purpose: a bank-to-bank movement that merely NAMES a
    # telecom/utility (e.g. "IMPS-...-AIRTEL PAYMENTS BANK") is a transfer, not a
    # bill, and one large such row would otherwise swamp the Utilities total.
    # AIRTEL/JIO are whole-word so they don't match inside longer words.
    "Utilities": ["ELECTRICITY BOARD", "WATER DEPT", "BROADBAND", "w:AIRTEL", "w:JIO"],
}


def apply_rules(description: str) -> str | None:
    upper = description.upper()
    # Whole-word view of the description, for keywords written "w:WORD" --
    # a plain substring "EMI" would also hit "PREMIUM", "CRED" would hit
    # "CREDIT", etc.
    words = " " + " ".join("".join(c if c.isalnum() else " " for c in upper).split()) + " "
    for category, keywords in RULES.items():
        for keyword in keywords:
            if keyword.startswith("w:"):
                if f" {keyword[2:]} " in words:
                    return category
            elif keyword in upper:
                return category
    return None
