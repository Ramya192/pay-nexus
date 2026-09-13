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
    # Decrypted client-side from GET /financial-profile — same trust tier
    # as payslip_data (§4); see tax_calculations.py for what the Nudge and
    # Payslip agents do with it.
    financial_profile: dict | None = None
    # Already-compressed cross-session summaries (decrypted client-side
    # from GET /payslip/history), §6 Level 2 — NOT this session's live
    # back-and-forth; see `conversation` below for that.
    session_history: list[dict] | None = None
    # Decrypted saved payslip snapshots, oldest->newest (from GET
    # /payslip/snapshots — NOT /payslip/history, despite the name
    # similarity to session_history above; see payslip_trends.py).
    payslip_history: list[dict] | None = None
    # THIS session's own exchanges so far, [{query, response}, ...] — the
    # orchestrator applies Level 1 sliding-window compression (§6) to this,
    # not to session_history; lets a follow-up like "consider the payslip
    # history" resolve against the question asked a moment ago instead of
    # being classified in total isolation.
    conversation: list[dict] | None = None


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
    # Exact token/cost for the one LLM call this endpoint makes (see
    # agents/llm_metrics.py) — {} when no exchanges were given, since then
    # no LLM call happened at all, not one that cost $0.
    token_usage: dict = {}
