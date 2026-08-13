"""
POST /payslip/save, GET /payslip/history — PROJECT_CONTEXT.md §9. Both only
ever handle ciphertext: the blob arrives already AES-256-GCM encrypted from
the browser (§4) and is stored/returned as-is, decrypted only by the client.
"""

import base64

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.models.payslip import (
    PayslipSaveRequest,
    PayslipSnapshotOut,
    SessionSummaryOut,
    SessionSummarySaveRequest,
)
from db.database import get_db
from db.models import PayslipSnapshot, SessionSummary, User
from security.auth import get_current_user

router = APIRouter(prefix="/payslip", tags=["payslip"])


@router.post("/save", response_model=PayslipSnapshotOut, status_code=201)
def save_payslip(
    body: PayslipSaveRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PayslipSnapshotOut:
    snapshot = PayslipSnapshot(
        user_id=user.id,
        month=body.month,
        ciphertext=base64.b64decode(body.ciphertext_b64),
        iv=base64.b64decode(body.iv_b64),
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return PayslipSnapshotOut(id=snapshot.id, month=snapshot.month, created_at=snapshot.created_at.isoformat())


@router.post("/session-summary", response_model=SessionSummaryOut, status_code=201)
def save_session_summary(
    body: SessionSummarySaveRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SessionSummaryOut:
    """Persists the Level 2 compressed summary (§6) — called from the
    frontend's logout flow, after POST /chat/summarize computed the
    plaintext and the client encrypted it. See get_history below for the
    read side."""
    summary = SessionSummary(
        user_id=user.id,
        ciphertext=base64.b64decode(body.ciphertext_b64),
        iv=base64.b64decode(body.iv_b64),
    )
    db.add(summary)
    db.commit()
    db.refresh(summary)
    return SessionSummaryOut(
        id=summary.id,
        ciphertext_b64=base64.b64encode(summary.ciphertext).decode(),
        iv_b64=base64.b64encode(summary.iv).decode(),
        created_at=summary.created_at.isoformat(),
    )


@router.get("/history", response_model=list[SessionSummaryOut])
def get_history(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[SessionSummaryOut]:
    """Compressed session summaries for the Nudge Agent (§9) — still
    ciphertext here; the client decrypts before handing plaintext to
    /chat's session_history field."""
    rows = db.scalars(
        select(SessionSummary)
        .where(SessionSummary.user_id == user.id)
        .order_by(SessionSummary.created_at.desc())
    ).all()
    return [
        SessionSummaryOut(
            id=row.id,
            ciphertext_b64=base64.b64encode(row.ciphertext).decode(),
            iv_b64=base64.b64encode(row.iv).decode(),
            created_at=row.created_at.isoformat(),
        )
        for row in rows
    ]
