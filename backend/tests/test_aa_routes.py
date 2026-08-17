"""Route-level tests for api/routes/aa.py — real FastAPI request/response
cycle against an in-memory database (tests/conftest.py's `client` fixture).
Every Setu network call is monkeypatched at the setu_aa_client module level
(same module object api/routes/aa.py calls into) — a route test shouldn't
depend on a live sandbox, per the AA integration plan's own test scope.
categorize_transactions is stubbed too, purely so this file doesn't need a
real OPENAI_API_KEY to pass: the categorization logic itself already has
its own dedicated tests (test_categorization.py).
"""

import pytest

import setu_aa_client
from api.routes import aa as aa_routes


@pytest.fixture(autouse=True)
def stub_categorize(monkeypatch):
    def _fake_categorize(transactions):
        for t in transactions:
            t.category = "Uncategorized"
            t.category_source = None
        return transactions

    monkeypatch.setattr(aa_routes, "categorize_transactions", _fake_categorize)


def _fi_data(transactions):
    return {"account": {"maskedAccNumber": "XXXX1234", "transactions": {"transaction": transactions}}}


_SAMPLE_FI_DATA = _fi_data(
    [
        {"amount": "5000", "type": "CREDIT", "narration": "Salary", "transactionTimestamp": "2026-07-01T10:00:00+00:00"},
        {"amount": "1200", "type": "DEBIT", "narration": "Groceries", "transactionTimestamp": "2026-07-03T10:00:00+00:00"},
    ]
)


class TestConsentAuth:
    def test_create_consent_requires_auth(self, client):
        assert client.post("/aa/consent", json={"vua": "9999999999@setu"}).status_code == 401

    def test_get_consent_status_requires_auth(self, client):
        assert client.get("/aa/consent/some-id").status_code == 401

    def test_fetch_requires_auth(self, client):
        body = {"consent_id": "some-id", "source_account": "HDFC (via Setu)"}
        assert client.post("/aa/fetch", json=body).status_code == 401


class TestWebhookNoAuth:
    def test_webhook_accepts_unauthenticated_requests(self, client):
        # Setu's servers call this directly — no logged-in user, no JWT to check.
        response = client.post("/aa/webhook", json={"consentId": "unknown", "data": {"status": "ACTIVE"}})
        assert response.status_code == 200

    def test_webhook_updates_known_consent_status(self, client, auth_headers, monkeypatch):
        monkeypatch.setattr(
            setu_aa_client, "create_consent", lambda vua, months=4: {"id": "consent-1", "url": "https://approve.example", "status": "PENDING"}
        )
        client.post("/aa/consent", json={"vua": "9999999999@setu"}, headers=auth_headers)

        webhook_response = client.post(
            "/aa/webhook", json={"consentId": "consent-1", "data": {"status": "ACTIVE"}}
        )
        assert webhook_response.status_code == 200

        # Proof the webhook actually persisted the status change (not just
        # acked): POST /aa/fetch's own ACTIVE check passes on this alone,
        # with no intervening GET /aa/consent/{id} refresh call.
        monkeypatch.setattr(setu_aa_client, "create_data_session", lambda consent_id, date_from, date_to: {"id": "session-1"})
        monkeypatch.setattr(setu_aa_client, "poll_and_fetch_session", lambda session_id, timeout_s=60: _SAMPLE_FI_DATA)
        fetch_response = client.post(
            "/aa/fetch",
            json={"consent_id": "consent-1", "source_account": "HDFC (via Setu)"},
            headers=auth_headers,
        )
        assert fetch_response.status_code == 200

    def test_webhook_malformed_payload_still_acks(self, client):
        response = client.post("/aa/webhook", json={"nonsense": True})
        assert response.status_code == 200
        assert response.json() == {"received": True}


