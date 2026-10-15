import unittest
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from breeze.identity.service import LOGIN_FAILED
from helpers import PASSWORD, authed_client, build_app


class FakeClock:
    def __init__(self):
        self.value = datetime(2026, 10, 13, 10, 0, 0, tzinfo=timezone(timedelta(hours=8)))

    def now(self) -> datetime:
        return self.value

    def advance(self, **delta) -> None:
        self.value += timedelta(**delta)


class AuthFlowTest(unittest.TestCase):
    def test_unique_account_password_rules_and_generic_errors(self):
        with TemporaryDirectory() as temporary:
            _settings, auth, _service, _root, app = build_app(temporary)
            client = TestClient(app)

            weak = client.post(
                "/api/auth/register",
                json={"username": "alice", "password": "short1"},
            )
            self.assertEqual(weak.status_code, 400)
            self.assertIn("12", weak.json()["detail"])

            created = client.post(
                "/api/auth/register",
                json={"username": "alice", "password": PASSWORD},
            )
            self.assertEqual(created.status_code, 200, created.text)
            self.assertEqual(created.json()["username"], "alice")

            duplicate = client.post(
                "/api/auth/register",
                json={"username": "Alice", "password": PASSWORD},
            )
            self.assertEqual(duplicate.status_code, 409)

            guest = TestClient(app)
            unknown = guest.post(
                "/api/auth/login",
                json={"username": "nobody", "password": PASSWORD},
            )
            self.assertEqual(unknown.status_code, 401)
            self.assertEqual(unknown.json()["detail"], LOGIN_FAILED)

            wrong = guest.post(
                "/api/auth/login",
                json={"username": "alice", "password": "WrongPassword1"},
            )
            self.assertEqual(wrong.status_code, 401)
            self.assertEqual(wrong.json()["detail"], LOGIN_FAILED)
            self.assertNotEqual(wrong.json()["detail"], "帳號不存在")
            self.assertNotEqual(wrong.json()["detail"], "密碼錯誤")

            actions = {event.action for event in auth.recent_logs()}
            self.assertIn("login_success", actions)
            self.assertIn("login_failure", actions)
            self.assertIn("account_created", actions)
            event = auth.recent_logs()[0]
            self.assertTrue(event.time)
            self.assertTrue(event.time_utc)
            self.assertTrue(event.ip)
            self.assertTrue(event.account)
            self.assertTrue(event.action)

    def test_lockout_after_five_failures(self):
        clock = FakeClock()
        with TemporaryDirectory() as temporary:
            _settings, auth, _service, _root, app = build_app(temporary, clock=clock)
            owner = authed_client(app, "alice")
            owner.post("/api/auth/logout")
            attacker = TestClient(app)
            for _ in range(5):
                failed = attacker.post(
                    "/api/auth/login",
                    json={"username": "alice", "password": "WrongPassword1"},
                )
                self.assertEqual(failed.status_code, 401)
                self.assertEqual(failed.json()["detail"], LOGIN_FAILED)

            locked = attacker.post(
                "/api/auth/login",
                json={"username": "alice", "password": PASSWORD},
            )
            self.assertEqual(locked.status_code, 423)
            self.assertIn("15 分鐘", locked.json()["detail"])
            self.assertEqual(locked.json()["detail"], unknown_lock(attacker))
            self.assertIn("lockout", {event.action for event in auth.recent_logs()})

            clock.advance(minutes=14)
            still = attacker.post(
                "/api/auth/login",
                json={"username": "alice", "password": PASSWORD},
            )
            self.assertEqual(still.status_code, 423)

            clock.advance(minutes=2)
            recovered = attacker.post(
                "/api/auth/login",
                json={"username": "alice", "password": PASSWORD},
            )
            self.assertEqual(recovered.status_code, 200, recovered.text)

    def test_second_login_replaces_session(self):
        with TemporaryDirectory() as temporary:
            _settings, _auth, _service, _root, app = build_app(temporary)
            first = authed_client(app, "alice")
            token = first.cookies.get("breeze_session")
            second = TestClient(app)
            logged = second.post(
                "/api/auth/login",
                json={"username": "alice", "password": PASSWORD},
            )
            self.assertEqual(logged.status_code, 200)
            stale = TestClient(app)
            stale.cookies.set("breeze_session", token)
            self.assertEqual(stale.get("/api/auth/me").status_code, 401)
            self.assertEqual(second.get("/api/auth/me").status_code, 200)

    def test_unauthenticated_api_is_rejected(self):
        with TemporaryDirectory() as temporary:
            _settings, _auth, _service, _root, app = build_app(temporary)
            client = TestClient(app)
            self.assertEqual(client.get("/api/transcripts").status_code, 401)
            self.assertEqual(client.get("/api/auth/me").status_code, 401)
            login_page = client.get("/login")
            self.assertEqual(login_page.status_code, 200)
            self.assertIn('id="app"', login_page.text)
            self.assertEqual(client.get("/background1.jpg").status_code, 200)
            register_page = client.get("/register")
            self.assertEqual(register_page.status_code, 200)
            self.assertIn('id="app"', register_page.text)

    def test_permission_change_is_audited(self):
        with TemporaryDirectory() as temporary:
            _settings, auth, _service, _root, app = build_app(temporary)
            alice_client = authed_client(app, "alice")
            authed_client(app, "bob")
            alice = auth.user_for_token(alice_client.cookies.get("breeze_session"))
            auth._store.set_role(alice.id, "admin")
            alice = auth.user_for_token(alice_client.cookies.get("breeze_session"))
            updated = auth.change_role(alice, "bob", "admin", "127.0.0.1")
            self.assertEqual(updated.role, "admin")
            events = [item for item in auth.recent_logs() if item.action == "permission_change"]
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].account, "alice")
            self.assertIn("target=bob", events[0].detail)


def unknown_lock(client: TestClient) -> str:
    response = client.post(
        "/api/auth/login",
        json={"username": "does_not_exist", "password": PASSWORD},
    )
    return response.json()["detail"]


if __name__ == "__main__":
    unittest.main()
