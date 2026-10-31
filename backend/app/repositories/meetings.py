from __future__ import annotations

import datetime as dt
import json
import uuid
from uuid import UUID

from app.repositories._util import as_uuid

STATUSES = (
    "uploaded", "transcribing", "proofreading", "reviewing",
    "transcribed", "summarizing", "completed", "failed",
)

_COLS = """id, meeting_name, date, start_time, end_time, source_type, audio_path,
           status, error_message, created_by, created_at, updated_at"""
SOURCE_TYPES = ("audio", "transcript")

SQL_INSERT = f"""
INSERT INTO meetings (id, meeting_name, date, start_time, end_time, source_type, audio_path, created_by)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
RETURNING {_COLS}
"""
SQL_GET = f"SELECT {_COLS} FROM meetings WHERE id = %s"
SQL_SET_STATUS = f"""
UPDATE meetings SET status = %s, error_message = NULL, updated_at = NOW()
WHERE id = %s
RETURNING {_COLS}
"""
SQL_SET_FAILED = f"""
UPDATE meetings SET status = 'failed', error_message = %s, updated_at = NOW()
WHERE id = %s
RETURNING {_COLS}
"""
SQL_DELETE = "DELETE FROM meetings WHERE id = %s RETURNING id, audio_path"
SQL_START_SUMMARIZING = f"""
UPDATE meetings SET status = 'summarizing', error_message = NULL, updated_at = NOW()
WHERE id = %s
  AND status IN ('transcribed', 'completed', 'failed')
  AND EXISTS (SELECT 1 FROM meeting_transcripts t
              WHERE t.meeting_id = meetings.id AND t.confirmed_at IS NOT NULL)
RETURNING {_COLS}
"""
SQL_START_PROOFREADING = f"""
UPDATE meetings SET status = 'proofreading', error_message = NULL, updated_at = NOW()
WHERE id = %s
  AND status IN ('reviewing', 'failed')
  AND EXISTS (SELECT 1 FROM meeting_transcripts t
              WHERE t.meeting_id = meetings.id AND t.confirmed_at IS NULL)
RETURNING {_COLS}
"""
SQL_FAIL_INTERRUPTED = """
UPDATE meetings SET
    status = 'failed',
    error_message = json_build_object(
        'stage', CASE status WHEN 'summarizing' THEN 'summarizing'
                             WHEN 'proofreading' THEN 'proofreading' ELSE 'transcribing' END,
        'code', 'INTERRUPTED',
        'message', '伺服器重新啟動，處理中斷，請重新操作。'
    )::text,
    updated_at = NOW()
WHERE status IN ('uploaded', 'transcribing', 'proofreading', 'summarizing')
RETURNING id
"""


def _decode(row: dict | None) -> dict | None:
    if row is None:
        return None
    raw = row.get("error_message")
    error = None
    if raw:
        try:
            error = json.loads(raw)
        except ValueError:
            error = {"stage": None, "code": None, "message": raw}
    row["error"] = error
    return row


def _and_owner(sql: str, params: tuple, owner_id: UUID | str | None) -> tuple[str, tuple]:
    if owner_id is None:
        return sql, params
    needle = "WHERE id = %s"
    if needle not in sql:
        raise RuntimeError("owner filter missing anchor")
    return sql.replace(needle, "WHERE id = %s AND created_by = %s", 1), params + (as_uuid(owner_id),)


def create_meeting(
    conn,
    *,
    meeting_name: str,
    date: dt.date,
    audio_path: str | None,
    start_time: dt.time | None = None,
    end_time: dt.time | None = None,
    meeting_id: UUID | str | None = None,
    source_type: str = "audio",
    created_by: UUID | str | None = None,
) -> dict:
    if source_type not in SOURCE_TYPES:
        raise ValueError(f"不合法的來源：{source_type}")
    if source_type == "audio" and not audio_path:
        raise ValueError("上傳錄音檔時 audio_path 必填")
    mid = as_uuid(meeting_id) if meeting_id else uuid.uuid4()
    row = conn.execute(
        SQL_INSERT, (mid, meeting_name, date, start_time, end_time, source_type, audio_path,
                     as_uuid(created_by) if created_by else None)
    ).fetchone()
    return _decode(row)


def get_meeting(conn, meeting_id: UUID | str, owner_id: UUID | str | None = None) -> dict | None:
    sql, params = _and_owner(SQL_GET, (as_uuid(meeting_id),), owner_id)
    return _decode(conn.execute(sql, params).fetchone())


def update_status(conn, meeting_id: UUID | str, status: str, owner_id: UUID | str | None = None) -> dict | None:
    if status not in STATUSES or status == "failed":
        raise ValueError(f"不合法的狀態：{status}")
    sql, params = _and_owner(SQL_SET_STATUS, (status, as_uuid(meeting_id)), owner_id)
    return _decode(conn.execute(sql, params).fetchone())


def mark_failed(
    conn, meeting_id: UUID | str, *, stage: str, code: str, message: str
) -> dict | None:
    payload = json.dumps({"stage": stage, "code": code, "message": message}, ensure_ascii=False)
    return _decode(conn.execute(SQL_SET_FAILED, (payload, as_uuid(meeting_id))).fetchone())


def delete_meeting(conn, meeting_id: UUID | str, owner_id: UUID | str | None = None) -> dict | None:
    sql, params = _and_owner(SQL_DELETE, (as_uuid(meeting_id),), owner_id)
    return conn.execute(sql, params).fetchone()


def start_summarizing(conn, meeting_id: UUID | str, owner_id: UUID | str | None = None) -> dict | None:
    sql, params = _and_owner(SQL_START_SUMMARIZING, (as_uuid(meeting_id),), owner_id)
    return _decode(conn.execute(sql, params).fetchone())


def start_proofreading(conn, meeting_id: UUID | str, owner_id: UUID | str | None = None) -> dict | None:
    sql, params = _and_owner(SQL_START_PROOFREADING, (as_uuid(meeting_id),), owner_id)
    return _decode(conn.execute(sql, params).fetchone())


def fail_interrupted(conn) -> int:
    return len(conn.execute(SQL_FAIL_INTERRUPTED).fetchall())
