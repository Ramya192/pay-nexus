"""
JWT issuing/verification + login password hashing. Distinct from
encryption.py's salt: this file only answers "is this the right user",
never touches salary data or the client's encryption key.
"""

from datetime import datetime, timedelta, timezone
from typing import Annotated

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from config import config
from db.database import get_db
from db.models import User

_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=True)

# bcrypt's algorithm hard-caps input at 72 bytes and raises past that (older
# wrapper libraries used to truncate silently — this one doesn't). Truncate
# ourselves so a long password degrades to "only the first 72 bytes count"
# rather than a 500. Originally went through passlib's CryptContext, but
# passlib (unmaintained since 2020) runs an internal self-test on bcrypt
# backend init that hard-crashes against bcrypt>=4.1 — calling bcrypt
# directly here instead, since it's actively maintained and this is a thin
# enough wrapper that passlib wasn't earning its keep.
_BCRYPT_MAX_BYTES = 72


def _prepare(password: str) -> bytes:
    return password.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prepare(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(_prepare(password), hashed.encode("utf-8"))


def create_access_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=config.JWT_EXPIRE_MINUTES)
    payload = {"sub": user_id, "exp": expire}
    return jwt.encode(payload, config.JWT_SECRET_KEY, algorithm=config.JWT_ALGORITHM)


def decode_access_token(token: str) -> str:
    """Returns the user id encoded in a valid token; raises a 401 otherwise."""
    try:
        payload = jwt.decode(token, config.JWT_SECRET_KEY, algorithms=[config.JWT_ALGORITHM])
    except JWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")

    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    return user_id


def get_current_user(
    token: Annotated[str, Depends(_oauth2_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    """FastAPI dependency: `user: User = Depends(get_current_user)`."""
    user_id = decode_access_token(token)
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    return user
