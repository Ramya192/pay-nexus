"""Shared row -> Transaction normalization for CSV statement ingestion.
Adapted from expense-simplifier/ingestion/normalize.py's column-aliasing
logic, rewritten without pandas (a small tried-in-order list of date
formats instead of pandas.to_datetime) to match this codebase's convention
— see analytics/spending_trends.py's module docstring for the same call.

Bank/credit-card CSV exports vary in header names and in whether they use a
single signed "Amount" column or separate "Debit"/"Credit" columns — this
module absorbs that variation so ingestion/csv_parser.py only ever deals in
Transaction.
"""

from __future__ import annotations

import re
from datetime import date, datetime

from models import Transaction, make_transaction_id

_DATE_ALIASES = ["date", "transaction date", "txn date", "value date", "posting date"]
_DESCRIPTION_ALIASES = ["description", "narration", "particulars", "details", "transaction details", "merchant"]
_AMOUNT_ALIASES = ["amount", "transaction amount"]
_DEBIT_ALIASES = ["debit", "withdrawal", "debit amount", "dr"]
_CREDIT_ALIASES = ["credit", "deposit", "credit amount", "cr"]

_AMOUNT_CLEAN_RE = re.compile(r"[^0-9.\-]")
# Indian bank exports are usually DD/MM/YYYY or DD-MM-YYYY, not ISO — tried
# in this order; ISO first since an already-clean/re-exported CSV is common
# too and shouldn't be misread as day-first.
_DATE_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d %b %Y", "%m/%d/%Y"]


def _find_column(columns: list[str], aliases: list[str]) -> str | None:
    lower_map = {str(c).strip().lower(): c for c in columns}
    for alias in aliases:
        if alias in lower_map:
            return lower_map[alias]
    return None


def _parse_amount(raw) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    cleaned = _AMOUNT_CLEAN_RE.sub("", str(raw))
    if not cleaned or cleaned in ("-", "."):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_date(raw) -> date | None:
    if raw is None:
        return None
    text = str(raw).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def rows_to_transactions(rows: list[dict], source_account: str) -> tuple[list[Transaction], list[dict]]:
    """Converts raw CSV row dicts (csv.DictReader output) into Transactions.
    Returns (transactions, skipped) — skipped rows are reported rather than
    silently dropped, since a statement parser that fails silently on a
    malformed row is worse than one that fails loudly.
    """
    if not rows:
        return [], []

    columns = list(rows[0].keys())
    date_col = _find_column(columns, _DATE_ALIASES)
    desc_col = _find_column(columns, _DESCRIPTION_ALIASES)
    amount_col = _find_column(columns, _AMOUNT_ALIASES)
    debit_col = _find_column(columns, _DEBIT_ALIASES)
    credit_col = _find_column(columns, _CREDIT_ALIASES)

    if date_col is None or desc_col is None or (amount_col is None and debit_col is None and credit_col is None):
        raise ValueError(f"Could not identify date/description/amount columns from headers: {columns}")

    transactions: list[Transaction] = []
    skipped: list[dict] = []

    for row in rows:
        txn_date = _parse_date(row.get(date_col))
        description = str(row.get(desc_col, "")).strip()

        if amount_col is not None:
            amount = _parse_amount(row.get(amount_col))
        else:
            debit = _parse_amount(row.get(debit_col)) or 0.0
            credit = _parse_amount(row.get(credit_col)) or 0.0
            amount = credit - debit

        if txn_date is None or not description or amount is None:
            skipped.append(row)
            continue

        transactions.append(
            Transaction(
                transaction_id=make_transaction_id(txn_date, description, amount, source_account),
                date=txn_date,
                description=description,
                amount=amount,
                source_account=source_account,
            )
        )

    return transactions, skipped
