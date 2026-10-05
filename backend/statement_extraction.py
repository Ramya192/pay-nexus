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
from concurrent.futures import ThreadPoolExecutor
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
"amount": number, "balance": number or null}, ...]} — one entry per row, in statement order. \
"amount" is signed: negative for money out (a purchase, a debit), positive for money in (a \
deposit, a refund, a salary credit). "balance" is the running/closing balance printed on that \
same row after the transaction (copy it exactly, as a plain number), or null if the statement \
has no balance column. Omit a row entirely rather than guess a date or amount you can't \
confidently read — a missing row the user can add by hand is far better than a wrong one they \
don't notice."""

# Rows whose balance change matches their amount to within this much are
# treated as reconciled (covers float rounding in the model's copy of the
# numbers).
_BALANCE_TOLERANCE = 0.05


def _number(value) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _fix_signs_from_balances(rows: list) -> None:
    """Corrects each row's in/out direction using the running balance, in
    place. The statement text has one amount column per row, so the model has
    to GUESS whether a row was a withdrawal or a deposit -- and does get it
    wrong (a 475,000 deposit read as an outflow). The balance column settles
    it deterministically: if a row's amount equals the balance change since
    the previous row, the direction is the sign of that change. Handles
    statements printed oldest-first or newest-first. Rows with no balance, or
    that don't reconcile, keep the model's sign."""
    for prev, cur in zip(rows, rows[1:]):
        if not isinstance(prev, dict) or not isinstance(cur, dict):
            continue
        prev_bal, cur_bal = _number(prev.get("balance")), _number(cur.get("balance"))
        prev_amt, cur_amt = _number(prev.get("amount")), _number(cur.get("amount"))
        if prev_bal is None or cur_bal is None:
            continue
        delta = cur_bal - prev_bal
        if cur_amt is not None and abs(abs(delta) - abs(cur_amt)) <= _BALANCE_TOLERANCE and delta != 0:
            cur["amount"] = abs(cur_amt) if delta > 0 else -abs(cur_amt)  # oldest-first
        elif prev_amt is not None and abs(abs(delta) - abs(prev_amt)) <= _BALANCE_TOLERANCE and delta != 0:
            prev["amount"] = -abs(prev_amt) if delta > 0 else abs(prev_amt)  # newest-first


# A long statement is split into chunks, each parsed by its own LLM call, so
# neither the input nor the model's output cap truncates it. Chunks are kept
# small enough that one chunk's JSON reply (~150 rows) fits comfortably in
# the output limit.
_CHUNK_CHARS = 20_000
_MAX_CHUNKS = 10
_MAX_WORKERS = 4


def _split_into_chunks(text: str) -> list[str]:
    """Splits on line boundaries (a transaction row is never cut in half),
    each chunk at most _CHUNK_CHARS unless a single line is longer."""
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for line in text.splitlines(keepends=True):
        if current and size + len(line) > _CHUNK_CHARS:
            chunks.append("".join(current))
            current, size = [], 0
        current.append(line)
        size += len(line)
    if current:
        chunks.append("".join(current))
    return chunks


def _parse_chunk(chunk: str) -> tuple[list, bool]:
    """Returns (raw rows, reply_was_cut_off)."""
    response = _client.chat.completions.create(
        model=config.STATEMENT_PARSE_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": chunk},
        ],
        response_format={"type": "json_object"},
        temperature=0,  # same statement -> same categories/rows on every upload
    )
    choice = response.choices[0]
    cut_off = choice.finish_reason == "length"
    try:
        parsed = json.loads(choice.message.content or "{}")
    except json.JSONDecodeError:
        return [], True
    rows = parsed.get("transactions") if isinstance(parsed, dict) else None
    return (rows if isinstance(rows, list) else []), cut_off


def extract_transactions_from_text(text: str, source_account: str) -> tuple[list[Transaction], int]:
    """Returns (transactions, truncated_chars). truncated_chars is 0 unless
    part of the statement couldn't be parsed — either it exceeded
    _MAX_CHUNKS chunks, or a chunk's reply was cut off by the model's output
    limit — so the caller/frontend can warn the user."""
    chunks = _split_into_chunks(text)
    truncated_chars = sum(len(c) for c in chunks[_MAX_CHUNKS:])
    chunks = chunks[:_MAX_CHUNKS]

    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        results = list(pool.map(_parse_chunk, chunks))  # preserves statement order

    rows: list = []
    for chunk, (chunk_rows, cut_off) in zip(chunks, results):
        rows.extend(chunk_rows)
        if cut_off:
            truncated_chars += len(chunk)

    _fix_signs_from_balances(rows)

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

    return transactions, truncated_chars
