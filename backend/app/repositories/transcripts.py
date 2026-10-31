from __future__ import annotations

from uuid import UUID

from psycopg.types.json import Jsonb

from app.repositories._util import as_uuid

TRANSCRIPT_VERSION = 1

_COLS = "meeting_id, transcript, model_name, proofread, confirmed_at, created_at, updated_at"

SQL_UPSERT = f"""
INSERT INTO meeting_transcripts (meeting_id, transcript, model_name)
VALUES (%s, %s, %s)
ON CONFLICT (meeting_id) DO UPDATE SET
    transcript = EXCLUDED.transcript,
    model_name = EXCLUDED.model_name,
    proofread = NULL,          -- 逐字稿重新產生：舊的校對與確認都作廢
    confirmed_at = NULL,
    updated_at = NOW()
RETURNING {_COLS}
"""
SQL_GET = f"SELECT {_COLS} FROM meeting_transcripts WHERE meeting_id = %s"
SQL_GET_FOR_UPDATE = SQL_GET + " FOR UPDATE"
SQL_SET_TEXT = """
UPDATE meeting_transcripts SET transcript = %s, proofread = %s, updated_at = NOW()
WHERE meeting_id = %s
"""
SQL_SET_PROOFREAD = "UPDATE meeting_transcripts SET proofread = %s, updated_at = NOW() WHERE meeting_id = %s"
SQL_CONFIRM = """
UPDATE meeting_transcripts SET confirmed_at = NOW(), proofread = %s, updated_at = NOW()
WHERE meeting_id = %s
"""


def segment_id(index: int) -> str:
    return f"S{index + 1:04d}"


def build_transcript(
    meeting_id: UUID | str, segments: list[dict], model_name: str | None, asr_info: dict | None = None
) -> dict:
    ordered = sorted(segments, key=lambda s: int(s["segment_index"]))
    out = []
    for i, s in enumerate(ordered):
        text = str(s["text"]).strip()
        out.append(
            {
                "segment_id": segment_id(i),
                "segment_index": i,
                "start_ms": s.get("start_ms"),
                "end_ms": s.get("end_ms"),
                "text": text,
            }
        )
    data = {
        "version": TRANSCRIPT_VERSION,
        "meeting_id": str(as_uuid(meeting_id)),
        "asr_model": model_name,
        "segment_count": len(out),
        "segments": out,
    }
    if asr_info:
        data["asr_info"] = asr_info
    return data


def save_transcript(
    conn, meeting_id: UUID | str, segments: list[dict], model_name: str | None,
    asr_info: dict | None = None,
) -> dict:
    mid = as_uuid(meeting_id)
    transcript = build_transcript(mid, segments, model_name, asr_info)
    row = conn.execute(SQL_UPSERT, (mid, Jsonb(transcript), model_name)).fetchone()
    return row["transcript"]


def get_transcript(conn, meeting_id: UUID | str) -> dict | None:
    row = conn.execute(SQL_GET, (as_uuid(meeting_id),)).fetchone()
    return row["transcript"] if row else None


def get_row(conn, meeting_id: UUID | str, *, for_update: bool = False) -> dict | None:
    sql = SQL_GET_FOR_UPDATE if for_update else SQL_GET
    return conn.execute(sql, (as_uuid(meeting_id),)).fetchone()


def save_edits(conn, meeting_id: UUID | str, transcript: dict, proofread: dict | None) -> None:
    conn.execute(SQL_SET_TEXT, (Jsonb(transcript), Jsonb(proofread) if proofread is not None else None,
                                as_uuid(meeting_id)))


def save_proofread(conn, meeting_id: UUID | str, proofread: dict) -> None:
    conn.execute(SQL_SET_PROOFREAD, (Jsonb(proofread), as_uuid(meeting_id)))


def confirm(conn, meeting_id: UUID | str, proofread: dict | None) -> None:
    conn.execute(SQL_CONFIRM, (Jsonb(proofread) if proofread is not None else None, as_uuid(meeting_id)))
