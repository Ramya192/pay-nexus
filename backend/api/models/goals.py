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
      "instrumentType": string | null,  # "fd" | "mutual_fund" | absent/null for a plain manual-entry goal (V2.1)
      "fdPrincipal": number | null,      # instrumentType "fd" only
      "fdAnnualRate": number | null,     # instrumentType "fd" only — annual %, e.g. 7.0 for 7%
      "fdStartDate": string | null,      # instrumentType "fd" only — "YYYY-MM-DD"
      "mfSchemeCode": string | null,     # instrumentType "mutual_fund" only — an AMFI scheme code
      "mfUnitsHeld": number | null,      # instrumentType "mutual_fund" only
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


class GoalValuationRequest(BaseModel):
    """One entry per investment-linked goal to (re-)value — see
    analytics/investment_valuation.py. `goal_id` here is just a caller-
    supplied label to match a response entry back to its goal (the
    client's own local goal id works fine); the server never persists or
    otherwise cares about it."""

    goal_id: str
    instrument_type: str  # "fd" | "mutual_fund"
    fd_principal: float | None = None
    fd_annual_rate: float | None = None
    fd_start_date: str | None = None
    mf_scheme_code: str | None = None
    mf_units_held: float | None = None


class GoalValuationResult(BaseModel):
    goal_id: str
    current_value: float | None
    error: str | None
