"""
Request/response schemas for Account Aggregator integration (Setu sandbox,
V2). No ciphertext contract here — see db/models.py's AAConsent docstring
for why consent metadata stays plaintext. The actual financial data a
completed consent unlocks flows out as plaintext transactions too (same
trust tier as POST /statement/parse's response — reviewed by the user,
nothing persisted until they explicitly save via the existing
POST /statement/save).
"""

from pydantic import BaseModel

from api.models.statement import TransactionOut


class ConsentCreateRequest(BaseModel):
    vua: str  # mobile number + AA handle, e.g. "9999999999@setu" — asked inline, never persisted


class ConsentCreateResponse(BaseModel):
    consent_id: str
    webview_url: str  # Setu-hosted page — redirect the user's browser here to approve
    status: str


class ConsentStatusResponse(BaseModel):
    consent_id: str
    status: str


class FetchRequest(BaseModel):
    consent_id: str
    source_account: str  # display label for the linked account, e.g. "HDFC (via Setu)"
    months: int = 4  # how far back to request FI data — must be within the consent's own authorized range


class FetchResponse(BaseModel):
    transactions: list[TransactionOut]
    skipped_row_count: int  # FI transaction rows that couldn't be normalized (missing date/amount/type)
