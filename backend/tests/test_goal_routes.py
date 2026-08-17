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
