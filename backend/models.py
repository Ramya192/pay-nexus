"""Shared transaction schema for SpendingAnalyser. Ported from
expense-simplifier/models.py. Every ingestion path (CSV parsed directly,
PDF text structured by gpt-4o via payslip_extraction.py-style extraction,
manual entry) produces Transaction objects; categorization (rules.py +
agents/spending_agent.py's LLM fallback), analytics (spending_trends.py,
recurring.py), and — Phase 2 — budgeting all consume this same shape, so it
lives at the top level rather than inside any one package, same reasoning
as payslip_trends.py's placement.

Travels through agents/state.py as plain dicts (`transactions: List[dict]`,
same trust tier as payslip_data — decrypted client-side, plaintext for one
request only, see PROJECT_CONTEXT.md §4) — this pydantic model is the
validation/shape contract at the API boundary (api/models/statement.py),
not the in-state representation.
"""

from __future__ import annotations

import hashlib
from datetime import date

from pydantic import BaseModel


class Transaction(BaseModel):
    transaction_id: str
    date: date
    description: str
    amount: float  # signed: negative = money out (expense), positive = money in
    source_account: str

    category: str | None = None
    category_confidence: float | None = None
    # "rule" | "llm" | "user_corrected" | None (not yet categorized)
    category_source: str | None = None


def make_transaction_id(date_: date, description: str, amount: float, source_account: str) -> str:
    """Deterministic ID from the transaction's own fields, so re-parsing or
    re-uploading the same statement twice produces the same IDs instead of
    duplicates — mirrors PayslipSnapshot's month-based dedup (api/routes/
    payslip.py), just content-hashed instead of a single plaintext field
    since a statement has many rows, not one per upload."""
    raw = f"{date_.isoformat()}|{description.strip().lower()}|{amount:.2f}|{source_account}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
