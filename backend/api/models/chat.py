"""
Request schema for POST /chat. `payslip_data` arrives already decrypted —
the client decrypts client-side and sends plaintext values only within this
authenticated, HTTPS session (§4); nothing here is stored as-is (see
api/models/payslip.py for the ciphertext-only persistence path).
"""

from pydantic import BaseModel


class ChatRequest(BaseModel):
    query: str
    payslip_data: dict | None = None
    # Already-compressed summaries (decrypted client-side from GET
    # /payslip/history) — the orchestrator applies Level 1 sliding-window
    # compression on top of whatever's passed here (§6).
    session_history: list[dict] | None = None


class SummarizeRequest(BaseModel):
    """Level 2 compression input (§6) — the client's own running list of
    {query, response} exchanges from this session, gathered client-side
    from chatStore, plus the current payslip snapshot. Plaintext: this
    endpoint computes the summary server-side (an OpenAI call), the same
    trust boundary /chat already uses for payslip_data — the client is
    responsible for encrypting the *response* before persisting it via
    POST /payslip/session-summary, since only the client holds the key."""

    exchanges: list[dict]
    payslip_data: dict | None = None


class SummarizeResponse(BaseModel):
    summary: dict
