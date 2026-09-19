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

Three more dict-only fields analytics/spending_trends.py reads that this
model deliberately doesn't declare, for the same reason `statement_period`
isn't declared here either (see that module's own docstring): all are
stamped client-side only, on synthetic/derived transactions this file's own
ingestion paths (CSV/PDF parsing, categorize.py) never produce —
`statement_period`, `counts_toward_category_spend`, and
`counts_toward_net_savings` (the latter two default True when absent, used
by the credit-card billing-cycle feature — see
frontend/src/components/StatementUploader/CreditCardStatementUploader.tsx).
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


def make_transaction_id(
    date_: date, description: str, amount: float, source_account: str, occurrence: int = 0
) -> str:
    """Deterministic ID from the transaction's own fields, so re-parsing or
    re-uploading the same statement twice produces the same IDs instead of
    duplicates — mirrors PayslipSnapshot's month-based dedup (api/routes/
    payslip.py), just content-hashed instead of a single plaintext field
    since a statement has many rows, not one per upload.

    `occurrence` disambiguates two genuinely-identical rows (same date,
    description, amount, and account — e.g. two separate ₹500 Netflix
    charges on the same day) landing in the same parse batch. Callers pass
    the 0-based count of prior rows with the same other four fields seen so
    far while walking the statement in order, so re-uploading the identical
    file still reproduces the identical set of IDs (parse order is stable),
    while two distinct-but-identical-looking rows no longer collide onto one
    ID. Left at its default of 0 for any caller that only has one row to
    hash (e.g. a direct unit-test call) — behaves exactly as before then."""
    raw = f"{date_.isoformat()}|{description.strip().lower()}|{amount:.2f}|{source_account}|{occurrence}"
    # usedforsecurity=False: this is a dedup fingerprint, not a security
    # boundary -- SHA1 is fine here (collision resistance isn't the property
    # being relied on, just a stable short ID), but flagging it plainly
    # rather than leaving a bare hashlib.sha1() call for a scanner (bandit,
    # added 2026-09-14) to keep re-flagging as if it were unreviewed.
    return hashlib.sha1(raw.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]