class TestCreateConsent:
    def test_creates_consent_row_and_returns_webview_url(self, client, auth_headers, monkeypatch):
        monkeypatch.setattr(
            setu_aa_client,
            "create_consent",
            lambda vua, months=4: {"id": "consent-1", "url": "https://approve.example/webview", "status": "PENDING"},
        )
        response = client.post("/aa/consent", json={"vua": "9999999999@setu"}, headers=auth_headers)
        assert response.status_code == 201
        body = response.json()
        assert body == {"consent_id": "consent-1", "webview_url": "https://approve.example/webview", "status": "PENDING"}


class TestGetConsentStatus:
    def test_404_for_unknown_consent(self, client, auth_headers):
        response = client.get("/aa/consent/does-not-exist", headers=auth_headers)
        assert response.status_code == 404

    def test_refreshes_status_from_setu(self, client, auth_headers, monkeypatch):
        monkeypatch.setattr(
            setu_aa_client, "create_consent", lambda vua, months=4: {"id": "consent-1", "url": "https://x", "status": "PENDING"}
        )
        client.post("/aa/consent", json={"vua": "9999999999@setu"}, headers=auth_headers)

        monkeypatch.setattr(setu_aa_client, "get_consent_status", lambda consent_id: {"id": consent_id, "status": "ACTIVE"})
        response = client.get("/aa/consent/consent-1", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["status"] == "ACTIVE"

    def test_isolated_between_users(self, client, make_auth_headers, monkeypatch):
        user_a = make_auth_headers()
        user_b = make_auth_headers()
        monkeypatch.setattr(
            setu_aa_client, "create_consent", lambda vua, months=4: {"id": "consent-a", "url": "https://x", "status": "PENDING"}
        )
        client.post("/aa/consent", json={"vua": "9999999999@setu"}, headers=user_a)

        response = client.get("/aa/consent/consent-a", headers=user_b)
        assert response.status_code == 404


class TestFetch:
    def _link_and_activate(self, client, auth_headers, monkeypatch, consent_id="consent-1"):
        monkeypatch.setattr(
            setu_aa_client,
            "create_consent",
            lambda vua, months=4: {"id": consent_id, "url": "https://x", "status": "PENDING"},
        )
        client.post("/aa/consent", json={"vua": "9999999999@setu"}, headers=auth_headers)
        monkeypatch.setattr(setu_aa_client, "get_consent_status", lambda cid: {"id": cid, "status": "ACTIVE"})
        client.get(f"/aa/consent/{consent_id}", headers=auth_headers)

    def test_fetch_rejects_non_active_consent(self, client, auth_headers, monkeypatch):
        monkeypatch.setattr(
            setu_aa_client, "create_consent", lambda vua, months=4: {"id": "consent-1", "url": "https://x", "status": "PENDING"}
        )
        client.post("/aa/consent", json={"vua": "9999999999@setu"}, headers=auth_headers)

        response = client.post(
            "/aa/fetch",
            json={"consent_id": "consent-1", "source_account": "HDFC (via Setu)"},
            headers=auth_headers,
        )
        assert response.status_code == 409

    def test_fetch_404_for_unknown_consent(self, client, auth_headers):
        response = client.post(
            "/aa/fetch",
            json={"consent_id": "does-not-exist", "source_account": "HDFC (via Setu)"},
            headers=auth_headers,
        )
        assert response.status_code == 404

    def test_fetch_returns_mapped_and_categorized_transactions(self, client, auth_headers, monkeypatch):
        self._link_and_activate(client, auth_headers, monkeypatch)
        monkeypatch.setattr(setu_aa_client, "create_data_session", lambda consent_id, date_from, date_to: {"id": "session-1"})
        monkeypatch.setattr(setu_aa_client, "poll_and_fetch_session", lambda session_id, timeout_s=60: _SAMPLE_FI_DATA)

        response = client.post(
            "/aa/fetch",
            json={"consent_id": "consent-1", "source_account": "HDFC (via Setu)"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["skipped_row_count"] == 0
        assert len(body["transactions"]) == 2
        amounts = sorted(t["amount"] for t in body["transactions"])
        assert amounts == [-1200.0, 5000.0]
        assert all(t["source_account"] == "HDFC (via Setu)" for t in body["transactions"])
        assert all(t["category"] == "Uncategorized" for t in body["transactions"])

    def test_fetch_reports_skipped_rows(self, client, auth_headers, monkeypatch):
        self._link_and_activate(client, auth_headers, monkeypatch)
        fi_data_with_bad_row = _fi_data(
            [
                {"amount": "100", "type": "CREDIT", "transactionTimestamp": "2026-07-01T10:00:00+00:00"},
                {"amount": "not-a-number", "type": "DEBIT", "transactionTimestamp": "2026-07-02T10:00:00+00:00"},
            ]
        )
        monkeypatch.setattr(setu_aa_client, "create_data_session", lambda consent_id, date_from, date_to: {"id": "session-1"})
        monkeypatch.setattr(setu_aa_client, "poll_and_fetch_session", lambda session_id, timeout_s=60: fi_data_with_bad_row)

        response = client.post(
            "/aa/fetch",
            json={"consent_id": "consent-1", "source_account": "HDFC (via Setu)"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["skipped_row_count"] == 1
        assert len(body["transactions"]) == 1

    def test_fetch_502_when_session_id_missing(self, client, auth_headers, monkeypatch):
        self._link_and_activate(client, auth_headers, monkeypatch)
        monkeypatch.setattr(setu_aa_client, "create_data_session", lambda consent_id, date_from, date_to: {})
        response = client.post(
            "/aa/fetch",
            json={"consent_id": "consent-1", "source_account": "HDFC (via Setu)"},
            headers=auth_headers,
        )
        assert response.status_code == 502

    def test_fetch_504_on_timeout(self, client, auth_headers, monkeypatch):
        self._link_and_activate(client, auth_headers, monkeypatch)
        monkeypatch.setattr(setu_aa_client, "create_data_session", lambda consent_id, date_from, date_to: {"id": "session-1"})

        def _raise_timeout(session_id, timeout_s=60):
            raise TimeoutError("session never completed")

        monkeypatch.setattr(setu_aa_client, "poll_and_fetch_session", _raise_timeout)

        response = client.post(
            "/aa/fetch",
            json={"consent_id": "consent-1", "source_account": "HDFC (via Setu)"},
            headers=auth_headers,
        )
        assert response.status_code == 504

    def test_fetch_isolated_between_users(self, client, make_auth_headers, monkeypatch):
        user_a = make_auth_headers()
        user_b = make_auth_headers()
        self._link_and_activate(client, user_a, monkeypatch)

        response = client.post(
            "/aa/fetch",
            json={"consent_id": "consent-1", "source_account": "HDFC (via Setu)"},
            headers=user_b,
        )
        assert response.status_code == 404

    def test_fetch_does_not_persist_anything(self, client, auth_headers, monkeypatch):
        """Same 'parse first, review, then explicitly save' contract as
        POST /statement/parse — this endpoint returns transactions but must
        not write a BankStatement row itself."""
        self._link_and_activate(client, auth_headers, monkeypatch)
        monkeypatch.setattr(setu_aa_client, "create_data_session", lambda consent_id, date_from, date_to: {"id": "session-1"})
        monkeypatch.setattr(setu_aa_client, "poll_and_fetch_session", lambda session_id, timeout_s=60: _SAMPLE_FI_DATA)

        client.post(
            "/aa/fetch",
            json={"consent_id": "consent-1", "source_account": "HDFC (via Setu)"},
            headers=auth_headers,
        )
        # No dedicated GET /statement/list endpoint assumption made here —
        # instead, confirm indirectly: fetching again with the same mocked
        # data must not 409/conflict the way POST /statement/save would on
        # a duplicate, since nothing was saved the first time.
        second_response = client.post(
            "/aa/fetch",
            json={"consent_id": "consent-1", "source_account": "HDFC (via Setu)"},
            headers=auth_headers,
        )
        assert second_response.status_code == 200
