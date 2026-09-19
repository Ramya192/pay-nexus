"""Route-level tests for api/routes/goals.py — real FastAPI request/response
cycle against an in-memory database. No LLM call anywhere in this file.
See test_budget_routes.py's module docstring for the fake-blob rationale.
"""

import base64


def _fake_blob(text: str) -> dict:
    return {"ciphertext_b64": base64.b64encode(text.encode()).decode(), "iv_b64": base64.b64encode(b"iv").decode()}


class TestGoalAuth:
    def test_list_requires_auth(self, client):
        assert client.get("/goals").status_code == 401

    def test_create_requires_auth(self, client):
        assert client.post("/goals", json=_fake_blob("x")).status_code == 401


class TestGoalCrud:
    def test_list_empty_initially(self, client, auth_headers):
        response = client.get("/goals", headers=auth_headers)
        assert response.status_code == 200
        assert response.json() == []

    def test_create_then_list(self, client, auth_headers):
        blob = _fake_blob('{"name": "Goa Trip"}')
        create_response = client.post("/goals", json=blob, headers=auth_headers)
        assert create_response.status_code == 201
        goal_id = create_response.json()["id"]

        list_response = client.get("/goals", headers=auth_headers)
        rows = list_response.json()
        assert len(rows) == 1
        assert rows[0]["id"] == goal_id
        assert rows[0]["ciphertext_b64"] == blob["ciphertext_b64"]

    def test_create_twice_produces_two_distinct_goals(self, client, auth_headers):
        """Unlike Budget/FinancialProfile, Goal has no dedup key — every
        POST is a new row, even with identical-looking content."""
        client.post("/goals", json=_fake_blob("goal 1"), headers=auth_headers)
        client.post("/goals", json=_fake_blob("goal 1"), headers=auth_headers)  # same content on purpose
        response = client.get("/goals", headers=auth_headers)
        assert len(response.json()) == 2

    def test_update_replaces_ciphertext(self, client, auth_headers):
        create_response = client.post("/goals", json=_fake_blob("original"), headers=auth_headers)
        goal_id = create_response.json()["id"]

        new_blob = _fake_blob("updated with new savedAmount")
        update_response = client.put(f"/goals/{goal_id}", json=new_blob, headers=auth_headers)
        assert update_response.status_code == 200

        response = client.get("/goals", headers=auth_headers)
        assert response.json()[0]["ciphertext_b64"] == new_blob["ciphertext_b64"]

    def test_update_nonexistent_goal_404(self, client, auth_headers):
        response = client.put("/goals/not-a-real-id", json=_fake_blob("x"), headers=auth_headers)
        assert response.status_code == 404

    def test_delete_removes_goal(self, client, auth_headers):
        create_response = client.post("/goals", json=_fake_blob("to delete"), headers=auth_headers)
        goal_id = create_response.json()["id"]

        delete_response = client.delete(f"/goals/{goal_id}", headers=auth_headers)
        assert delete_response.status_code == 204

        response = client.get("/goals", headers=auth_headers)
        assert response.json() == []

    def test_delete_nonexistent_goal_404(self, client, auth_headers):
        response = client.delete("/goals/not-a-real-id", headers=auth_headers)
        assert response.status_code == 404


class TestGoalIsolation:
    def test_one_users_goals_invisible_to_another(self, client, make_auth_headers):
        user_a = make_auth_headers()
        user_b = make_auth_headers()

        client.post("/goals", json=_fake_blob("user a's goal"), headers=user_a)

        response = client.get("/goals", headers=user_b)
        assert response.json() == []

    def test_cannot_update_another_users_goal(self, client, make_auth_headers):
        user_a = make_auth_headers()
        user_b = make_auth_headers()

        create_response = client.post("/goals", json=_fake_blob("user a's goal"), headers=user_a)
        goal_id = create_response.json()["id"]

        response = client.put(f"/goals/{goal_id}", json=_fake_blob("hijacked"), headers=user_b)
        assert response.status_code == 404

    def test_cannot_delete_another_users_goal(self, client, make_auth_headers):
        user_a = make_auth_headers()
        user_b = make_auth_headers()

        create_response = client.post("/goals", json=_fake_blob("user a's goal"), headers=user_a)
        goal_id = create_response.json()["id"]

        response = client.delete(f"/goals/{goal_id}", headers=user_b)
        assert response.status_code == 404
        # Still there from user A's side — the failed cross-user delete didn't remove it.
        assert len(client.get("/goals", headers=user_a).json()) == 1


class TestGoalValuation:
    """POST /goals/valuation — stateless, no persistence, so no client/db
    interaction beyond auth. Real network call (mfapi.in) mocked via
    monkeypatch, matching test_investment_valuation.py's own approach."""

    def test_fd_valuation_is_pure_math_no_network(self, client, auth_headers):
        body = [
            {
                "goal_id": "g1",
                "instrument_type": "fd",
                "fd_principal": 100000,
                "fd_annual_rate": 7.0,
                "fd_start_date": "2020-01-01",
            }
        ]
        response = client.post("/goals/valuation", json=body, headers=auth_headers)
        assert response.status_code == 200
        result = response.json()[0]
        assert result["goal_id"] == "g1"
        assert result["current_value"] > 100000
        assert result["error"] is None

    def test_mutual_fund_valuation_calls_the_price_service(self, client, auth_headers, monkeypatch):
        import httpx

        class FakeResponse:
            status_code = 200

            def json(self):
                return {"data": [{"nav": "100.00"}]}

        monkeypatch.setattr(httpx, "get", lambda url, timeout: FakeResponse())
        body = [{"goal_id": "g2", "instrument_type": "mutual_fund", "mf_scheme_code": "119598", "mf_units_held": 50}]
        response = client.post("/goals/valuation", json=body, headers=auth_headers)
        result = response.json()[0]
        assert result["current_value"] == 5000.0
        assert result["error"] is None

    def test_one_bad_entry_does_not_fail_the_others(self, client, auth_headers):
        body = [
            {"goal_id": "good", "instrument_type": "fd", "fd_principal": 50000, "fd_annual_rate": 6.0, "fd_start_date": "2021-01-01"},
            {"goal_id": "bad", "instrument_type": "fd"},  # missing required fields
        ]
        response = client.post("/goals/valuation", json=body, headers=auth_headers)
        results = {r["goal_id"]: r for r in response.json()}
        assert results["good"]["error"] is None
        assert results["good"]["current_value"] > 50000
        assert results["bad"]["error"] is not None
        assert results["bad"]["current_value"] is None

    def test_unknown_instrument_type_returns_an_error(self, client, auth_headers):
        body = [{"goal_id": "g3", "instrument_type": "crypto"}]
        response = client.post("/goals/valuation", json=body, headers=auth_headers)
        result = response.json()[0]
        assert result["current_value"] is None
        assert "crypto" in result["error"]

    def test_requires_auth(self, client):
        response = client.post("/goals/valuation", json=[])
        assert response.status_code == 401
