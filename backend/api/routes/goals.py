"""
POST /goals, PUT /goals/{id}, DELETE /goals/{id}, GET /goals — Goal Tracker
UI CRUD, V2. Ciphertext in, ciphertext out — same contract as payslip.py.
No plaintext discriminator field (see db/models.py's Goal docstring for
why), so there's no duplicate-detection 409 here the way payslip.py's
month check or statement.py's (source_account, period_label) check give —
every POST just creates a new goal.

UI-only for now: not read by /chat (agents/state.py has no `goals` field
yet) — the GoalTracker LangGraph agent that would narrate over these is a
separate, later piece (PROJECT_CONTEXT.md's V2 Phase 3).
"""

import base64

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.models.goals import GoalFull, GoalOut, GoalSaveRequest
from db.database import get_db
from db.models import Goal, User
from security.auth import get_current_user

router = APIRouter(prefix="/goals", tags=["goals"])


@router.post("", response_model=GoalOut, status_code=201)
def create_goal(
    body: GoalSaveRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> GoalOut:
    goal = Goal(
        user_id=user.id,
        ciphertext=base64.b64decode(body.ciphertext_b64),
        iv=base64.b64decode(body.iv_b64),
    )
    db.add(goal)
    db.commit()
    db.refresh(goal)
    return GoalOut(id=goal.id, created_at=goal.created_at.isoformat())


@router.put("/{goal_id}", response_model=GoalOut)
def update_goal(
    goal_id: str,
    body: GoalSaveRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> GoalOut:
    """Full replace, not a partial patch — the client re-encrypts the whole
    goal object (e.g. after editing savedAmount) and sends it here, same
    "client owns the plaintext shape entirely" reasoning as every other
    ciphertext-in-ciphertext-out endpoint."""
    goal = db.get(Goal, goal_id)
    if not goal or goal.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Goal not found.")
    goal.ciphertext = base64.b64decode(body.ciphertext_b64)
    goal.iv = base64.b64decode(body.iv_b64)
    db.commit()
    db.refresh(goal)
    return GoalOut(id=goal.id, created_at=goal.created_at.isoformat())


@router.delete("/{goal_id}", status_code=204)
def delete_goal(
    goal_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    goal = db.get(Goal, goal_id)
    if not goal or goal.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Goal not found.")
    db.delete(goal)
    db.commit()


@router.get("", response_model=list[GoalFull])
def list_goals(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[GoalFull]:
    rows = db.scalars(
        select(Goal).where(Goal.user_id == user.id).order_by(Goal.created_at.asc())
    ).all()
    return [
        GoalFull(
            id=row.id,
            ciphertext_b64=base64.b64encode(row.ciphertext).decode(),
            iv_b64=base64.b64encode(row.iv).decode(),
            created_at=row.created_at.isoformat(),
        )
        for row in rows
    ]
