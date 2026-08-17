"""Route-level tests for api/routes/statement.py — real FastAPI request/
response cycle against an in-memory database. The CSV parse path needs no
LLM call (categorization/rules.py's keyword rules cover every merchant used
below) so it's a free, always-on test; the PDF parse path needs a real
gpt-4o-mini call and is a separate, `integration`-marked test class. See
test_budget_routes.py's module docstring for the fake-blob rationale used
in the save/list/delete tests below.
"""

import base64

import pytest


def _fake_blob(text: str) -> dict:
    return {"ciphertext_b64": base64.b64encode(text.encode()).decode(), "iv_b64": base64.b64encode(b"iv").decode()}


def _fake_hash(label: str) -> str:
    """Stands in for utils/contentHash.ts's real SHA-256 fingerprint — a
    route test only needs two calls to be equal or different on purpose,
    not an actual hash of real transaction content."""
    return f"content-hash-{label}"


_VALID_CSV = "Date,Description,Amount\n2026-07-01,SALARY CREDIT,75000\n2026-07-02,SWIGGY ORDER,-500\n"


class TestStatementParseAuth:
    def test_parse_requires_auth(self, client):
        body = {"text": _VALID_CSV, "source_account": "HDFC", "format": "csv"}
        assert client.post("/statement/parse", json=body).status_code == 401


