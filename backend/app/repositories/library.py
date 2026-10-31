from __future__ import annotations

from uuid import UUID

from app.repositories._util import as_uuid

SQL_LIBRARY = """
SELECT m.id, m.meeting_name, m.date, m.start_time, m.end_time, m.status,
       t.transcript,
       s.headline, s.reports, s.discussions, s.decisions, s.action_items, s.next_meeting, s.review_notes
FROM meetings m
JOIN meeting_transcripts t ON t.meeting_id = m.id AND t.confirmed_at IS NOT NULL
LEFT JOIN meeting_summaries s ON s.meeting_id = m.id
WHERE m.created_by = %s
ORDER BY m.date DESC, m.start_time DESC NULLS LAST, m.created_at DESC
"""


def load_library(conn, user_id: UUID | str) -> list[dict]:
    rows = conn.execute(SQL_LIBRARY, (as_uuid(user_id),)).fetchall()
    out = []
    for r in rows:
        has_summary = r["headline"] is not None or r["decisions"] is not None
        out.append({
            "id": str(r["id"]),
            "name": r["meeting_name"],
            "date": r["date"],
            "start_time": r["start_time"],
            "status": r["status"],
            "segments": (r["transcript"] or {}).get("segments", []),
            "summary": {
                "headline": r["headline"],
                "reports": r["reports"] or [],
                "discussions": r["discussions"] or [],
                "decisions": r["decisions"] or [],
                "action_items": r["action_items"] or [],
                "next_meeting": r["next_meeting"] or {},
                "review_notes": r["review_notes"] or [],
            } if has_summary else None,
        })
    return out
