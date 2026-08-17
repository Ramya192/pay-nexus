"""
Request/response schemas for GET/PUT /budget and GET /budget/suggested.
Same ciphertext-only contract as api/models/financial_profile.py —
`ciphertext_b64`/`iv_b64` are the AES-256-GCM blob + nonce produced
client-side (§4); this file never carries a plaintext budget figure.

Plaintext shape (once decrypted client-side), for reference — the server
never sees this shape:
    {"Rent": number, "Groceries": number, "Food & Dining": number, ...}
Keys match categorization/categories.py's CATEGORIES (minus "Income" and
"Uncategorized" — a budget targets spending categories, not those two).
"""

from pydantic import BaseModel


class BudgetSaveRequest(BaseModel):
    ciphertext_b64: str
    iv_b64: str


class BudgetOut(BaseModel):
    ciphertext_b64: str
    iv_b64: str
    updated_at: str


class SuggestedBudgetResponse(BaseModel):
    """GET /budget/suggested — plaintext, no user data involved (just a
    salary-bracket-scaled starting point, same as
    budgeting/budgets.py's suggested_budgets_for_salary_bracket), so this
    one has no ciphertext contract at all."""

    salary_bracket: str
    budgets: dict[str, float]
