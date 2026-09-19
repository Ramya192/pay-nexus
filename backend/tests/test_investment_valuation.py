"""
Unit tests for analytics/investment_valuation.py. FD math is pure and
tested directly, no mocking needed. Mutual fund NAV lookup mocks
`httpx.get` — no real network call, matching this file's own "no LLM
call, no network" convention (this isn't an LLM call, but the same
determinism-in-CI reasoning applies).
"""

from datetime import date, timedelta

import httpx
import pytest

from analytics.investment_valuation import fd_current_value, fetch_mf_nav, mf_current_value


class TestFdCurrentValue:
    def test_zero_elapsed_time_returns_principal_unchanged(self):
        assert fd_current_value(100000, 7.0, str(date.today())) == 100000

    def test_malformed_start_date_returns_principal_unchanged(self):
        assert fd_current_value(100000, 7.0, "not-a-date") == 100000

    def test_one_year_at_seven_percent_quarterly_compounded(self):
        one_year_ago = date.today() - timedelta(days=365)
        value = fd_current_value(100000, 7.0, str(one_year_ago))
        # (1 + 0.07/4)^4 ~= 1.07186 -- real quarterly-compounding math, not a guess.
        assert 107100 < value < 107300

    def test_longer_elapsed_time_grows_more(self):
        one_year_ago = date.today() - timedelta(days=365)
        two_years_ago = date.today() - timedelta(days=730)
        one_year_value = fd_current_value(100000, 7.0, str(one_year_ago))
        two_year_value = fd_current_value(100000, 7.0, str(two_years_ago))
        assert two_year_value > one_year_value

    def test_zero_rate_never_grows(self):
        one_year_ago = date.today() - timedelta(days=365)
        assert fd_current_value(100000, 0.0, str(one_year_ago)) == pytest.approx(100000, rel=1e-6)


class TestFetchMfNav:
    def test_successful_lookup_parses_nav(self, monkeypatch):
        class FakeResponse:
            status_code = 200

            def json(self):
                return {"data": [{"date": "11-09-2026", "nav": "101.4013"}]}

        monkeypatch.setattr(httpx, "get", lambda url, timeout: FakeResponse())
        nav, error = fetch_mf_nav("119598")
        assert nav == pytest.approx(101.4013)
        assert error is None

    def test_network_error_returns_a_clear_message_not_an_exception(self, monkeypatch):
        def fake_get(url, timeout):
            raise httpx.ConnectTimeout("timed out")

        monkeypatch.setattr(httpx, "get", fake_get)
        nav, error = fetch_mf_nav("119598")
        assert nav is None
        assert error is not None

    def test_non_200_status_returns_an_error(self, monkeypatch):
        class FakeResponse:
            status_code = 500

            def json(self):
                return {}

        monkeypatch.setattr(httpx, "get", lambda url, timeout: FakeResponse())
        nav, error = fetch_mf_nav("119598")
        assert nav is None
        assert "500" in error

    def test_malformed_response_shape_returns_an_error_not_a_crash(self, monkeypatch):
        class FakeResponse:
            status_code = 200

            def json(self):
                return {"data": []}  # empty -- a real shape mfapi.in returns for an unknown scheme code

        monkeypatch.setattr(httpx, "get", lambda url, timeout: FakeResponse())
        nav, error = fetch_mf_nav("00000000")
        assert nav is None
        assert "00000000" in error


class TestMfCurrentValue:
    def test_units_times_nav(self, monkeypatch):
        class FakeResponse:
            status_code = 200

            def json(self):
                return {"data": [{"nav": "100.00"}]}

        monkeypatch.setattr(httpx, "get", lambda url, timeout: FakeResponse())
        value, error = mf_current_value("119598", 50)
        assert value == pytest.approx(5000.0)
        assert error is None

    def test_zero_units_is_a_real_input_error_not_a_zero_value(self):
        value, error = mf_current_value("119598", 0)
        assert value is None
        assert error is not None

    def test_negative_units_is_a_real_input_error(self):
        value, error = mf_current_value("119598", -5)
        assert value is None
        assert error is not None

    def test_nav_lookup_failure_propagates_as_the_valuation_error(self, monkeypatch):
        def fake_get(url, timeout):
            raise httpx.ConnectTimeout("timed out")

        monkeypatch.setattr(httpx, "get", fake_get)
        value, error = mf_current_value("119598", 50)
        assert value is None
        assert error is not None
