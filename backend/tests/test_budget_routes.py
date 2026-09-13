"""Route-level tests for api/routes/budget.py — real FastAPI request/response
cycle against an in-memory database (tests/conftest.py's `client` fixture),
not just the Python function in isolation. No LLM call anywhere in this
file. `ciphertext_b64`/`iv_b64` are fake base64 blobs, not real AES-GCM
output — these routes never decrypt, only store and return ciphertext
as-is, so a route test doesn't need real client-side crypto to exercise it.
"""

import base64


def _fake_blob(text: str) -> dict:
    return {"ciphertext_b64": base64.b64encode(text.encode()).decode(), "iv_b64": base64.b64encode(b"iv").decode()}


class TestBudgetAuth:
    def test_get_budget_requires_auth(self, client):
        assert client.get("/budget").status_code == 401

    def test_put_budget_requires_auth(self, client):
        assert client.put("/budget", json=_fake_blob("x")).status_code == 401


class TestBudgetCrud:
    def test_get_budget_404_when_none_saved(self, client, auth_headers):
        response = client.get("/budget", headers=auth_headers)
        assert response.status_code == 404

    def test_put_then_get_roundtrips_ciphertext(self, client, auth_headers):
        blob = _fake_blob('{"Rent": 18000}')
        put_response = client.put("/budget", json=blob, headers=auth_headers)
        assert put_response.status_code == 200
        assert "updated_at" in put_response.json()

        get_response = client.get("/budget", headers=auth_headers)
        assert get_response.status_code == 200
        assert get_response.json()["ciphertext_b64"] == blob["ciphertext_b64"]

    def test_put_twice_upserts_not_duplicates(self, client, auth_headers):
        client.put("/budget", json=_fake_blob("first"), headers=auth_headers)
        client.put("/budget", json=_fake_blob("second"), headers=auth_headers)

        response = client.get("/budget", headers=auth_headers)
        assert response.json()["ciphertext_b64"] == _fake_blob("second")["ciphertext_b64"]


class TestBudgetIsolation:
    def test_one_users_budget_invisible_to_another(self, client, make_auth_headers):
        user_a = make_auth_headers()
        user_b = make_auth_headers()

        client.put("/budget", json=_fake_blob("user a's budget"), headers=user_a)

        response = client.get("/budget", headers=user_b)
        assert response.status_code == 404


class TestSuggestedBudget:
    def test_requires_auth(self, client):
        assert client.get("/budget/suggested").status_code == 401

    def test_defaults_to_baseline_bracket_with_no_income_given(self, client, auth_headers):
        response = client.get("/budget/suggested", headers=auth_headers)
        assert response.status_code == 200
        body = response.json()
        assert body["salary_bracket"] == "60k-100k"
        assert body["budgets"]["Rent"] == 18000

    def test_scales_with_monthly_income(self, client, auth_headers):
        response = client.get("/budget/suggested", params={"monthly_income": 20000}, headers=auth_headers)
        body = response.json()
        assert body["salary_bracket"] == "Below 30k"
        assert body["budgets"]["Rent"] == 18000 * 0.4
