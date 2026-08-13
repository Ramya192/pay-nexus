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


class PayslipSnapshotFull(BaseModel):
    """GET /payslip/snapshots — unlike PayslipSnapshotOut (returned from
    POST /save, just a receipt), this carries the ciphertext back so the
    client can decrypt every saved month and compute real trends from them
    (see backend/payslip_trends.py)."""

    id: str
    month: str
    ciphertext_b64: str
    iv_b64: str
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


class PayslipParseRequest(BaseModel):
    """Body for POST /payslip/parse — text already extracted client-side
    from an uploaded PDF (frontend/.../PDFParser.tsx). Plaintext; the PDF
    itself never reaches the server."""

    text: str


class PayslipParseResponse(BaseModel):
    fields: dict
