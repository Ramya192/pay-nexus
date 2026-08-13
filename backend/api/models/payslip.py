"""
Request/response schemas for payslip persistence. `ciphertext_b64`/`iv_b64`
are the AES-256-GCM blob + nonce produced client-side (§4), base64-encoded
for JSON transport — this file, like db/models.py, never carries a
plaintext salary figure.
"""

from pydantic import BaseModel


class PayslipSaveRequest(BaseModel):
    month: str  # e.g. "2026-07"
    ciphertext_b64: str
    iv_b64: str


class PayslipSnapshotOut(BaseModel):
    id: str
    month: str
    created_at: str


class SessionSummaryOut(BaseModel):
    id: str
    ciphertext_b64: str
    iv_b64: str
    created_at: str


class SessionSummarySaveRequest(BaseModel):
    """Body for POST /payslip/session-summary — the client encrypts the
    plaintext dict POST /chat/summarize returned before sending it here;
    same ciphertext-only contract as PayslipSaveRequest."""

    ciphertext_b64: str
    iv_b64: str
