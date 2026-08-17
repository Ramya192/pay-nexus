"""The fixed category set for bank transactions (SpendingAnalyser). Ported
from expense-simplifier/categorization/categories.py — fixed deliberately:
apply_rules (rules.py) and the LLM fallback (agents/spending_agent.py) both
need one shared, closed set of category names so a transaction categorized
by either path is comparable to one categorized by the other, and so
BudgetPlanner's per-category targets (Phase 2) always refer to a category
that categorization can actually produce.
"""

CATEGORIES = [
    "Income",
    "Rent",
    "Food & Dining",
    "Groceries",
    "Transport",
    "Subscriptions",
    "Shopping",
    "Utilities",
    "Uncategorized",
]
