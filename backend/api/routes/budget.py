"""
GET/PUT /budget — encrypted per-category budget, same ciphertext-only
contract as api/routes/financial_profile.py. Upserted in place (one row per
user, see db/models.py's Budget docstring for why), not a growing log — PUT
always replaces whatever's there.

GET /budget/suggested is the one plaintext exception — a salary-bracket-
scaled starting point (budgeting/budgets.py), no user data involved, so it
skips the ciphertext contract entirely; the frontend calls it once to
pre-fill the Budget tab's form, which the user can still edit before
actually saving anything via PUT.
"""

import base64

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api.models.budget import BudgetOut, BudgetSaveRequest, SuggestedBudgetResponse
from budgeting.budgets import (
    bracket_for_monthly_income,
    suggested_budgets_for_salary_bracket,
)
from db.database import get_db
from db.models import Budget, User
from security.auth import get_current_user

router = APIRouter(prefix="/budget", tags=["budget"])


@router.put("", response_model=BudgetOut)
def save_budget(
    body: BudgetSaveRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BudgetOut:
    ciphertext = base64.b64decode(body.ciphertext_b64)
    iv = base64.b64decode(body.iv_b64)

    existing = db.query(Budget).filter(Budget.user_id == user.id).first()
    if existing:
        existing.ciphertext = ciphertext
        existing.iv = iv
        budget = existing
    else:
        budget = Budget(user_id=user.id, ciphertext=ciphertext, iv=iv)
        db.add(budget)

    db.commit()
    db.refresh(budget)
    return BudgetOut(
        ciphertext_b64=base64.b64encode(budget.ciphertext).decode(),
        iv_b64=base64.b64encode(budget.iv).decode(),
        updated_at=budget.updated_at.isoformat(),
    )


@router.get("", response_model=BudgetOut)
def get_budget(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BudgetOut:
    budget = db.query(Budget).filter(Budget.user_id == user.id).first()
    if budget is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No budget saved yet.")
    return BudgetOut(
        ciphertext_b64=base64.b64encode(budget.ciphertext).decode(),
        iv_b64=base64.b64encode(budget.iv).decode(),
        updated_at=budget.updated_at.isoformat(),
    )


@router.get("/suggested", response_model=SuggestedBudgetResponse)
def suggested_budget(
    monthly_income: float | None = None,
    _user: User = Depends(get_current_user),
) -> SuggestedBudgetResponse:
    """Pre-fills the Budget tab's form on first visit — `monthly_income` is
    a rough figure the frontend derives from whatever payslip data it
    already has client-side (nothing new sent here just for this); omitted
    entirely, this falls back to the "60k-100k" bracket
    DEFAULT_MONTHLY_BUDGETS was itself calibrated against."""
    bracket = bracket_for_monthly_income(monthly_income) if monthly_income is not None else "60k-100k"
    return SuggestedBudgetResponse(salary_bracket=bracket, budgets=suggested_budgets_for_salary_bracket(bracket))
