"""
Request/response schemas for the auth endpoints. The plaintext here (email,
password) is login credentials only — payslip values never pass through
these schemas; see api/models/payslip.py (Phase 4) for that boundary.
"""

from pydantic import BaseModel, EmailStr, Field


class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    # base64-encoded — the client needs this to re-derive its AES-256-GCM
    # key via PBKDF2 (§4). Not a secret by itself: without the user's
    # password it derives nothing, so it's fine in a JSON response body.
    encryption_salt: str


class UserOut(BaseModel):
    id: str
    email: EmailStr

    model_config = {"from_attributes": True}
