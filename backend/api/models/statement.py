"""
Request/response schemas for bank statement parsing and persistence. Two
contracts, matching payslip.py's split:
  - /parse: plaintext in, plaintext out, nothing persisted (statement text
    already extracted client-side — PDF via pdfjs-dist, CSV read as text —
    same "the file never reaches the server" rule as payslip.py's /parse).
  - /save, /list: ciphertext_b64/iv_b64 in and out, same contract as
    payslip snapshots — the parsed-and-categorized transaction list is what
    gets encrypted client-side before /save.
"""

from typing import Literal

from pydantic import BaseModel


class StatementParseRequest(BaseModel):
    text: str
    source_account: str
    format: Literal["pdf", "csv"]


class TransactionOut(BaseModel):
    transaction_id: str
    date: str
    description: str
    amount: float
    source_account: str
    category: str | None = None
    category_source: str | None = None


class StatementParseResponse(BaseModel):
    transactions: list[TransactionOut]
    skipped_row_count: int  # CSV rows normalize.py couldn't read (missing date/description/amount)
    truncated_chars: int  # >0 only on the PDF path, if input exceeded statement_extraction.py's cap


class StatementSaveRequest(BaseModel):
    source_account: str
    period_label: str  # e.g. "2026-07"
    ciphertext_b64: str
    iv_b64: str
    # SHA-256 fingerprint of the transaction list's own content (date +
    # description + amount — see frontend/src/utils/contentHash.ts),
    # computed client-side. Lets POST /save catch the same statement
    # re-saved under a DIFFERENT account name, which source_account +
    # period_label alone can't — see db/models.py's BankStatement docstring.
    content_hash: str


class StatementUpdateRequest(BaseModel):
    """PUT /statement/{id} — overwrites a saved statement's ciphertext in
    place. Used by the per-row category-correction UI: the client decrypts
    the full transaction list, edits one row's category, then re-encrypts
    and sends the whole list back. source_account/period_label aren't here
    — a correction doesn't change the statement's identity, just its
    contents, so the existing dedup key stays untouched."""

    ciphertext_b64: str
    iv_b64: str


class StatementOut(BaseModel):
    id: str
    source_account: str
    period_label: str
    created_at: str


class StatementFull(BaseModel):
    """GET /statement/list — unlike StatementOut (returned from /save, just
    a receipt), this carries the ciphertext back so the client can decrypt
    every saved statement and hand the full transaction history to the
    SpendingAnalyser agent (see agents/spending_agent.py)."""

    id: str
    source_account: str
    period_label: str
    ciphertext_b64: str
    iv_b64: str
    created_at: str
