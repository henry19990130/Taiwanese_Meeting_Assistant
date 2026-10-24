from __future__ import annotations

import uuid
from uuid import UUID

from app.repositories._util import as_uuid

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
