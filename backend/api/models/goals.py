"""
Request/response schemas for goal persistence (Goal Tracker UI, V2).
`ciphertext_b64`/`iv_b64` are the AES-256-GCM blob + nonce produced
client-side (§4), base64-encoded for JSON transport — same contract as
api/models/payslip.py, never a plaintext goal figure.

Plaintext shape (once decrypted client-side), for reference — the server
never sees this shape:
    {
      "name": string,               # e.g. "Goa Trip", "Home Loan Down Payment"
      "category": string,           # "Trip" | "Home" | "Education" | "Emergency Fund" | "Retirement" | "Other"
      "targetAmount": number,
      "targetDate": string | null,  # "YYYY-MM-DD", optional
      "savedAmount": number,        # progress so far — the field PUT /goals/{id} updates most often
    }
"""

from pydantic import BaseModel


class GoalSaveRequest(BaseModel):
    ciphertext_b64: str
    iv_b64: str


class GoalOut(BaseModel):
    id: str
    created_at: str


class GoalFull(BaseModel):
    """GET /goals — unlike GoalOut (returned from POST/PUT, just a
    receipt), this carries the ciphertext back so the client can decrypt
    and render every saved goal."""

    id: str
    ciphertext_b64: str
    iv_b64: str
    created_at: str
