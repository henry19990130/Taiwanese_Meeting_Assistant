import json
import sqlite3
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from breeze.api import create_app
from breeze.audio import FfmpegConverter
from breeze.identity.service import AuthService
from breeze.identity.store import IdentityStore
from breeze.jobs import MemoryJobStore
from breeze.meeting_summary.journal import SummaryJournal
from breeze.service import TranscriptionService
from breeze.settings import load_settings
from breeze.store import UserTranscriptStores
from helpers import FakeRecognizer, authed_client, tone_wav


class FakeSummarizer:
    def summarize_transcript(self, transcript, output_dir):
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "會議紀錄_regen.md"
        path.write_text("# 重新生成\n", encoding="utf-8")
        return path


class SummaryJournalApiTest(unittest.TestCase):
    def test_edit_keeps_original_and_writes_log(self):
        with TemporaryDirectory() as temporary:
            client, service, root = _client(temporary)
            record_id, user_id = _seed_summary(client, service, root, "# 原本摘要\n")

            updated = client.put(
                f"/api/transcripts/{record_id}/summary",
                json={"summary": "# 修改後\n"},
            )
            self.assertEqual(updated.status_code, 200, updated.text)
            self.assertIn("修改後", updated.json()["summary"])
            self.assertEqual(updated.json()["summary_log"]["original"].strip(), "# 原本摘要")
            self.assertTrue(updated.json()["summary_log"]["edited"])
            self.assertFalse(updated.json()["summary_log"]["regenerated"])

            again = client.put(
                f"/api/transcripts/{record_id}/summary",
                json={"summary": "# 第二次\n"},
            )
            versions = again.json()["summary_log"]["versions"]
            self.assertEqual(versions[0]["summary"].strip(), "# 原本摘要")
            self.assertEqual(versions[1]["summary"].strip(), "# 修改後")
            log_path = root / "logs" / user_id / f"{record_id}.json"
            saved = json.loads(log_path.read_text(encoding="utf-8"))
            self.assertEqual([item["summary"].strip() for item in saved["entries"]], ["# 原本摘要", "# 修改後"])
            connection = sqlite3.connect(root / "logs" / "journal.sqlite")
            try:
                rows = connection.execute(
                    "SELECT summary FROM summary_revisions WHERE owner_id = ? AND transcript_id = ? ORDER BY id",
                    (user_id, record_id),
                ).fetchall()
            finally:
                connection.close()
            self.assertEqual([row[0].strip() for row in rows], ["# 原本摘要", "# 修改後"])

            blank = client.put(
                f"/api/transcripts/{record_id}/summary",
                json={"summary": "  "},
            )
            self.assertEqual(blank.status_code, 400)

    def test_regenerate_marks_log_and_keeps_original(self):
        with TemporaryDirectory() as temporary:
            client, service, root = _client(temporary, summarizer=FakeSummarizer())
            record_id, _user_id = _seed_summary(client, service, root, "# 原本摘要\n")
            regenerated = client.post(f"/api/transcripts/{record_id}/summary/regenerate")
            self.assertEqual(regenerated.status_code, 200, regenerated.text)
            body = regenerated.json()
            self.assertIn("重新生成", body["summary"])
            self.assertEqual(body["summary_log"]["original"].strip(), "# 原本摘要")
            self.assertTrue(body["summary_log"]["regenerated"])
            self.assertFalse(body["summary_log"]["edited"])

    def test_other_account_cannot_edit_summary(self):
        with TemporaryDirectory() as temporary:
            client, _service, _root = _client(temporary)
            created = client.post(
                "/api/transcribe",
                files={"file": ("hello.wav", tone_wav(), "audio/wav")},
            )
            record_id = created.json()["id"]
            bob = authed_client(client.app, username="bob")
            denied = bob.put(
                f"/api/transcripts/{record_id}/summary",
                json={"summary": "# 偷改"},
            )
            self.assertEqual(denied.status_code, 404)

    def test_delete_summary_keeps_text_in_json_and_sqlite(self):
        with TemporaryDirectory() as temporary:
            client, service, root = _client(temporary)
            record_id, user_id = _seed_summary(client, service, root, "# 即將刪除\n")
            deleted = client.delete(f"/api/transcripts/{record_id}/summary")
            self.assertEqual(deleted.status_code, 200, deleted.text)
            body = deleted.json()
            self.assertEqual(body["summary"].strip(), "")
            self.assertTrue(body["summary_log"]["deleted"])
            self.assertEqual(body["summary_log"]["versions"][0]["summary"].strip(), "# 即將刪除")
            saved = json.loads((root / "logs" / user_id / f"{record_id}.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["entries"][0]["action"], "delete")
            self.assertIn("即將刪除", saved["entries"][0]["summary"])
            connection = sqlite3.connect(root / "logs" / "journal.sqlite")
            try:
                row = connection.execute(
                    "SELECT action, summary FROM summary_revisions WHERE transcript_id = ?",
                    (record_id,),
                ).fetchone()
            finally:
                connection.close()
            self.assertEqual(row[0], "delete")
            self.assertIn("即將刪除", row[1])

    def test_list_delete_writes_summary_into_json_and_sqlite(self):
        with TemporaryDirectory() as temporary:
            client, service, root = _client(temporary)
            record_id, user_id = _seed_summary(client, service, root, "# 列表刪除\n")
            removed = client.delete(f"/api/transcripts/{record_id}")
            self.assertEqual(removed.status_code, 200, removed.text)
            self.assertEqual(client.get(f"/api/transcripts/{record_id}").status_code, 404)
            saved = json.loads((root / "logs" / user_id / f"{record_id}.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["entries"][-1]["action"], "delete")
            self.assertIn("列表刪除", saved["entries"][-1]["summary"])
            connection = sqlite3.connect(root / "logs" / "journal.sqlite")
            try:
                row = connection.execute(
                    """
                    SELECT action, summary
                    FROM summary_revisions
                    WHERE transcript_id = ?
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (record_id,),
                ).fetchone()
            finally:
                connection.close()
            self.assertEqual(row[0], "delete")
            self.assertIn("列表刪除", row[1])

    def test_old_json_without_version_text_imports_original(self):
        owner_id = "a" * 32
        transcript_id = "b" * 32
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = root / owner_id
            folder.mkdir()
            (folder / f"{transcript_id}.json").write_text(
                json.dumps(
                    {
                        "original": "# 舊版\n",
                        "entries": [{"action": "edit", "at": "2026-10-15T15:00:00+08:00"}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            journal = SummaryJournal(root)
            body = journal.read(owner_id, transcript_id)
            self.assertEqual(body["versions"][0]["summary"].strip(), "# 舊版")
            connection = sqlite3.connect(root / "journal.sqlite")
            try:
                count = connection.execute("SELECT COUNT(*) FROM summary_revisions").fetchone()[0]
            finally:
                connection.close()
            self.assertEqual(count, 1)


def _client(temporary: str, summarizer=None):
    root = Path(temporary)
    settings = load_settings()
    auth = AuthService(IdentityStore(root / "identity.sqlite"))
    service = TranscriptionService(
        converter=FfmpegConverter(settings.ffmpeg_path),
        recognizer=FakeRecognizer(),
        stores=UserTranscriptStores(root / "transcripts"),
        jobs=MemoryJobStore(),
        allowed_suffixes=settings.allowed_suffixes,
        max_upload_bytes=settings.max_upload_bytes,
        summarizer=summarizer,
        summaries_dir=root / "summaries",
        summary_journal=SummaryJournal(root / "logs"),
    )
    app = create_app(service, auth, settings.web_dir)
    return authed_client(app), service, root


def _seed_summary(client, service, root: Path, text: str):
    created = client.post(
        "/api/transcribe",
        files={"file": ("hello.wav", tone_wav(), "audio/wav")},
    )
    body = created.json()
    user_id = client.get("/api/auth/me").json()["id"]
    folder = root / "summaries" / user_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "會議紀錄_seed.md").write_text(text, encoding="utf-8")
    record = service.get_transcript(user_id, body["id"])
    service._stores.for_user(user_id).save(replace(record, summary_filename="會議紀錄_seed.md"))
    return body["id"], user_id
