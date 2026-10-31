from __future__ import annotations

from uuid import UUID

from psycopg.types.json import Jsonb

from app.repositories._util import as_uuid

LIST_FIELDS = ("reports", "discussions", "decisions", "action_items")
DEFAULT_NEXT_MEETING = {"date": None, "time": None, "status": "not_mentioned"}

_COLS = """meeting_id, reports, discussions, decisions, action_items,
           next_meeting, review_notes, headline, model_name, language, created_at, updated_at"""

SQL_UPSERT = f"""
INSERT INTO meeting_summaries
    (meeting_id, reports, discussions, decisions, action_items,
     next_meeting, review_notes, headline, model_name, language)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (meeting_id) DO UPDATE SET
    reports = EXCLUDED.reports,
    discussions = EXCLUDED.discussions,
    decisions = EXCLUDED.decisions,
    action_items = EXCLUDED.action_items,
    next_meeting = EXCLUDED.next_meeting,
    review_notes = EXCLUDED.review_notes,
    headline = EXCLUDED.headline,
    model_name = EXCLUDED.model_name,
    language = EXCLUDED.language,
    updated_at = NOW()
RETURNING {_COLS}
"""
SQL_UPDATE_CONTENT = f"""
UPDATE meeting_summaries SET
    reports = %s, discussions = %s, decisions = %s, action_items = %s,
    next_meeting = %s, review_notes = %s, headline = %s, updated_at = NOW()
WHERE meeting_id = %s
RETURNING {_COLS}
"""
SQL_GET = f"SELECT {_COLS} FROM meeting_summaries WHERE meeting_id = %s"


def _content_params(summary: dict) -> tuple:
    mc = summary.get("meeting_content") or {}
    return (
        *(Jsonb(mc.get(f) or []) for f in LIST_FIELDS),
        Jsonb(mc.get("next_meeting") or DEFAULT_NEXT_MEETING),
        Jsonb(summary.get("review_notes") or []),
        summary.get("headline"),
    )


def _to_summary(row: dict | None) -> dict | None:
    if row is None:
        return None
    return {
        "meeting_id": row["meeting_id"],
        "headline": row["headline"],
        "meeting_content": {
            **{f: row[f] for f in LIST_FIELDS},
            "next_meeting": row["next_meeting"],
        },
        "review_notes": row["review_notes"],
        "model_name": row["model_name"],
        "language": row.get("language") or "zh",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def upsert_summary(conn, meeting_id: UUID | str, summary: dict, model_name: str | None,
                   language: str | None = None) -> dict:
    row = conn.execute(
        SQL_UPSERT, (as_uuid(meeting_id), *_content_params(summary), model_name, language or "zh")
    ).fetchone()
    return _to_summary(row)


def update_content(conn, meeting_id: UUID | str, summary: dict) -> dict | None:
    row = conn.execute(
        SQL_UPDATE_CONTENT, (*_content_params(summary), as_uuid(meeting_id))
    ).fetchone()
    return _to_summary(row)


def get_summary(conn, meeting_id: UUID | str) -> dict | None:
    return _to_summary(conn.execute(SQL_GET, (as_uuid(meeting_id),)).fetchone())
