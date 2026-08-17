"""
POST /statement/parse, POST /statement/save, DELETE /statement/{id},
GET /statement/list — SpendingAnalyser, V2. Same split as payslip.py:
/parse is plaintext in, plaintext out, nothing persisted; /save and /list
are ciphertext in, ciphertext out.

POST /save rejects a second save for a (user, source_account, period_label)
triple already on file with 409, same reasoning as payslip.py's month
dedup — the two plaintext fields the server sees are enough to catch a
duplicate upload without ever looking at a transaction description or
amount.
"""

import base64

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.models.statement import (
    StatementFull,
    StatementOut,
    StatementParseRequest,
    StatementParseResponse,
    StatementSaveRequest,
    StatementUpdateRequest,
    TransactionOut,
)
from categorization.categorize import categorize_transactions
from db.database import get_db
from db.models import BankStatement, User
from ingestion.csv_parser import parse_csv_text
from security.auth import get_current_user
from statement_extraction import extract_transactions_from_text

router = APIRouter(prefix="/statement", tags=["statement"])


@router.post("/parse", response_model=StatementParseResponse)
def parse_statement(
    body: StatementParseRequest,
    _user: User = Depends(get_current_user),
) -> StatementParseResponse:
    """Turns already-extracted statement text into categorized transaction
    rows — pre-fills a review list, never auto-saves, same "upload and
    manual entry both land in one editable form" shape as
    POST /payslip/parse."""
    if not body.text.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No text to parse.")

    skipped_row_count = 0
    truncated_chars = 0
    if body.format == "csv":
        try:
            transactions, skipped = parse_csv_text(body.text, body.source_account)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
        skipped_row_count = len(skipped)
    else:
        transactions, truncated_chars = extract_transactions_from_text(body.text, body.source_account)

    transactions = categorize_transactions(transactions)
    return StatementParseResponse(
        transactions=[
            TransactionOut(
                transaction_id=t.transaction_id,
                date=t.date.isoformat(),
                description=t.description,
                amount=t.amount,
                source_account=t.source_account,
                category=t.category,
                category_source=t.category_source,
            )
            for t in transactions
        ],
        skipped_row_count=skipped_row_count,
        truncated_chars=truncated_chars,
    )


@router.post("/save", response_model=StatementOut, status_code=201)
def save_statement(
    body: StatementSaveRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StatementOut:
    existing = db.scalar(
        select(BankStatement).where(
            BankStatement.user_id == user.id,
            BankStatement.source_account == body.source_account,
            BankStatement.period_label == body.period_label,
        )
    )
    if existing:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"A statement for {body.source_account}, {body.period_label} is already saved. "
            "Delete it first if you want to replace it.",
        )

    # Second, independent duplicate check: the same transactions saved under
    # a DIFFERENT account name — the check above can't catch this since it
    # only compares source_account/period_label, and this app never sees a
    # statement's actual contents to compare directly. content_hash is a
    # one-way fingerprint of the transaction list itself, computed
    # client-side (frontend/src/utils/contentHash.ts) — a real gap found in
    # testing (re-uploading the same PDF under "HDFC Checking1" sailed
    # through as a "new" statement). content_hash is nullable for
    # statements saved before this column existed, so an old row with no
    # hash never falsely collides here.
    content_duplicate = db.scalar(
        select(BankStatement).where(
            BankStatement.user_id == user.id,
            BankStatement.content_hash == body.content_hash,
        )
    )
    if content_duplicate:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"These transactions are already saved, as \"{content_duplicate.source_account}\", "
            f"{content_duplicate.period_label}. If this is really a different account, rename it "
            "so it's distinguishable — otherwise delete the existing one first.",
        )

    statement = BankStatement(
        user_id=user.id,
        source_account=body.source_account,
        period_label=body.period_label,
        ciphertext=base64.b64decode(body.ciphertext_b64),
        iv=base64.b64decode(body.iv_b64),
        content_hash=body.content_hash,
    )
    db.add(statement)
    db.commit()
    db.refresh(statement)
    return StatementOut(
        id=statement.id,
        source_account=statement.source_account,
        period_label=statement.period_label,
        created_at=statement.created_at.isoformat(),
    )


@router.put("/{statement_id}", response_model=StatementOut)
def update_statement(
    statement_id: str,
    body: StatementUpdateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StatementOut:
    """Overwrites a saved statement's ciphertext in place — the per-row
    category-correction path (StatementList.tsx): the client decrypts the
    full transaction list, edits one row's category client-side, then
    re-encrypts and PUTs the whole list back. Same 'server never sees
    plaintext' contract as POST /save — this endpoint only ever swaps one
    opaque blob for another."""
    statement = db.get(BankStatement, statement_id)
    if not statement or statement.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Statement not found.")

    statement.ciphertext = base64.b64decode(body.ciphertext_b64)
    statement.iv = base64.b64decode(body.iv_b64)
    db.commit()
    db.refresh(statement)
    return StatementOut(
        id=statement.id,
        source_account=statement.source_account,
        period_label=statement.period_label,
        created_at=statement.created_at.isoformat(),
    )


@router.delete("/{statement_id}", status_code=204)
def delete_statement(
    statement_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Deliberately not something the chat agents can invoke — same
    reasoning as payslip.py's delete_snapshot: deleting saved data stays
    behind an explicit UI action the user clicks."""
    statement = db.get(BankStatement, statement_id)
    if not statement or statement.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Statement not found.")
    db.delete(statement)
    db.commit()


@router.get("/list", response_model=list[StatementFull])
def list_statements(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[StatementFull]:
    rows = db.scalars(
        select(BankStatement)
        .where(BankStatement.user_id == user.id)
        .order_by(BankStatement.period_label.asc())
    ).all()
    return [
        StatementFull(
            id=row.id,
            source_account=row.source_account,
            period_label=row.period_label,
            ciphertext_b64=base64.b64encode(row.ciphertext).decode(),
            iv_b64=base64.b64encode(row.iv).decode(),
            created_at=row.created_at.isoformat(),
        )
        for row in rows
    ]
