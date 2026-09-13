"""
GET/PUT /financial-profile — encrypted investments/loans/insurance profile,
same ciphertext-only contract as api/routes/payslip.py. Upserted in place
(one row per user, see db/models.py's FinancialProfile docstring for why),
not a growing log — PUT always replaces whatever's there.
"""

import base64

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api.models.financial_profile import FinancialProfileOut, FinancialProfileSaveRequest
from db.database import get_db
from db.models import FinancialProfile, User
from security.auth import get_current_user

router = APIRouter(prefix="/financial-profile", tags=["financial-profile"])


@router.put("", response_model=FinancialProfileOut)
def save_financial_profile(
    body: FinancialProfileSaveRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FinancialProfileOut:
    ciphertext = base64.b64decode(body.ciphertext_b64)
    iv = base64.b64decode(body.iv_b64)

    existing = db.query(FinancialProfile).filter(FinancialProfile.user_id == user.id).first()
    if existing:
        existing.ciphertext = ciphertext
        existing.iv = iv
        profile = existing
    else:
        profile = FinancialProfile(user_id=user.id, ciphertext=ciphertext, iv=iv)
        db.add(profile)

    db.commit()
    db.refresh(profile)
    return FinancialProfileOut(
        ciphertext_b64=base64.b64encode(profile.ciphertext).decode(),
        iv_b64=base64.b64encode(profile.iv).decode(),
        updated_at=profile.updated_at.isoformat(),
    )


@router.get("", response_model=FinancialProfileOut)
def get_financial_profile(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FinancialProfileOut:
    profile = db.query(FinancialProfile).filter(FinancialProfile.user_id == user.id).first()
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No financial profile saved yet.")
    return FinancialProfileOut(
        ciphertext_b64=base64.b64encode(profile.ciphertext).decode(),
        iv_b64=base64.b64encode(profile.iv).decode(),
        updated_at=profile.updated_at.isoformat(),
    )