class TestStatementParseCsv:
    def test_valid_csv_parsed_and_categorized_by_rules_alone(self, client, auth_headers):
        body = {"text": _VALID_CSV, "source_account": "HDFC Checking", "format": "csv"}
        response = client.post("/statement/parse", json=body, headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["skipped_row_count"] == 0
        assert len(data["transactions"]) == 2
        by_desc = {t["description"]: t for t in data["transactions"]}
        assert by_desc["SALARY CREDIT"]["category"] == "Income"
        assert by_desc["SALARY CREDIT"]["category_source"] == "rule"
        assert by_desc["SWIGGY ORDER"]["category"] == "Food & Dining"
        assert by_desc["SWIGGY ORDER"]["amount"] == -500

    def test_empty_text_400(self, client, auth_headers):
        body = {"text": "   ", "source_account": "HDFC", "format": "csv"}
        response = client.post("/statement/parse", json=body, headers=auth_headers)
        assert response.status_code == 400

    def test_unrecognized_headers_400(self, client, auth_headers):
        body = {"text": "Col A,Col B\nx,y\n", "source_account": "HDFC", "format": "csv"}
        response = client.post("/statement/parse", json=body, headers=auth_headers)
        assert response.status_code == 400

    def test_malformed_row_skipped_not_dropped_silently(self, client, auth_headers):
        text = _VALID_CSV + "not-a-date,BAD ROW,-100\n"
        body = {"text": text, "source_account": "HDFC", "format": "csv"}
        response = client.post("/statement/parse", json=body, headers=auth_headers)
        data = response.json()
        assert data["skipped_row_count"] == 1
        assert len(data["transactions"]) == 2  # the two good rows still came through

    def test_nothing_persisted_by_parse_alone(self, client, auth_headers):
        body = {"text": _VALID_CSV, "source_account": "HDFC Checking", "format": "csv"}
        client.post("/statement/parse", json=body, headers=auth_headers)
        assert client.get("/statement/list", headers=auth_headers).json() == []


@pytest.mark.integration
class TestStatementParsePdf:
    def test_pdf_text_structured_by_llm(self, client, auth_headers):
        text = (
            "Sunrise National Bank Statement\n"
            "01/07/2026 SALARY CREDIT - ACME CORP 75000.00\n"
            "02/07/2026 SWIGGY ORDER #481 500.00\n"
        )
        body = {"text": text, "source_account": "HDFC Checking", "format": "pdf"}
        response = client.post("/statement/parse", json=body, headers=auth_headers)
        assert response.status_code == 200
        assert len(response.json()["transactions"]) >= 1


class TestStatementSaveListDelete:
    def test_save_then_list(self, client, auth_headers):
        body = {
            "source_account": "HDFC Checking",
            "period_label": "2026-07",
            "content_hash": _fake_hash("jul"),
            **_fake_blob("[]"),
        }
        save_response = client.post("/statement/save", json=body, headers=auth_headers)
        assert save_response.status_code == 201
        assert save_response.json()["period_label"] == "2026-07"

        list_response = client.get("/statement/list", headers=auth_headers)
        rows = list_response.json()
        assert len(rows) == 1
        assert rows[0]["source_account"] == "HDFC Checking"

    def test_duplicate_account_and_period_409(self, client, auth_headers):
        body = {
            "source_account": "HDFC Checking",
            "period_label": "2026-07",
            "content_hash": _fake_hash("jul"),
            **_fake_blob("[]"),
        }
        client.post("/statement/save", json=body, headers=auth_headers)
        response = client.post("/statement/save", json=body, headers=auth_headers)
        assert response.status_code == 409

    def test_same_account_different_period_not_a_duplicate(self, client, auth_headers):
        client.post(
            "/statement/save",
            json={
                "source_account": "HDFC Checking",
                "period_label": "2026-07",
                "content_hash": _fake_hash("jul"),
                **_fake_blob("[]"),
            },
            headers=auth_headers,
        )
        response = client.post(
            "/statement/save",
            json={
                "source_account": "HDFC Checking",
                "period_label": "2026-08",
                "content_hash": _fake_hash("aug"),
                **_fake_blob("[]"),
            },
            headers=auth_headers,
        )
        assert response.status_code == 201

    def test_delete_removes_statement(self, client, auth_headers):
        save_response = client.post(
            "/statement/save",
            json={
                "source_account": "HDFC Checking",
                "period_label": "2026-07",
                "content_hash": _fake_hash("jul"),
                **_fake_blob("[]"),
            },
            headers=auth_headers,
        )
        statement_id = save_response.json()["id"]

        delete_response = client.delete(f"/statement/{statement_id}", headers=auth_headers)
        assert delete_response.status_code == 204
        assert client.get("/statement/list", headers=auth_headers).json() == []

    def test_delete_nonexistent_statement_404(self, client, auth_headers):
        assert client.delete("/statement/not-a-real-id", headers=auth_headers).status_code == 404


class TestStatementContentHashDuplicate:
    """The gap found in manual testing: the same real statement re-saved
    under a different account name previously sailed through as 'new'
    because the only duplicate check compared source_account/period_label,
    neither of which had changed by design (a user renaming the account)."""

    def test_same_content_different_account_name_409(self, client, auth_headers):
        client.post(
            "/statement/save",
            json={
                "source_account": "HDFC Checking",
                "period_label": "2026-07",
                "content_hash": _fake_hash("same-statement"),
                **_fake_blob("[]"),
            },
            headers=auth_headers,
        )
        response = client.post(
            "/statement/save",
            json={
                "source_account": "HDFC Checking1",
                "period_label": "2026-07",
                "content_hash": _fake_hash("same-statement"),
                **_fake_blob("[]"),
            },
            headers=auth_headers,
        )
        assert response.status_code == 409
        assert "HDFC Checking" in response.json()["detail"]

    def test_same_content_different_period_label_409(self, client, auth_headers):
        """Content hash alone is enough to flag it — even if the period
        label also differs (e.g. a re-upload where the user mistyped a
        different range this time)."""
        client.post(
            "/statement/save",
            json={
                "source_account": "HDFC Checking",
                "period_label": "2026-07",
                "content_hash": _fake_hash("same-statement"),
                **_fake_blob("[]"),
            },
            headers=auth_headers,
        )
        response = client.post(
            "/statement/save",
            json={
                "source_account": "HDFC Checking",
                "period_label": "2026-06 to 2026-07",
                "content_hash": _fake_hash("same-statement"),
                **_fake_blob("[]"),
            },
            headers=auth_headers,
        )
        assert response.status_code == 409

    def test_different_content_same_account_and_overlapping_hash_prefix_not_flagged(self, client, auth_headers):
        """Sanity check that the hash comparison is exact-match, not a
        prefix/substring check — two genuinely different statements with
        similar-looking hashes must both save."""
        client.post(
            "/statement/save",
            json={
                "source_account": "HDFC Checking",
                "period_label": "2026-07",
                "content_hash": "abc123",
                **_fake_blob("[]"),
            },
            headers=auth_headers,
        )
        response = client.post(
            "/statement/save",
            json={
                "source_account": "ICICI Savings",
                "period_label": "2026-07",
                "content_hash": "abc1234",
                **_fake_blob("[]"),
            },
            headers=auth_headers,
        )
        assert response.status_code == 201

    def test_content_hash_duplicate_check_is_per_user(self, client, make_auth_headers):
        """Two different users legitimately holding the same real
        statement (e.g. a shared household account each uploads) must not
        collide with each other."""
        user_a = make_auth_headers()
        user_b = make_auth_headers()
        body = {
            "source_account": "HDFC Checking",
            "period_label": "2026-07",
            "content_hash": _fake_hash("shared"),
            **_fake_blob("[]"),
        }
        assert client.post("/statement/save", json=body, headers=user_a).status_code == 201
        assert client.post("/statement/save", json=body, headers=user_b).status_code == 201

    def test_content_hash_missing_from_request_422(self, client, auth_headers):
        body = {"source_account": "HDFC Checking", "period_label": "2026-07", **_fake_blob("[]")}
        response = client.post("/statement/save", json=body, headers=auth_headers)
        assert response.status_code == 422


class TestStatementUpdate:
    def test_update_requires_auth(self, client):
        assert client.put("/statement/some-id", json=_fake_blob("x")).status_code == 401

    def test_update_overwrites_ciphertext(self, client, auth_headers):
        save_response = client.post(
            "/statement/save",
            json={
                "source_account": "HDFC Checking",
                "period_label": "2026-07",
                "content_hash": _fake_hash("orig"),
                **_fake_blob("original"),
            },
            headers=auth_headers,
        )
        statement_id = save_response.json()["id"]

        update_response = client.put(f"/statement/{statement_id}", json=_fake_blob("corrected"), headers=auth_headers)
        assert update_response.status_code == 200
        assert update_response.json()["id"] == statement_id

        list_response = client.get("/statement/list", headers=auth_headers)
        row = next(r for r in list_response.json() if r["id"] == statement_id)
        assert row["ciphertext_b64"] == _fake_blob("corrected")["ciphertext_b64"]

    def test_update_preserves_source_account_and_period(self, client, auth_headers):
        save_response = client.post(
            "/statement/save",
            json={
                "source_account": "HDFC Checking",
                "period_label": "2026-07",
                "content_hash": _fake_hash("orig"),
                **_fake_blob("original"),
            },
            headers=auth_headers,
        )
        statement_id = save_response.json()["id"]

        update_response = client.put(f"/statement/{statement_id}", json=_fake_blob("corrected"), headers=auth_headers)
        body = update_response.json()
        assert body["source_account"] == "HDFC Checking"
        assert body["period_label"] == "2026-07"

    def test_update_nonexistent_statement_404(self, client, auth_headers):
        response = client.put("/statement/not-a-real-id", json=_fake_blob("x"), headers=auth_headers)
        assert response.status_code == 404

    def test_update_isolated_between_users(self, client, make_auth_headers):
        user_a = make_auth_headers()
        user_b = make_auth_headers()
        save_response = client.post(
            "/statement/save",
            json={
                "source_account": "HDFC Checking",
                "period_label": "2026-07",
                "content_hash": _fake_hash("orig"),
                **_fake_blob("original"),
            },
            headers=user_a,
        )
        statement_id = save_response.json()["id"]

        response = client.put(f"/statement/{statement_id}", json=_fake_blob("hijacked"), headers=user_b)
        assert response.status_code == 404

        # Confirm user A's data was untouched by the rejected attempt.
        list_response = client.get("/statement/list", headers=user_a)
        row = next(r for r in list_response.json() if r["id"] == statement_id)
        assert row["ciphertext_b64"] == _fake_blob("original")["ciphertext_b64"]


class TestStatementIsolation:
    def test_one_users_statements_invisible_to_another(self, client, make_auth_headers):
        user_a = make_auth_headers()
        user_b = make_auth_headers()

        client.post(
            "/statement/save",
            json={
                "source_account": "HDFC Checking",
                "period_label": "2026-07",
                "content_hash": _fake_hash("jul"),
                **_fake_blob("[]"),
            },
            headers=user_a,
        )
        assert client.get("/statement/list", headers=user_b).json() == []

    def test_duplicate_check_is_per_user_not_global(self, client, make_auth_headers):
        """Same (source_account, period_label) pair for two DIFFERENT users
        must not collide — the dedup check is scoped by user_id too, not
        just the two plaintext fields."""
        user_a = make_auth_headers()
        user_b = make_auth_headers()
        body = {
            "source_account": "HDFC Checking",
            "period_label": "2026-07",
            "content_hash": _fake_hash("jul"),
            **_fake_blob("[]"),
        }

        assert client.post("/statement/save", json=body, headers=user_a).status_code == 201
        assert client.post("/statement/save", json=body, headers=user_b).status_code == 201
