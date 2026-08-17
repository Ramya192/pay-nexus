"""
Maps Setu's Account Aggregator FI (Financial Information) data shape into
models.Transaction — the one thing every downstream consumer
(categorization/categorize.py, SpendingAnalyser, BudgetPlanner, GoalTracker)
actually understands. AA becomes a third way to *arrive at* a Transaction
list, not a parallel data model — see the AA integration plan's scope
decisions.

The description/narration field is the one part of Setu's FI schema this
codebase hasn't verified against a real sandbox response (their own
consent-flow doc example didn't include one) — falls back to a
mode+type-derived label ("UPI CREDIT") when no narration-style field is
present, rather than leaving a transaction with an empty description
categorization/rules.py could never match a merchant keyword against.
"""

from __future__ import annotations

from datetime import date

from models import Transaction, make_transaction_id

_DESCRIPTION_FIELDS = ("narration", "remarks", "particulars", "reference")


def _description_for(txn: dict) -> str:
    for field in _DESCRIPTION_FIELDS:
        value = txn.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    mode = str(txn.get("mode") or "").strip()
    txn_type = str(txn.get("type") or "").strip()
    combined = f"{mode} {txn_type}".strip()
    return combined or "Bank transaction"


def _date_for(txn: dict) -> date | None:
    timestamp = txn.get("transactionTimestamp") or txn.get("valueDate")
    if not isinstance(timestamp, str) or len(timestamp) < 10:
        return None
    try:
        # "2020-05-08T11:05:29+00:00" -> just the date part; a Transaction
        # tracks calendar date, not time-of-day.
        return date.fromisoformat(timestamp[:10])
    except ValueError:
        return None


def map_fi_data_to_transactions(fi_data: dict, source_account: str) -> tuple[list[Transaction], list[dict]]:
    """Returns (transactions, skipped) — same "report, don't silently drop"
    shape as ingestion/normalize.py's rows_to_transactions, for the same
    reason: a row this can't confidently parse should be visible, not lost.
    """
    account = fi_data.get("account") or {}
    raw_transactions = (account.get("transactions") or {}).get("transaction") or []
    # A single transaction sometimes arrives as a bare dict instead of a
    # one-item list — a known XML-to-JSON conversion quirk in this class of
    # API, not something to assume away.
    if isinstance(raw_transactions, dict):
        raw_transactions = [raw_transactions]

    transactions: list[Transaction] = []
    skipped: list[dict] = []

    for raw in raw_transactions:
        if not isinstance(raw, dict):
            skipped.append({"raw": raw})
            continue

        txn_date = _date_for(raw)
        amount_raw = raw.get("amount")
        txn_type = str(raw.get("type") or "").upper()

        if txn_date is None or amount_raw is None or txn_type not in ("CREDIT", "DEBIT"):
            skipped.append(raw)
            continue

        try:
            amount = float(amount_raw)
        except (TypeError, ValueError):
            skipped.append(raw)
            continue

        signed_amount = amount if txn_type == "CREDIT" else -amount
        description = _description_for(raw)

        transactions.append(
            Transaction(
                transaction_id=make_transaction_id(txn_date, description, signed_amount, source_account),
                date=txn_date,
                description=description,
                amount=signed_amount,
                source_account=source_account,
            )
        )

    return transactions, skipped
