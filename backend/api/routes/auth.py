"""
POST /auth/register, POST /auth/login — see PROJECT_CONTEXT.md §9.

Both issue a JWT and the user's encryption_salt, so the client can
immediately derive its AES-256-GCM key (§4) without a second round trip.

Not yet wired into a FastAPI app — api/main.py (Phase 4) will
`app.include_router(auth.router)`.
"""

import base64

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api.models.user import TokenResponse, UserLogin, UserRegister
from db.database import get_db
from db.models import User
from security.auth import create_access_token, hash_password, verify_password
from security.encryption import generate_salt

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(body: UserRegister, db: Session = Depends(get_db)) -> TokenResponse:
    if db.query(User).filter(User.email == body.email).first() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists.")

    user = User(
        email=body.email,
        hashed_password=hash_password(body.password),
        encryption_salt=generate_salt(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return TokenResponse(
        access_token=create_access_token(user.id),
        encryption_salt=base64.b64encode(user.encryption_salt).decode(),
    )


@router.post("/login", response_model=TokenResponse)
def login(body: UserLogin, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.query(User).filter(User.email == body.email).first()
    if user is None or not verify_password(body.password, user.hashed_password):
        # Deliberately the same error for "no such user" and "wrong password" —
        # distinguishing them lets an attacker enumerate registered emails.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password.")

    return TokenResponse(
        access_token=create_access_token(user.id),
        encryption_salt=base64.b64encode(user.encryption_salt).decode(),
    )
