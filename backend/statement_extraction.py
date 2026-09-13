"""
Turns raw text extracted from a bank/credit-card statement PDF into a list
of transaction rows — backs POST /statement/parse's PDF path. Mirrors
payslip_extraction.py's role and privacy contract exactly: the PDF itself
never reaches the server, only text extracted client-side (pdfjs-dist)
does. Not a fifth agent in the §2 sense (no LangGraph node, no place in
PayNexusState) — a one-shot utility call, same pattern as
compression/context_compressor.py.

CSV statements skip this module entirely (ingestion/csv_parser.py parses
them directly — already row-structured, no LLM needed). This file only
handles the PDF path, where a table has been flattened to plain text by
pdfjs-dist and needs an LLM to recover row structure — the reason
SpendingAnalyser needs an LLM step at all where expense-simplifier's
original ingestion/pdf_parser.py didn't: that version received the actual
PDF file server-side and let pdfplumber recover the table structurally.
"""

import json
from datetime import date

from openai import OpenAI

from config import config
from models import Transaction, make_transaction_id

_client = OpenAI(api_key=config.OPENAI_API_KEY)

_SYSTEM_PROMPT = """Extract every transaction row from raw text pulled from a bank or \
credit-card statement PDF. Indian statements vary widely in layout across banks — match on \
meaning, not exact label text (e.g. "Narration"/"Particulars"/"Description" all mean the \
transaction description; "Withdrawal Amt"/"Debit" is money out, "Deposit Amt"/"Credit" is \
money in).

Respond with a JSON object: {"transactions": [{"date": "YYYY-MM-DD", "description": string, \
"amount": number}, ...]} — one entry per row, in statement order. "amount" is signed: negative \
for money out (a purchase, a debit), positive for money in (a deposit, a refund, a salary \
credit). Omit a row entirely rather than guess a date or amount you can't confidently read — a \
missing row the user can add by hand is far better than a wrong one they don't notice."""


def extract_transactions_from_text(text: str, source_account: str) -> tuple[list[Transaction], int]:
    """Returns (transactions, truncated_chars). truncated_chars is 0 unless
    the input exceeded the cap below, so the caller/frontend can warn the
    user a long statement was only partially parsed. Capped more generously
    than payslip_extraction.py's 8000: a payslip is a page or two, a
    statement can run many pages of transaction rows."""
    capped = text[:60_000]
    response = _client.chat.completions.create(
        model=config.STATEMENT_PARSE_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": capped},
        ],
        response_format={"type": "json_object"},
    )
    parsed = json.loads(response.choices[0].message.content or "{}")
    rows = parsed.get("transactions") if isinstance(parsed, dict) else None
    if not isinstance(rows, list):
        rows = []

    transactions: list[Transaction] = []
    # See ingestion/normalize.py's identical pattern — disambiguates
    # genuinely-duplicate rows within the same statement so they don't
    # collide onto one transaction_id.
    seen_counts: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            txn_date = date.fromisoformat(str(row["date"]))
            description = str(row["description"]).strip()
            amount = float(row["amount"])
        except (KeyError, ValueError, TypeError):
            continue
        if not description:
            continue
        dedup_key = f"{txn_date.isoformat()}|{description.strip().lower()}|{amount:.2f}|{source_account}"
        occurrence = seen_counts.get(dedup_key, 0)
        seen_counts[dedup_key] = occurrence + 1
        transactions.append(
            Transaction(
                transaction_id=make_transaction_id(txn_date, description, amount, source_account, occurrence),
                date=txn_date,
                description=description,
                amount=amount,
                source_account=source_account,
            )
        )

    return transactions, max(0, len(text) - len(capped))
