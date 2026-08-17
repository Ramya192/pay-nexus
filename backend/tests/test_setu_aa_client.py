"""Tests for setu_aa_client.py — the Setu sandbox HTTP layer is faked out
entirely (a FakeHttpClient standing in for the module's `_client`), so this
covers token caching/refresh logic and request payload shapes, not real
network behavior. The actual sandbox calls are inherently integration-tier
(real network, real credentials) — see conftest.py's module docstring for
why that line is drawn the same way everywhere else in this suite.
"""

import time
from datetime import datetime, timezone

import pytest

import setu_aa_client
from config import config


class FakeResponse:
    def __init__(self, json_data):
        self._json_data = json_data

    def raise_for_status(self):
        pass

    def json(self):
        return self._json_data


class FakeHttpClient:
    """Stands in for httpx.Client — records every call and returns queued
    responses in order, so a test can assert both on request shape and on
    how many times the network was actually hit."""

    def __init__(self, responses):
        self.calls = []
        self._responses = list(responses)

    def post(self, url, headers=None, json=None):
        self.calls.append({"method": "POST", "url": url, "headers": headers, "json": json})
        return self._responses.pop(0)

    def get(self, url, headers=None):
        self.calls.append({"method": "GET", "url": url, "headers": headers, "json": None})
        return self._responses.pop(0)


@pytest.fixture(autouse=True)
def isolated_config_and_cache(monkeypatch):
    """The token cache is module-level by design (one token shared across a
    process) — reset it before each test so one test's cached token can't
    leak into the next. Config values are pinned to known test values rather
    than whatever's actually in backend/.env, so assertions here don't
    accidentally depend on real sandbox credentials."""
    setu_aa_client._token_cache.clear()
    monkeypatch.setattr(config, "SETU_AA_CLIENT_ID", "test-client-id")
    monkeypatch.setattr(config, "SETU_AA_CLIENT_SECRET", "test-secret")
    monkeypatch.setattr(config, "SETU_AA_PRODUCT_INSTANCE_ID", "test-product-instance")
    monkeypatch.setattr(config, "SETU_AA_BASE_URL", "https://fiu-sandbox.example")
    monkeypatch.setattr(config, "SETU_AA_TOKEN_URL", "https://uat.example/auth/token")


def _token_response(expires_in=1800, token="tok-1"):
    return FakeResponse({"data": {"token": token, "expiresIn": expires_in}})


class TestGetAccessToken:
    def test_fetches_and_caches_token(self, monkeypatch):
        fake_client = FakeHttpClient([_token_response()])
        monkeypatch.setattr(setu_aa_client, "_client", fake_client)

        token = setu_aa_client.get_access_token()
        assert token == "tok-1"
        assert len(fake_client.calls) == 1
        assert fake_client.calls[0]["json"] == {"clientID": "test-client-id", "secret": "test-secret"}

    def test_second_call_reuses_cached_token(self, monkeypatch):
        fake_client = FakeHttpClient([_token_response()])
        monkeypatch.setattr(setu_aa_client, "_client", fake_client)

        setu_aa_client.get_access_token()
        setu_aa_client.get_access_token()
        assert len(fake_client.calls) == 1  # second call didn't touch the network

    def test_refreshes_when_within_margin_of_expiry(self, monkeypatch):
        fake_client = FakeHttpClient([_token_response(), _token_response(token="tok-2")])
        monkeypatch.setattr(setu_aa_client, "_client", fake_client)

        setu_aa_client.get_access_token()
        setu_aa_client._token_cache["expires_at"] = time.time() + setu_aa_client._TOKEN_REFRESH_MARGIN_S - 1

        token = setu_aa_client.get_access_token()
        assert token == "tok-2"
        assert len(fake_client.calls) == 2


class TestHeaders:
    def test_includes_bearer_token_and_product_instance_id(self, monkeypatch):
        fake_client = FakeHttpClient([_token_response()])
        monkeypatch.setattr(setu_aa_client, "_client", fake_client)

        headers = setu_aa_client._headers()
        assert headers["Authorization"] == "Bearer tok-1"
        assert headers["x-product-instance-id"] == "test-product-instance"


