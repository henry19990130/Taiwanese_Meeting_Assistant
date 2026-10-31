from __future__ import annotations

import datetime as dt
import uuid
from uuid import UUID

from app.repositories._util import as_uuid
from app.security import lock_is_active, next_failure

SQL_INSERT = """
INSERT INTO users (id, username, password_hash)
VALUES (%s, %s, %s)
RETURNING id, username
"""
SQL_BY_USERNAME = "SELECT id, username, password_hash FROM users WHERE username = %s"
SQL_BY_ID = "SELECT id, username FROM users WHERE id = %s"
SQL_SET_PASSWORD = "UPDATE users SET password_hash = %s WHERE username = %s RETURNING id, username"


def create_user(conn, username: str, password_hash: str) -> dict:
    return conn.execute(SQL_INSERT, (uuid.uuid4(), username, password_hash)).fetchone()


def get_by_username(conn, username: str) -> dict | None:
    return conn.execute(SQL_BY_USERNAME, (username,)).fetchone()


def get_by_id(conn, user_id: UUID | str) -> dict | None:
    return conn.execute(SQL_BY_ID, (as_uuid(user_id),)).fetchone()


def set_password(conn, username: str, password_hash: str) -> dict | None:
    return conn.execute(SQL_SET_PASSWORD, (password_hash, username)).fetchone()


SQL_GET_LOCK = """
SELECT username, failed_count, locked_until
FROM login_locks WHERE username = %s
"""
SQL_UPSERT_LOCK = """
INSERT INTO login_locks (username, failed_count, locked_until)
VALUES (%s, %s, %s)
ON CONFLICT (username) DO UPDATE SET
    failed_count = EXCLUDED.failed_count,
    locked_until = EXCLUDED.locked_until
RETURNING username, failed_count, locked_until
"""
SQL_CLEAR_LOCK = "DELETE FROM login_locks WHERE username = %s"


def get_lock(conn, username: str) -> dict | None:
    return conn.execute(SQL_GET_LOCK, (username,)).fetchone()


def lock_active(row: dict | None, now: dt.datetime | None = None) -> bool:
    if row is None:
        return False
    return lock_is_active(row.get("locked_until"), now or dt.datetime.now(dt.timezone.utc))


def record_login_failure(conn, username: str, now: dt.datetime | None = None) -> dict:
    row = get_lock(conn, username)
    moment = now or dt.datetime.now(dt.timezone.utc)
    count = row["failed_count"] if row else 0
    until = row["locked_until"] if row else None
    count, until, locked = next_failure(count, until, moment)
    saved = conn.execute(SQL_UPSERT_LOCK, (username, count, until)).fetchone()
    return {
        "failed_count": saved["failed_count"],
        "locked_until": saved["locked_until"],
        "locked": locked,
    }


def clear_login_failures(conn, username: str) -> None:
    conn.execute(SQL_CLEAR_LOCK, (username,))
