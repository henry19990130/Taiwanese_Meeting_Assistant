import sqlite3
from contextlib import contextmanager
from pathlib import Path


class SqliteSummaryLog:
    """摘要版本的 SQLite。一列是一次被換掉的摘要全文。"""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        with self._db() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS summary_revisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_id TEXT NOT NULL,
                    transcript_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_summary_revisions_lookup
                    ON summary_revisions (owner_id, transcript_id, id);
                """
            )

    def list(self, owner_id: str, transcript_id: str) -> list[dict[str, str]]:
        with self._db() as connection:
            rows = connection.execute(
                """
                SELECT action, summary, created_at
                FROM summary_revisions
                WHERE owner_id = ? AND transcript_id = ?
                ORDER BY id
                """,
                (owner_id, transcript_id),
            ).fetchall()
        return [
            {
                "action": str(row["action"]),
                "summary": str(row["summary"]),
                "at": str(row["created_at"]),
            }
            for row in rows
        ]

    def append(
        self,
        owner_id: str,
        transcript_id: str,
        action: str,
        summary: str,
        created_at: str,
    ) -> None:
        with self._db() as connection:
            connection.execute(
                """
                INSERT INTO summary_revisions
                    (owner_id, transcript_id, action, summary, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (owner_id, transcript_id, action, summary, created_at),
            )

    def count(self, owner_id: str, transcript_id: str) -> int:
        with self._db() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS total
                FROM summary_revisions
                WHERE owner_id = ? AND transcript_id = ?
                """,
                (owner_id, transcript_id),
            ).fetchone()
        return int(row["total"])

    def delete(self, owner_id: str, transcript_id: str) -> None:
        with self._db() as connection:
            connection.execute(
                "DELETE FROM summary_revisions WHERE owner_id = ? AND transcript_id = ?",
                (owner_id, transcript_id),
            )

    @contextmanager
    def _db(self):
        connection = sqlite3.connect(self._path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
