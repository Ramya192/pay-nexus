"""
POST /aa/consent, GET /aa/consent/{id}, POST /aa/webhook, POST /aa/fetch —
Account Aggregator integration (Setu sandbox, V2). See setu_aa_client.py's
module docstring for the verified API contracts this wraps, and
aa_transaction_mapping.py for how fetched data becomes a Transaction list.

POST /aa/fetch is the endpoint that actually drives the UI — it polls Setu
directly (setu_aa_client.poll_and_fetch_session) rather than waiting on
POST /aa/webhook, since a local backend isn't reachable from Setu's servers
without ngrok. The webhook receiver is still built to spec (real, correct,
demonstrates the production pattern) but isn't on the critical path for
actually using this feature locally.

Nothing here persists financial data — POST /aa/fetch returns transactions
for review, same "parse first, review, then explicitly save" contract as
POST /statement/parse; saving still goes through the existing
POST /statement/save, completely unmodified by this file.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

import setu_aa_client
from aa_transaction_mapping import map_fi_data_to_transactions
from api.models.aa import (
    ConsentCreateRequest,
    ConsentCreateResponse,
    ConsentStatusResponse,
    FetchRequest,
    FetchResponse,
)
from api.models.statement import TransactionOut
from categorization.categorize import categorize_transactions
from db.database import get_db
from db.models import AAConsent, User
from security.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/aa", tags=["account-aggregator"])


@router.post("/consent", response_model=ConsentCreateResponse, status_code=201)
def create_consent(
    body: ConsentCreateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ConsentCreateResponse:
    result = setu_aa_client.create_consent(body.vua)
    consent = AAConsent(
        id=result["id"], user_id=user.id, vua=body.vua, status=result.get("status", "PENDING")
    )
    db.add(consent)
    db.commit()
    return ConsentCreateResponse(consent_id=result["id"], webview_url=result["url"], status=consent.status)


@router.get("/consent/{consent_id}", response_model=ConsentStatusResponse)
def get_consent_status(
    consent_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ConsentStatusResponse:
    consent = db.get(AAConsent, consent_id)
    if not consent or consent.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Consent not found.")

    result = setu_aa_client.get_consent_status(consent_id)
    fresh_status = result.get("status", consent.status)
    if fresh_status != consent.status:
        consent.status = fresh_status
        db.commit()
    return ConsentStatusResponse(consent_id=consent_id, status=fresh_status)


@router.post("/webhook", status_code=200)
def webhook(payload: dict, db: Session = Depends(get_db)) -> dict:
    """Receives Setu's CONSENT_STATUS_UPDATE / SESSION_STATUS_UPDATE
    notifications — built to spec, not required for local use (see module
    docstring). Deliberately no auth dependency: Setu's servers call this
    directly, not a logged-in PayNexus user, so there's no JWT to check —
    same reasoning payslip.py's endpoints all DO require auth and this one
    structurally can't."""
    consent_id = payload.get("consentId")
    new_status = (payload.get("data") or {}).get("status")
    if not consent_id or not new_status:
        return {"received": True}  # malformed/unrecognized payload — ack anyway, nothing to update

    consent = db.get(AAConsent, consent_id)
    if consent:
        consent.status = new_status
        db.commit()
    else:
        logger.warning("AA webhook received for unknown consent id %s", consent_id)
    return {"received": True}


@router.post("/fetch", response_model=FetchResponse)
def fetch_via_aa(
    body: FetchRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FetchResponse:
    consent = db.get(AAConsent, body.consent_id)
    if not consent or consent.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Consent not found.")
    if consent.status != "ACTIVE":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Consent is {consent.status}, not ACTIVE yet — complete the approval flow first.",
        )

    session = setu_aa_client.create_data_session(
        consent.id, date_from=setu_aa_client.months_ago(body.months), date_to=setu_aa_client.now_iso()
    )
    session_id = session.get("id") or session.get("sessionId")
    if not session_id:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Setu did not return a data session id.")

    try:
        completed = setu_aa_client.poll_and_fetch_session(session_id)
    except TimeoutError as exc:
        raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, str(exc)) from None

    transactions, skipped = map_fi_data_to_transactions(completed, body.source_account)
    transactions = categorize_transactions(transactions)

    return FetchResponse(
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
        skipped_row_count=len(skipped),
    )