class TestMonthsAgoAndNowIso:
    def test_months_ago_caps_day_at_28(self):
        result = setu_aa_client.months_ago(4)
        assert int(result[8:10]) <= 28

    def test_months_ago_format(self):
        result = setu_aa_client.months_ago(1)
        assert result.endswith("Z")
        assert "T" in result

    def test_now_iso_is_not_capped_at_28(self):
        # now_iso() exists specifically because months_ago(0) would wrongly
        # cap today's day-of-month at 28 — assert it returns the real day.
        expected_day = datetime.now(timezone.utc).day
        result = setu_aa_client.now_iso()
        assert int(result[8:10]) == expected_day


class TestCreateConsent:
    def test_posts_expected_payload_shape(self, monkeypatch):
        fake_client = FakeHttpClient(
            [_token_response(), FakeResponse({"id": "consent-1", "url": "https://approve.example", "status": "PENDING"})]
        )
        monkeypatch.setattr(setu_aa_client, "_client", fake_client)

        result = setu_aa_client.create_consent("9999999999@setu", months=4)

        assert result == {"id": "consent-1", "url": "https://approve.example", "status": "PENDING"}
        consent_call = fake_client.calls[-1]
        assert consent_call["url"] == "https://fiu-sandbox.example/consents"
        assert consent_call["json"]["vua"] == "9999999999@setu"
        assert consent_call["json"]["consentDuration"] == {"unit": "MONTH", "value": "4"}
        assert consent_call["headers"]["Authorization"] == "Bearer tok-1"


class TestGetConsentStatus:
    def test_gets_expected_url(self, monkeypatch):
        fake_client = FakeHttpClient([_token_response(), FakeResponse({"id": "consent-1", "status": "ACTIVE"})])
        monkeypatch.setattr(setu_aa_client, "_client", fake_client)

        result = setu_aa_client.get_consent_status("consent-1")
        assert result["status"] == "ACTIVE"
        assert fake_client.calls[-1]["url"] == "https://fiu-sandbox.example/consents/consent-1"


class TestCreateDataSession:
    def test_posts_expected_payload(self, monkeypatch):
        fake_client = FakeHttpClient([_token_response(), FakeResponse({"id": "session-1"})])
        monkeypatch.setattr(setu_aa_client, "_client", fake_client)

        result = setu_aa_client.create_data_session("consent-1", "2026-04-01T00:00:00Z", "2026-08-01T00:00:00Z")
        assert result == {"id": "session-1"}
        session_call = fake_client.calls[-1]
        assert session_call["url"] == "https://fiu-sandbox.example/sessions"
        assert session_call["json"]["consentId"] == "consent-1"
        assert session_call["json"]["dataRange"] == {"from": "2026-04-01T00:00:00Z", "to": "2026-08-01T00:00:00Z"}


class TestPollAndFetchSession:
    def test_returns_immediately_on_terminal_status_top_level(self, monkeypatch):
        fake_client = FakeHttpClient([_token_response(), FakeResponse({"status": "COMPLETED", "account": {}})])
        monkeypatch.setattr(setu_aa_client, "_client", fake_client)

        result = setu_aa_client.poll_and_fetch_session("session-1")
        assert result["status"] == "COMPLETED"

    def test_returns_on_terminal_status_nested_under_data(self, monkeypatch):
        fake_client = FakeHttpClient([_token_response(), FakeResponse({"data": {"status": "PARTIAL"}})])
        monkeypatch.setattr(setu_aa_client, "_client", fake_client)

        result = setu_aa_client.poll_and_fetch_session("session-1")
        assert result["data"]["status"] == "PARTIAL"

    def test_polls_again_when_status_is_not_yet_terminal(self, monkeypatch):
        fake_client = FakeHttpClient(
            [_token_response(), FakeResponse({"status": "PENDING"}), FakeResponse({"status": "COMPLETED"})]
        )
        monkeypatch.setattr(setu_aa_client, "_client", fake_client)
        monkeypatch.setattr(setu_aa_client, "_POLL_INTERVAL_S", 0)  # don't actually sleep in a test

        result = setu_aa_client.poll_and_fetch_session("session-1")
        assert result["status"] == "COMPLETED"
        assert len(fake_client.calls) == 3  # 1 token fetch + 2 GET polls

    def test_raises_timeout_error_past_deadline(self, monkeypatch):
        fake_client = FakeHttpClient([_token_response()] + [FakeResponse({"status": "PENDING"})] * 5)
        monkeypatch.setattr(setu_aa_client, "_client", fake_client)
        monkeypatch.setattr(setu_aa_client, "_POLL_INTERVAL_S", 0)

        with pytest.raises(TimeoutError):
            setu_aa_client.poll_and_fetch_session("session-1", timeout_s=0)
