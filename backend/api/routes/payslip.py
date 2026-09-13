"""
POST /payslip/save, DELETE /payslip/snapshots/{id}, GET /payslip/snapshots,
GET /payslip/history — PROJECT_CONTEXT.md §9. All ciphertext in, ciphertext
out: blobs arrive already AES-256-GCM encrypted from the browser (§4) and
are stored/returned as-is, decrypted only by the client. Note the naming
wrinkle: /history returns compressed *session summaries* (§6), not payslip
snapshots — /snapshots is the actual payslip-snapshot list, added later
than /history and named for what it is rather than renaming the older
endpoint.

POST /save rejects a second save for a (user, month) pair already on file
with 409 rather than silently creating a duplicate row — the one plaintext
field the server sees (month) is enough to catch that without ever looking
at the encrypted payslip figures themselves.
"""

import base64

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.models.payslip import (
    PayslipParseRequest,
    PayslipParseResponse,
    PayslipSaveRequest,
    PayslipSnapshotFull,
    PayslipSnapshotOut,
    SessionSummaryOut,
    SessionSummarySaveRequest,
)
from db.database import get_db
from db.models import PayslipSnapshot, SessionSummary, User
from payslip_extraction import extract_payslip_fields
from security.auth import get_current_user

router = APIRouter(prefix="/payslip", tags=["payslip"])


@router.post("/parse", response_model=PayslipParseResponse)
def parse_payslip(
    body: PayslipParseRequest,
    _user: User = Depends(get_current_user),
) -> PayslipParseResponse:
    """Turns PDF-extracted text into the same structured fields
    ManualEntryForm collects — pre-fills the form, never auto-submits, so
    upload and manual entry stay two paths into the same editable form
    rather than the PDF path replacing manual entry."""
    if not body.text.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No text to parse.")
    return PayslipParseResponse(fields=extract_payslip_fields(body.text))


@router.post("/save", response_model=PayslipSnapshotOut, status_code=201)
def save_payslip(
    body: PayslipSaveRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PayslipSnapshotOut:
    # `month` is the one payslip field the server sees in plaintext (§4) —
    # everything else stays ciphertext. That's deliberate here: it's what
    # lets the server catch "the same month saved twice" without ever
    # looking at the payslip's actual figures. Found missing in testing —
    # bulk-uploading the same 12 files twice silently produced 24 rows with
    # no signal to the user that anything was duplicated.
    existing = db.scalar(
        select(PayslipSnapshot).where(
            PayslipSnapshot.user_id == user.id, PayslipSnapshot.month == body.month
        )
    )
    if existing:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"A payslip for {body.month} is already saved. Delete it from Payslip history first "
            "if you want to replace it.",
        )

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


@router.delete("/snapshots/{snapshot_id}", status_code=204)
def delete_snapshot(
    snapshot_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Lets the user actually clear out duplicates or a mistaken entry —
    the Payslip history panel's per-row delete button and its "Remove
    duplicates" cleanup action (frontend) both call this. Deliberately not
    something the chat agents can invoke themselves: deleting saved data is
    hard to reverse, so it stays behind an explicit UI action the user
    clicks, not something an LLM can decide to do from a chat message."""
    snapshot = db.get(PayslipSnapshot, snapshot_id)
    if not snapshot or snapshot.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Payslip snapshot not found.")
    db.delete(snapshot)
    db.commit()


@router.get("/snapshots", response_model=list[PayslipSnapshotFull])
def list_snapshots(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[PayslipSnapshotFull]:
    """Every saved payslip snapshot, ciphertext included — distinct from
    GET /payslip/history, which (confusingly, in hindsight) returns
    compressed *session summaries*, not payslip snapshots. The client
    decrypts each row and computes real month-over-month trends from them
    (backend/payslip_trends.py) rather than relying on session-summary
    narrative alone."""
    rows = db.scalars(
        select(PayslipSnapshot)
        .where(PayslipSnapshot.user_id == user.id)
        .order_by(PayslipSnapshot.month.asc())
    ).all()
    return [
        PayslipSnapshotFull(
            id=row.id,
            month=row.month,
            ciphertext_b64=base64.b64encode(row.ciphertext).decode(),
            iv_b64=base64.b64encode(row.iv).decode(),
            created_at=row.created_at.isoformat(),
        )
        for row in rows
    ]


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
