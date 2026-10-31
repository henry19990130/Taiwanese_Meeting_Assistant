from __future__ import annotations

from uuid import UUID

from app.repositories._util import as_uuid

SQL_INSERT = """
INSERT INTO sessions (token_hash, user_id, expires_at)
VALUES (%s, %s, NOW() + %s * INTERVAL '1 second')
RETURNING token_hash, user_id, created_at, expires_at
"""
SQL_GET_VALID = """
SELECT u.id AS user_id, u.username, s.expires_at
FROM sessions s
JOIN users u ON u.id = s.user_id
WHERE s.token_hash = %s AND s.expires_at > NOW()
"""
SQL_DELETE = "DELETE FROM sessions WHERE token_hash = %s"
SQL_DELETE_EXPIRED = "DELETE FROM sessions WHERE expires_at <= NOW()"


def create_session(conn, token_hash: str, user_id: UUID | str, ttl_seconds: int) -> dict:
    return conn.execute(SQL_INSERT, (token_hash, as_uuid(user_id), int(ttl_seconds))).fetchone()


def get_valid_session(conn, token_hash: str) -> dict | None:
    return conn.execute(SQL_GET_VALID, (token_hash,)).fetchone()


def delete_session(conn, token_hash: str) -> bool:
    return conn.execute(SQL_DELETE, (token_hash,)).rowcount > 0


def delete_expired(conn) -> int:
    return conn.execute(SQL_DELETE_EXPIRED).rowcount
