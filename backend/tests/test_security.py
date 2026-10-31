from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import audit, config, security, uploads
from app.deps import get_current_user
from app.repositories import library, meetings, terms
from app.routers import auth, glossary, meetings as meetings_router
from app.security import hash_token

PASSWORD = "Correcthorse1"
WRONG = "Wronghorse99"


@contextmanager
def _conn():
    yield object()


def _load_create_user():
    spec = importlib.util.spec_from_file_location("create_user_script", ROOT / "scripts" / "create_user.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _audit_text(root: Path) -> str:
    parts = []
    for path in root.rglob("*.jsonl"):
        parts.append(path.read_text(encoding="utf-8"))
    return "\n".join(parts)


def _events(root: Path) -> list[dict]:
    rows = []
    for path in root.rglob("*.jsonl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("{"):
                rows.append(json.loads(line))
    return rows


class SecurityRulesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self._old_audit = os.environ.get("AUDIT_LOG_DIR")
        os.environ["AUDIT_LOG_DIR"] = str(self.root)

    def tearDown(self):
        if self._old_audit is None:
            os.environ.pop("AUDIT_LOG_DIR", None)
        else:
            os.environ["AUDIT_LOG_DIR"] = self._old_audit
        self.tmp.cleanup()

    def test_username_and_password_rules(self):
        self.assertTrue(security.validate_username("abc"))
        self.assertTrue(security.validate_username("A_1"))
        self.assertTrue(security.validate_username("a" * 32))
        self.assertFalse(security.validate_username("ab"))
        self.assertFalse(security.validate_username("a" * 33))
        self.assertFalse(security.validate_username("a-b"))
        self.assertFalse(security.validate_username("中文帳號"))
        self.assertTrue(security.validate_password("abcdef123456"))
        self.assertFalse(security.validate_password("abcdef12345"))
        self.assertFalse(security.validate_password("abcdefghijkl"))
        self.assertFalse(security.validate_password("123456789012"))
        self.assertEqual(security.registration_error("ab", PASSWORD), "username")
        self.assertEqual(security.registration_error("alice", "short"), "password")
        self.assertIsNone(security.registration_error("alice", PASSWORD))

    def test_pbkdf2_format_and_constant_time_compare(self):
        stored = security.hash_password(PASSWORD)
        algo, rounds, salt, digest = stored.split("$")
        self.assertEqual(algo, "pbkdf2_sha256")
        self.assertEqual(rounds, "260000")
        self.assertTrue(salt)
        self.assertTrue(digest)
        self.assertNotIn(PASSWORD, stored)
        self.assertTrue(security.verify_password(PASSWORD, stored))
        self.assertFalse(security.verify_password(WRONG, stored))
        self.assertFalse(security.verify_password(PASSWORD, "scrypt$16384$8$1$aa$bb"))
        self.assertTrue(security.verify_password(PASSWORD, _legacy_scrypt(PASSWORD)))
        self.assertFalse(security.verify_password(WRONG, _legacy_scrypt(PASSWORD)))
        with patch("app.security.passwords.hmac.compare_digest", return_value=True) as compared:
            security.verify_password(PASSWORD, stored)
        compared.assert_called()

    def test_missing_user_verifies_dummy_and_matches_wrong_password(self):
        state = self._auth_state()
        seen = []
        real = security.verify_password

        def spy(password, stored):
            seen.append(stored)
            return real(password, stored)

        client = self._auth_client(state, verify=spy)
        missing = client.post("/api/v1/auth/login", json={"username": "ghost", "password": PASSWORD})
        wrong = client.post("/api/v1/auth/login", json={"username": "alice", "password": WRONG})
        self.assertEqual(seen[0], security.DUMMY_PASSWORD_HASH)
        self.assertIn(state["user"]["password_hash"], seen)
        self.assertEqual(missing.status_code, wrong.status_code)
        self.assertEqual(missing.json(), wrong.json())
        self.assertEqual(missing.json()["detail"]["message"], "帳號或密碼錯誤")
        self.assertNotIn(PASSWORD, missing.text)
        self.assertNotIn(WRONG, _audit_text(self.root))
        for event in _events(self.root):
            self.assertEqual(event["action"], "登入失敗")
            self._assert_audit_fields(event)

    def test_cookie_session_hash_and_default_ttl(self):
        state = self._auth_state()
        client = self._auth_client(state)
        res = client.post("/api/v1/auth/login", json={"username": "alice", "password": PASSWORD})
        self.assertEqual(res.status_code, 200)
        token = res.json()["access_token"]
        header = res.headers["set-cookie"].lower()
        self.assertIn("httponly", header)
        self.assertIn("samesite=lax", header)
        self.assertIn("path=/", header)
        self.assertEqual(res.json()["expires_in"], config.SESSION_TTL_SECONDS)
        stored_hash, stored_user, ttl = state["sessions"][-1]
        self.assertEqual(stored_hash, hash_token(token))
        self.assertNotEqual(stored_hash, token)
        self.assertEqual(len(stored_hash), 64)
        self.assertEqual(ttl, config.SESSION_TTL_SECONDS)
        self.assertNotIn(token, _audit_text(self.root))
        me = client.get("/api/v1/auth/me")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["username"], "alice")
        out = client.post("/api/v1/auth/logout")
        self.assertEqual(out.status_code, 204)
        cleared = out.headers["set-cookie"].lower()
        self.assertIn("session=", cleared)
        self.assertIn("path=/", cleared)
        actions = [event["action"] for event in _events(self.root)]
        self.assertIn("登入成功", actions)
        self.assertIn("登出", actions)
        for event in _events(self.root):
            self._assert_audit_fields(event)

    def test_fifth_failure_locks_for_15_minutes(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        count, until, locked = 0, None, False
        for _ in range(4):
            count, until, locked = security.next_failure(count, until, now)
            self.assertFalse(locked)
            self.assertIsNone(until)
        count, until, locked = security.next_failure(count, until, now)
        self.assertTrue(locked)
        self.assertEqual(until - now, timedelta(minutes=15))
        self.assertTrue(security.lock_is_active(until, now + timedelta(minutes=14)))
        self.assertFalse(security.lock_is_active(until, now + timedelta(minutes=15)))

        state = self._auth_state()
        client = self._auth_client(state)
        for _ in range(4):
            res = client.post("/api/v1/auth/login", json={"username": "alice", "password": WRONG})
            self.assertEqual(res.status_code, 401)
            self.assertEqual(res.json()["detail"]["message"], "帳號或密碼錯誤")
        fifth = client.post("/api/v1/auth/login", json={"username": "alice", "password": WRONG})
        self.assertEqual(fifth.status_code, 401)
        self.assertEqual(fifth.json()["detail"]["message"], "已達 5 次上限，請 15 分鐘後再試")
        self.assertTrue(state["lock"]["locked_until"] > datetime.now(timezone.utc) + timedelta(minutes=14))
        blocked = client.post("/api/v1/auth/login", json={"username": "alice", "password": PASSWORD})
        self.assertEqual(blocked.status_code, 401)
        self.assertEqual(blocked.json()["detail"]["message"], "已達 5 次上限，請 15 分鐘後再試")
        self.assertEqual(state["sessions"], [])
        actions = [event["action"] for event in _events(self.root)]
        self.assertEqual(actions[:4], ["登入失敗"] * 4)
        self.assertEqual(actions[4], "鎖定")
        self.assertEqual(actions[5], "鎖定")
        for event in _events(self.root):
            self._assert_audit_fields(event)
        self.assertNotIn(PASSWORD, _audit_text(self.root))
        self.assertNotIn(WRONG, _audit_text(self.root))

    def test_registration_audit(self):
        mod = _load_create_user()
        with patch.object(sys, "argv", ["create_user.py", "x", "--password", PASSWORD]):
            self.assertEqual(mod.main(), 1)
        with patch.object(sys, "argv", ["create_user.py", "alice", "--password", "short"]):
            self.assertEqual(mod.main(), 1)
        created = {}

        def create_user(conn, username, password_hash):
            created["row"] = {"id": uuid.uuid4(), "username": username, "password_hash": password_hash}
            return created["row"]

        with patch.object(mod, "get_conn", _conn), patch.object(mod.users, "get_by_username", lambda conn, name: None), \
                patch.object(mod.users, "create_user", create_user), \
                patch.object(sys, "argv", ["create_user.py", "alice", "--password", PASSWORD]):
            self.assertEqual(mod.main(), 0)
        self.assertTrue(created["row"]["password_hash"].startswith("pbkdf2_sha256$260000$"))
        self.assertNotIn(PASSWORD, created["row"]["password_hash"])
        actions = [event["action"] for event in _events(self.root)]
        self.assertEqual(actions[:2], ["註冊被拒", "註冊被拒"])
        self.assertIn("建立帳號", actions)
        for event in _events(self.root):
            self._assert_audit_fields(event)
        self.assertNotIn(PASSWORD, _audit_text(self.root))
        self.assertNotIn("short", _audit_text(self.root))
        for path in self.root.iterdir():
            self.assertRegex(path.name, r"^[0-9a-f]{32}$")

    def test_register_endpoint_session_and_exists_message(self):
        state = self._auth_state()
        client = self._auth_client(state)
        bad_name = client.post("/api/v1/auth/register", json={"username": "ab", "password": PASSWORD})
        bad_pw = client.post("/api/v1/auth/register", json={"username": "alice", "password": "short"})
        exists = client.post("/api/v1/auth/register", json={"username": "alice", "password": PASSWORD})
        race = client.post("/api/v1/auth/register", json={"username": "taken", "password": PASSWORD})
        self.assertEqual(bad_name.status_code, 422)
        self.assertEqual(bad_name.json()["detail"]["message"], "帳號只允許 3 到 32 碼的英數字或底線")
        self.assertEqual(bad_pw.status_code, 422)
        self.assertEqual(bad_pw.json()["detail"]["message"], "密碼至少 12 碼，而且要同時含英文字母和數字")
        self.assertEqual(exists.status_code, 409)
        self.assertEqual(exists.json()["detail"]["message"], "這個帳號已經有人使用")
        self.assertEqual(race.status_code, 409)
        self.assertNotIn("UniqueViolation", race.text)
        self.assertNotIn(PASSWORD, exists.text + race.text + bad_name.text + bad_pw.text)
        created = client.post("/api/v1/auth/register", json={"username": "new_user", "password": PASSWORD})
        self.assertEqual(created.status_code, 200)
        token = created.json()["access_token"]
        header = created.headers["set-cookie"].lower()
        self.assertIn("httponly", header)
        self.assertIn("samesite=lax", header)
        self.assertEqual(created.json()["user"]["username"], "new_user")
        stored = state["created"]["new_user"]["password_hash"]
        self.assertTrue(stored.startswith("pbkdf2_sha256$260000$"))
        self.assertNotIn(PASSWORD, stored)
        stored_hash, stored_user, ttl = state["sessions"][-1]
        self.assertEqual(stored_hash, hash_token(token))
        self.assertEqual(stored_user, state["created"]["new_user"]["id"])
        self.assertEqual(ttl, config.SESSION_TTL_SECONDS)
        me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(me.json()["username"], "new_user")
        actions = [event["action"] for event in _events(self.root)]
        self.assertEqual(actions.count("註冊被拒"), 4)
        self.assertIn("建立帳號", actions)
        self.assertNotIn(PASSWORD, _audit_text(self.root))
        self.assertNotIn(token, _audit_text(self.root))
        self.assertNotIn("short", _audit_text(self.root))

    def test_other_account_read_update_delete_are_404(self):
        owner = uuid.uuid4()
        stranger = uuid.uuid4()
        mid = uuid.uuid4()
        row = {"id": mid, "created_by": owner, "status": "reviewing", "meeting_name": "週會",
               "source_type": "audio", "error": None, "updated_at": None}

        def fake_get(conn, meeting_id, owner_id=None):
            if str(meeting_id) != str(mid):
                return None
            return dict(row)

        app = FastAPI()
        app.include_router(meetings_router.router)
        app.dependency_overrides[get_current_user] = lambda: {
            "id": stranger, "username": "bob", "token_hash": "x" * 64,
        }
        client = TestClient(app)
        with patch("app.services.meeting_service.get_conn", _conn), \
                patch("app.services.meeting_service.meetings.get_meeting", fake_get):
            status_res = client.get(f"/api/v1/meetings/{mid}/status")
            edit_res = client.put(
                f"/api/v1/meetings/{mid}/transcript/segments/S0001",
                json={"text": "改寫"},
            )
            delete_res = client.delete(f"/api/v1/meetings/{mid}")
        self.assertEqual(status_res.status_code, 404)
        self.assertEqual(edit_res.status_code, 404)
        self.assertEqual(delete_res.status_code, 404)
        denied = [event for event in _events(self.root) if event["action"] == "權限不足"]
        self.assertGreaterEqual(len(denied), 3)
        for event in denied:
            self._assert_audit_fields(event)
            self.assertEqual(event["username"], "bob")

        app.dependency_overrides[get_current_user] = lambda: {
            "id": owner, "username": "alice", "token_hash": "y" * 64,
        }
        gloss = FastAPI()
        gloss.include_router(glossary.router)
        gloss.dependency_overrides[get_current_user] = app.dependency_overrides[get_current_user]
        bad = TestClient(gloss).delete("/api/v1/glossary/not-a-uuid")
        self.assertEqual(bad.status_code, 404)
        self.assertIn("user_id = %s", terms.SQL_DELETE)
        self.assertIn("user_id = %s", terms.SQL_LIST)
        self.assertIn("created_by = %s", library.SQL_LIBRARY)

    def test_owner_filter_and_storage_id(self):
        class Cur:
            def execute(self, sql, params):
                self.sql = sql
                self.params = params
                return self

            def fetchone(self):
                return None

        owner = uuid.uuid4()
        cur = Cur()
        meetings.get_meeting(cur, uuid.uuid4(), owner_id=owner)
        self.assertIn("created_by = %s", cur.sql)
        meetings.delete_meeting(cur, uuid.uuid4(), owner_id=owner)
        self.assertIn("created_by = %s", cur.sql)
        meetings.update_status(cur, uuid.uuid4(), "transcribed", owner_id=owner)
        self.assertIn("created_by = %s", cur.sql)
        self.assertIn(owner, cur.params)

        mid = uuid.uuid4()
        self.assertEqual(uploads.safe_storage_id(mid.hex), mid.hex)
        self.assertEqual(uploads.safe_storage_id(str(mid)), mid.hex)
        for bad in ("../etc/passwd", "abcd", "a/b", mid.hex + "zz", "{%s}" % mid):
            with self.assertRaises(ValueError):
                uploads.safe_storage_id(bad)
            with self.assertRaises(ValueError):
                uploads.audio_destination(Path("/tmp/audio"), bad, "talk.mp3")
        stored = uploads.audio_destination(Path("audio"), mid, "talk.mp3")
        self.assertRegex(stored.name, r"^[0-9a-f]{32}\.mp3$")
        self.assertNotIn("..", stored.parts)

    def test_upload_limit_and_extensions(self):
        limit = config.MAX_UPLOAD_MB
        self.assertFalse(uploads.too_large(limit * 1024 * 1024))
        self.assertTrue(uploads.too_large(limit * 1024 * 1024 + 1))
        self.assertEqual(uploads.audio_suffix("talk.MP3"), ".mp3")
        self.assertEqual(uploads.transcript_suffix("notes.srt"), ".srt")
        for name in ("evil.php", "notes.exe", "noext", "clip.bin"):
            with self.assertRaises(ValueError):
                uploads.audio_suffix(name)
        for name in ("evil.php", "notes.docx", "noext"):
            with self.assertRaises(ValueError):
                uploads.transcript_suffix(name)

    def test_content_log_appends_and_delete_keeps_log(self):
        user_id = uuid.uuid4()
        key = audit.account_key(user_id)
        path = self.root / key / "content.jsonl"
        path.parent.mkdir(parents=True)
        path.write_bytes("這不是合法 JSON{{{{".encode())
        audit.record_content(
            user_id=user_id, username="alice", action="修改", ip="127.0.0.1",
            previous={"transcript": {"segments": [{"text": "舊逐字稿"}]}},
        )
        raw = path.read_bytes()
        self.assertTrue(raw.startswith("這不是合法 JSON{{{{".encode()))
        parsed = json.loads(raw.decode().splitlines()[-1])
        self.assertEqual(parsed["action"], "修改")
        self.assertIn("舊逐字稿", json.dumps(parsed["previous"], ensure_ascii=False))
        self.assertIn("time", parsed)
        self.assertEqual(parsed["timezone"], config.TIMEZONE)

        from app.services import meeting_service as svc

        owner = user_id
        mid = uuid.uuid4()
        audio_dir = self.root / "audio"
        audio_dir.mkdir()
        clip = audio_dir / "clip.m4a"
        clip.write_bytes(b"sound")
        outside = self.root / "keep.txt"
        outside.write_bytes(b"keep")
        meeting = {
            "id": mid, "created_by": owner, "status": "reviewing", "meeting_name": "週會",
            "audio_path": str(clip), "source_type": "audio",
        }
        transcript = {"segments": [{"text": "被換掉的內容"}]}

        def fake_get(conn, meeting_id, owner_id=None):
            return dict(meeting)

        def fake_row(conn, meeting_id, for_update=False):
            return {"transcript": transcript, "proofread": {"suggestions": []}, "confirmed_at": None}

        def fake_summary(conn, meeting_id):
            return {"headline": "舊重點"}

        def fake_delete(conn, meeting_id, owner_id=None):
            self.assertEqual(str(owner_id), str(owner))
            return {"id": meeting_id, "audio_path": str(clip)}

        actor = {"id": owner, "username": "alice"}
        with patch("app.services.meeting_service.get_conn", _conn), \
                patch("app.services.meeting_service.meetings.get_meeting", fake_get), \
                patch("app.services.meeting_service.transcripts.get_row", fake_row), \
                patch("app.services.meeting_service.transcripts.save_edits", lambda *a, **k: None), \
                patch("app.services.meeting_service.summaries.get_summary", fake_summary), \
                patch("app.services.meeting_service.meetings.delete_meeting", fake_delete), \
                patch("app.services.meeting_service.meetings.start_summarizing", lambda *a, **k: {"id": mid}), \
                patch.object(svc._worker, "submit", lambda *a, **k: None), \
                patch("app.config.AUDIO_DIR", audio_dir):
            svc._edit(mid, lambda text, suggestions, proofread: text, actor=actor, ip="10.0.0.8")
            svc.request_summary(mid, actor=actor, ip="10.0.0.8")
            svc.delete_owned_meeting(mid, actor=actor, ip="10.0.0.8")
        self.assertFalse(clip.exists())
        self.assertTrue(outside.exists())
        self.assertFalse(uploads.unlink_inside(audio_dir, str(outside)))
        content = _events(self.root)
        actions = [event["action"] for event in content if event["action"] in ("修改", "重新產生", "刪除")]
        self.assertEqual(actions, ["修改", "修改", "重新產生", "刪除"])
        blob = _audit_text(self.root)
        self.assertIn("舊逐字稿", blob)
        self.assertIn("舊重點", blob)
        self.assertIn("被換掉的內容", blob)
        self.assertTrue(path.exists())

    def _assert_audit_fields(self, event: dict):
        for key in ("time", "timezone", "username", "ip", "action", "detail"):
            self.assertIn(key, event)
        parsed = datetime.fromisoformat(event["time"])
        self.assertIsNotNone(parsed.tzinfo)
        self.assertEqual(event["timezone"], config.TIMEZONE)
        self.assertNotIn("password", event["detail"])
        self.assertNotIn("token", event["detail"])

    def _auth_state(self):
        return {
            "user": {
                "id": uuid.uuid4(),
                "username": "alice",
                "password_hash": security.hash_password(PASSWORD),
            },
            "lock": None,
            "sessions": [],
        }

    def _auth_client(self, state, verify=None):
        from psycopg.errors import UniqueViolation

        state.setdefault("created", {})

        def get_by_username(conn, username):
            if username == state["user"]["username"]:
                return state["user"]
            return state["created"].get(username)

        def create_user(conn, username, password_hash):
            if username == "taken":
                raise UniqueViolation("duplicate")
            row = {"id": uuid.uuid4(), "username": username, "password_hash": password_hash}
            state["created"][username] = row
            return row

        def get_lock(conn, username):
            return state["lock"]

        def record_login_failure(conn, username, now=None):
            moment = now or datetime.now(timezone.utc)
            count = state["lock"]["failed_count"] if state["lock"] else 0
            until = state["lock"]["locked_until"] if state["lock"] else None
            count, until, locked = security.next_failure(count, until, moment)
            state["lock"] = {"username": username, "failed_count": count, "locked_until": until}
            return {"failed_count": count, "locked_until": until, "locked": locked}

        def clear_login_failures(conn, username):
            state["lock"] = None

        def create_session(conn, token_hash, user_id, ttl):
            state["sessions"].append((token_hash, user_id, ttl))

        def get_valid_session(conn, token_hash):
            for stored_hash, user_id, _ttl in state["sessions"]:
                if stored_hash != token_hash:
                    continue
                name = state["user"]["username"]
                if user_id != state["user"]["id"]:
                    for row in state["created"].values():
                        if row["id"] == user_id:
                            name = row["username"]
                return {"user_id": user_id, "username": name}
            return None

        app = FastAPI()
        app.include_router(auth.router)
        patches = [
            patch("app.routers.auth.get_conn", _conn),
            patch("app.routers.auth.users.get_by_username", get_by_username),
            patch("app.routers.auth.users.create_user", create_user),
            patch("app.routers.auth.users.get_lock", get_lock),
            patch("app.routers.auth.users.record_login_failure", record_login_failure),
            patch("app.routers.auth.users.clear_login_failures", clear_login_failures),
            patch("app.routers.auth.sessions.delete_expired", lambda conn: 0),
            patch("app.routers.auth.sessions.create_session", create_session),
            patch("app.routers.auth.sessions.delete_session", lambda conn, token_hash: True),
            patch("app.deps.get_conn", _conn),
            patch("app.deps.sessions.get_valid_session", get_valid_session),
        ]
        if verify is not None:
            patches.append(patch("app.routers.auth.verify_password", verify))
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        return TestClient(app)


def _legacy_scrypt(password: str) -> str:
    salt = b"0123456789abcdef"
    dk = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)

    def b64(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    return f"scrypt${2**14}$8$1${b64(salt)}${b64(dk)}"


if __name__ == "__main__":
    unittest.main()
