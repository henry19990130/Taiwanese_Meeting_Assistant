import hashlib
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from breeze.identity.models import AuditEvent, User


class IdentityStore:
    """使用者、session、鎖定、稽核都在同一份 SQLite，對外仍是獨立方法。"""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        with self._db() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA foreign_keys=ON;
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    username_lower TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id),
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS lockouts (
                    key TEXT PRIMARY KEY,
                    failures INTEGER NOT NULL,
                    locked_until TEXT,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    time TEXT NOT NULL,
                    time_utc TEXT NOT NULL,
                    tz TEXT NOT NULL,
                    account TEXT NOT NULL,
                    ip TEXT NOT NULL,
                    action TEXT NOT NULL,
                    detail TEXT NOT NULL
                );
                """
            )

    def create_user(self, user: User, password_hash: str) -> User:
        with self._db() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO users (id, username, username_lower, password_hash, role, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user.id,
                        user.username,
                        user.username.lower(),
                        password_hash,
                        user.role,
                        user.created_at,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise DuplicateUsername() from exc
        return user

    def get_user_by_id(self, user_id: str) -> User | None:
        row = self._one("SELECT * FROM users WHERE id = ?", (user_id,))
        return _user_from_row(row) if row else None

    def get_user_by_username(self, username: str) -> User | None:
        row = self._one(
            "SELECT * FROM users WHERE username_lower = ?",
            (username.lower(),),
        )
        return _user_from_row(row) if row else None

    def password_hash_for(self, user_id: str) -> str | None:
        row = self._one("SELECT password_hash FROM users WHERE id = ?", (user_id,))
        return str(row["password_hash"]) if row else None

    def set_role(self, user_id: str, role: str) -> User | None:
        with self._db() as connection:
            connection.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
        return self.get_user_by_id(user_id)

    def create_session(self, token: str, user_id: str, created_at: str, expires_at: str) -> None:
        with self._db() as connection:
            connection.execute(
                """
                INSERT INTO sessions (token_hash, user_id, created_at, expires_at)
                VALUES (?, ?, ?, ?)
                """,
                (_token_hash(token), user_id, created_at, expires_at),
            )

    def drop_sessions_for_user(self, user_id: str) -> None:
        with self._db() as connection:
            connection.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))

    def session_user_id(self, token: str, now: str) -> str | None:
        row = self._one(
            """
            SELECT user_id FROM sessions
            WHERE token_hash = ? AND expires_at > ?
            """,
            (_token_hash(token), now),
        )
        return str(row["user_id"]) if row else None

    def delete_session(self, token: str) -> None:
        with self._db() as connection:
            connection.execute(
                "DELETE FROM sessions WHERE token_hash = ?",
                (_token_hash(token),),
            )

    def lockout(self, key: str) -> tuple[int, str | None]:
        row = self._one(
            "SELECT failures, locked_until FROM lockouts WHERE key = ?",
            (key,),
        )
        if row is None:
            return 0, None
        return int(row["failures"]), row["locked_until"]

    def set_lockout(self, key: str, failures: int, locked_until: str | None, updated_at: str) -> None:
        with self._db() as connection:
            connection.execute(
                """
                INSERT INTO lockouts (key, failures, locked_until, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    failures = excluded.failures,
                    locked_until = excluded.locked_until,
                    updated_at = excluded.updated_at
                """,
                (key, failures, locked_until, updated_at),
            )

    def clear_lockout(self, key: str) -> None:
        with self._db() as connection:
            connection.execute("DELETE FROM lockouts WHERE key = ?", (key,))

    def append_audit(self, event: AuditEvent) -> None:
        with self._db() as connection:
            connection.execute(
                """
                INSERT INTO audit_log (time, time_utc, tz, account, ip, action, detail)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.time,
                    event.time_utc,
                    event.tz,
                    event.account,
                    event.ip,
                    event.action,
                    event.detail,
                ),
            )

    def list_audit(self, limit: int = 100) -> list[AuditEvent]:
        with self._db() as connection:
            rows = connection.execute(
                """
                SELECT time, time_utc, tz, account, ip, action, detail
                FROM audit_log
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            AuditEvent(
                time=str(row["time"]),
                time_utc=str(row["time_utc"]),
                tz=str(row["tz"]),
                account=str(row["account"]),
                ip=str(row["ip"]),
                action=str(row["action"]),
                detail=str(row["detail"]),
            )
            for row in rows
        ]

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @contextmanager
    def _db(self):
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _one(self, sql: str, params: tuple) -> sqlite3.Row | None:
        with self._db() as connection:
            return connection.execute(sql, params).fetchone()


class DuplicateUsername(Exception):
    pass


def _user_from_row(row: sqlite3.Row) -> User:
    return User(
        id=str(row["id"]),
        username=str(row["username"]),
        role=str(row["role"]),
        created_at=str(row["created_at"]),
    )


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
