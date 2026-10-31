from __future__ import annotations

import uuid
from uuid import UUID

from app.repositories._util import as_uuid

MAX_TERMS = 200
MAX_TERM_LEN = 30

SQL_LIST = "SELECT id, term, created_at FROM user_terms WHERE user_id = %s ORDER BY created_at, term"
SQL_COUNT = "SELECT COUNT(*) AS n FROM user_terms WHERE user_id = %s"
SQL_INSERT = """
INSERT INTO user_terms (id, user_id, term) VALUES (%s, %s, %s)
ON CONFLICT (user_id, term) DO NOTHING
RETURNING id
"""
SQL_DELETE = "DELETE FROM user_terms WHERE user_id = %s AND id = %s RETURNING id"
SQL_LOCK_USER = "SELECT id FROM users WHERE id = %s FOR UPDATE"


def clean(term: str) -> str:
    return str(term or "").strip().strip("，,、；;。")


def list_terms(conn, user_id: UUID | str) -> list[dict]:
    return conn.execute(SQL_LIST, (as_uuid(user_id),)).fetchall()


def add_terms(conn, user_id: UUID | str, terms: list[str]) -> dict:
    uid = as_uuid(user_id)
    conn.execute(SQL_LOCK_USER, (uid,))
    n = conn.execute(SQL_COUNT, (uid,)).fetchone()["n"]
    out = {"added": [], "duplicated": [], "invalid": [], "over_limit": []}
    seen = set()
    for raw in terms:
        t = clean(raw)
        if not t or len(t) > MAX_TERM_LEN:
            if raw and str(raw).strip():
                out["invalid"].append(str(raw).strip()[:MAX_TERM_LEN + 5])
            continue
        if t in seen:
            continue
        seen.add(t)
        if n >= MAX_TERMS:
            out["over_limit"].append(t)
            continue
        row = conn.execute(SQL_INSERT, (uuid.uuid4(), uid, t)).fetchone()
        if row is None:
            out["duplicated"].append(t)
        else:
            out["added"].append(t)
            n += 1
    return out


def delete_term(conn, user_id: UUID | str, term_id: UUID | str) -> bool:
    return conn.execute(SQL_DELETE, (as_uuid(user_id), as_uuid(term_id))).fetchone() is not None


def term_strings(conn, user_id: UUID | str | None) -> list[str]:
    if not user_id:
        return []
    return [r["term"] for r in list_terms(conn, user_id)]
