"""
Thin HTTP client for Setu's Account Aggregator sandbox API — auth token
caching, consent creation/status, data session creation/fetch. One-shot
utility module, not a LangGraph node — same placement convention as
payslip_extraction.py/statement_extraction.py, just talking to an external
API instead of OpenAI.

Verified against docs.setu.co while planning this integration (2026-08) —
the endpoint paths/payloads below aren't guessed from the general AA/ReBIT
spec, they're quoted from Setu's own docs:
- Auth: POST {SETU_AA_TOKEN_URL} {"clientID", "secret"} ->
  {"data": {"token", "expiresIn"}}. Token host is deliberately different
  from the consent/session host — see config.py's SETU_AA_TOKEN_URL comment.
- Consent: POST {SETU_AA_BASE_URL}/consents -> {"id", "url", "status", "detail"}.
  `url` is a Setu-hosted webview for the user's browser (mobile + OTP +
  bank selection) — nothing is actually linked until they complete it.
- Session: POST {SETU_AA_BASE_URL}/sessions -> a session id;
  GET /sessions/:id for status, and (once PARTIAL/COMPLETED) the actual FI
  data in the same response.
- Setu decrypts FI data before handing it back — confirmed from their docs,
  not assumed — so there's no ECDH/AES layer to implement on this side.

Two things flagged as genuinely unverified rather than assumed correct,
both because they can only be confirmed against a real sandbox response,
not from documentation alone: (1) whether GET /sessions/:id's interim
(not-yet-ready) response nests "status" under a "data" key the way webhook
payloads do, or puts it at the top level — poll_and_fetch_session checks
both; (2) the exact shape of a transaction's description/narration field —
handled in aa_transaction_mapping.py, not here.

Sandbox only. No real bank data, no KYC required at this tier.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import httpx

from config import config

_client = httpx.Client(timeout=30.0)

# Module-level cache — one token shared across every call in this process,
# refreshed a safety margin before Setu's own expiry rather than reacting
# to a 401. Setu's default token lifetime is 1800s (30 minutes).
_TOKEN_REFRESH_MARGIN_S = 60
_token_cache: dict[str, float | str] = {}


def get_access_token() -> str:
    """Cached, auto-refreshing bearer token — re-authenticates only when
    the cached token is missing or within _TOKEN_REFRESH_MARGIN_S of
    expiring, not on every call."""
    cached_token = _token_cache.get("token")
    expires_at = _token_cache.get("expires_at", 0.0)
    if cached_token and time.time() < expires_at - _TOKEN_REFRESH_MARGIN_S:
        return cached_token  # type: ignore[return-value]

    response = _client.post(
        config.SETU_AA_TOKEN_URL,
        json={"clientID": config.SETU_AA_CLIENT_ID, "secret": config.SETU_AA_CLIENT_SECRET},
    )
    response.raise_for_status()
    data = response.json()["data"]
    _token_cache["token"] = data["token"]
    _token_cache["expires_at"] = time.time() + data["expiresIn"]
    return data["token"]


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {get_access_token()}",
        "x-product-instance-id": config.SETU_AA_PRODUCT_INSTANCE_ID,
        "Content-Type": "application/json",
    }


def months_ago(months: int) -> str:
    now = datetime.now(timezone.utc)
    year, month = now.year, now.month - months
    while month <= 0:
        month += 12
        year -= 1
    day = min(now.day, 28)  # sidesteps month-end overflow (e.g. Aug 31 minus 4 months)
    return now.replace(year=year, month=month, day=day).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_iso() -> str:
    """The actual current instant, unlike months_ago(0) — which would
    wrongly cap today's day-of-month at 28 (that capping only makes sense
    when *subtracting* months, to dodge month-end overflow; today's own
    date needs no such adjustment)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def create_consent(vua: str, months: int = 4) -> dict:
    """Starts a new AA consent request — DEPOSIT (bank) accounts only, per
    V2's MVP scope; Setu's dashboard has other FI types registered but this
    call deliberately doesn't request them yet. `vua` is the user's mobile
    number + AA handle (e.g. "9999999999@setu") — asked inline by the
    frontend each time, not persisted (see PROJECT_CONTEXT.md's AA scope
    decisions). Returns {"id", "url", "status", "detail"}."""
    response = _client.post(
        f"{config.SETU_AA_BASE_URL}/consents",
        headers=_headers(),
        json={
            "consentDuration": {"unit": "MONTH", "value": str(months)},
            "vua": vua,
            "dataRange": {"from": months_ago(months), "to": now_iso()},
            "context": [],
            "additionalParams": {"tags": ["PayNexus"]},
        },
    )
    response.raise_for_status()
    return response.json()


def get_consent_status(consent_id: str) -> dict:
    response = _client.get(f"{config.SETU_AA_BASE_URL}/consents/{consent_id}", headers=_headers())
    response.raise_for_status()
    return response.json()


def create_data_session(consent_id: str, date_from: str, date_to: str) -> dict:
    response = _client.post(
        f"{config.SETU_AA_BASE_URL}/sessions",
        headers=_headers(),
        json={"consentId": consent_id, "dataRange": {"from": date_from, "to": date_to}, "format": "json"},
    )
    response.raise_for_status()
    return response.json()


_TERMINAL_SESSION_STATUSES = {"COMPLETED", "PARTIAL", "FAILED", "EXPIRED"}
_POLL_INTERVAL_S = 3


def poll_and_fetch_session(session_id: str, timeout_s: int = 60) -> dict:
    """Polls GET /sessions/:id until Setu reports a terminal status, instead
    of waiting on the webhook (see setu_aa_client.py module docstring / the
    AA integration plan's scope decision: a local backend isn't reachable
    from Setu's servers without ngrok, so the path that actually drives the
    UI polls directly rather than depending on that). Raises TimeoutError
    past `timeout_s` rather than hanging indefinitely — a slow/stuck
    sandbox session shouldn't leave a request hanging forever."""
    deadline = time.time() + timeout_s
    while True:
        response = _client.get(f"{config.SETU_AA_BASE_URL}/sessions/{session_id}", headers=_headers())
        response.raise_for_status()
        session = response.json()
        status = session.get("status") or session.get("data", {}).get("status")
        if status in _TERMINAL_SESSION_STATUSES:
            return session
        if time.time() >= deadline:
            raise TimeoutError(
                f"Data session {session_id} did not reach a terminal status within {timeout_s}s "
                f"(last status: {status})"
            )
        time.sleep(_POLL_INTERVAL_S)
