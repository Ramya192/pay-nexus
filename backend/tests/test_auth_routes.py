"""
POST /auth/register, POST /auth/login — including the rate limiting added
2026-09-13 after a security pass found neither route was throttled at all
(security/rate_limit.py). The `client` fixture (tests/conftest.py) resets
the limiter before each test, so these don't interfere with each other or
with every other route test's own register/login calls.
"""


class TestRegisterAndLogin:
    def test_register_then_login_succeeds(self, client):
        r = client.post(
            "/auth/register", json={"email": "a@example.com", "password": "correcthorse123"}
        )
        assert r.status_code == 201
        assert "access_token" in r.json()

        r = client.post(
            "/auth/login", json={"email": "a@example.com", "password": "correcthorse123"}
        )
        assert r.status_code == 200
        assert "access_token" in r.json()

    def test_duplicate_register_409(self, client):
        body = {"email": "dupe@example.com", "password": "correcthorse123"}
        client.post("/auth/register", json=body)
        r = client.post("/auth/register", json=body)
        assert r.status_code == 409

    def test_wrong_password_401_same_message_as_no_such_user(self, client):
        client.post(
            "/auth/register", json={"email": "b@example.com", "password": "correcthorse123"}
        )
        wrong_pw = client.post(
            "/auth/login", json={"email": "b@example.com", "password": "wrongpassword"}
        )
        no_such_user = client.post(
            "/auth/login", json={"email": "nobody@example.com", "password": "whatever123"}
        )
        assert wrong_pw.status_code == 401
        assert no_such_user.status_code == 401
        # Deliberately identical, per auth.py's own comment -- distinguishing
        # them would let an attacker enumerate registered emails.
        assert wrong_pw.json()["detail"] == no_such_user.json()["detail"]


class TestRateLimiting:
    def test_login_gets_throttled_past_its_limit(self, client):
        """/auth/login is limited to 10/minute (security/rate_limit.py,
        api/routes/auth.py). Hit it 11 times fast and confirm at least one
        429 comes back -- proves the decorator actually enforces something,
        not just that it's present in the source."""
        client.post(
            "/auth/register", json={"email": "throttle@example.com", "password": "correcthorse123"}
        )
        statuses = [
            client.post(
                "/auth/login",
                json={"email": "throttle@example.com", "password": "correcthorse123"},
            ).status_code
            for _ in range(11)
        ]
        assert 429 in statuses, f"expected a 429 somewhere in 11 rapid logins, got {statuses}"

    def test_register_gets_throttled_past_its_limit(self, client):
        """/auth/register is limited to 5/minute -- tighter than login,
        since spamming new accounts is the more expensive abuse case."""
        statuses = [
            client.post(
                "/auth/register",
                json={"email": f"spam{i}@example.com", "password": "correcthorse123"},
            ).status_code
            for i in range(6)
        ]
        assert 429 in statuses, f"expected a 429 somewhere in 6 rapid registrations, got {statuses}"

    def test_limiter_resets_between_tests(self, client):
        """Sanity check on the fixture's own limiter.reset() -- if this test
        ran right after the two throttling tests above and still got 429
        immediately, the reset isn't working."""
        r = client.post(
            "/auth/register", json={"email": "fresh@example.com", "password": "correcthorse123"}
        )
        assert r.status_code == 201
