import json
import time
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from breeze.meeting_summary.client import OllamaChatClient, resolve_model_name
from breeze.meeting_summary.errors import SummaryError
from breeze.meeting_summary.export import export_markdown
from breeze.meeting_summary.io import read_transcript_file
from breeze.meeting_summary.prompt import SYSTEM_PROMPT, build_user_prompt
from helpers import FakeRecognizer, authed_client, tone_wav
from breeze.service import TranscriptionService
from breeze.jobs import MemoryJobStore
from breeze.store import UserTranscriptStores
from breeze.audio import FfmpegConverter
from breeze.settings import load_settings


class MeetingSummaryUnitTest(unittest.TestCase):
    def test_read_txt_and_reject_other_types(self):
        with TemporaryDirectory() as temporary:
            folder = Path(temporary)
            txt = folder / "meeting.txt"
            txt.write_text("今天決議下周交稿。", encoding="utf-8")
            self.assertIn("決議", read_transcript_file(txt))
            md = folder / "meeting.md"
            md.write_text("# 逐字稿\n內容", encoding="utf-8")
            self.assertIn("內容", read_transcript_file(md))
            bad = folder / "meeting.json"
            bad.write_text("{}", encoding="utf-8")
            with self.assertRaises(SummaryError):
                read_transcript_file(bad)
            missing = folder / "nope.txt"
            with self.assertRaises(SummaryError):
                read_transcript_file(missing)

    def test_export_uses_date_and_avoids_overwrite(self):
        with TemporaryDirectory() as temporary:
            folder = Path(temporary)
            when = datetime(2026, 10, 14, 15, 16, 17)
            first = export_markdown("# 會議紀錄\n", folder, when)
            self.assertEqual(first.name, "會議紀錄_20261014.md")
            second = export_markdown("# 會議紀錄\n第二份", folder, when)
            self.assertEqual(second.name, "會議紀錄_20261014_151617.md")
            self.assertTrue(first.read_text(encoding="utf-8").startswith("# 會議紀錄"))

    def test_prompt_requires_traditional_chinese_sections(self):
        self.assertIn("台灣繁體中文", SYSTEM_PROMPT)
        self.assertIn("會議基本資訊", SYSTEM_PROMPT)
        self.assertIn("核心主旨", SYSTEM_PROMPT)
        self.assertIn("重點議題討論", SYSTEM_PROMPT)
        self.assertIn("決議事項", SYSTEM_PROMPT)
        self.assertIn("待辦事項與行動計畫", SYSTEM_PROMPT)
        self.assertIn("禁止中國大陸用語", SYSTEM_PROMPT)
        user = build_user_prompt("內容", source_name="a.wav", created_at="2026-10-14")
        self.assertIn("a.wav", user)
        self.assertIn("內容", user)

    def test_ollama_stream_collects_tokens(self):
        lines = [
            json.dumps({"message": {"content": "# 會議紀錄\n"}, "done": False}),
            json.dumps({"message": {"content": "## 核心主旨\n完成。"}, "done": False}),
            json.dumps({"done": True}),
        ]
        response = MagicMock()
        response.status_code = 200
        response.iter_lines.return_value = lines
        response.__enter__.return_value = response
        tokens: list[str] = []
        with patch("breeze.meeting_summary.client.requests.post", return_value=response):
            text = OllamaChatClient().summarize(
                "今天開會",
                source_name="a.txt",
                created_at="2026-10-14",
                on_token=tokens.append,
            )
        self.assertIn("會議紀錄", text)
        self.assertEqual("".join(tokens), text)

    def test_ollama_down_has_clear_message(self):
        import requests as requests_lib

        with patch(
            "breeze.meeting_summary.client.requests.post",
            side_effect=requests_lib.exceptions.ConnectionError(),
        ):
            with self.assertRaises(SummaryError) as caught:
                OllamaChatClient().summarize("x", source_name="a.txt", created_at="t")
        self.assertIn("ollama serve", str(caught.exception))

    def test_missing_model_message(self):
        response = MagicMock()
        response.status_code = 404
        response.text = "model not found"
        tags = MagicMock()
        tags.status_code = 200
        tags.json.return_value = {"models": []}
        with (
            patch("breeze.meeting_summary.client.requests.post", return_value=response),
            patch("breeze.meeting_summary.client.requests.get", return_value=tags),
        ):
            with self.assertRaises(SummaryError) as caught:
                OllamaChatClient().summarize("x", source_name="a.txt", created_at="t")
        self.assertIn("ollama pull llama3.1:8b", str(caught.exception))

    def test_bare_name_uses_installed_8b_tag(self):
        self.assertEqual(resolve_model_name("llama3.1", ["llama3.1:8b"]), "llama3.1:8b")
        self.assertIsNone(resolve_model_name("llama3.1:70b", ["llama3.1:8b"]))
        missing = MagicMock()
        missing.status_code = 404
        ok = MagicMock()
        ok.status_code = 200
        ok.iter_lines.return_value = [
            json.dumps({"message": {"content": "# 會議紀錄"}, "done": True})
        ]
        tags = MagicMock()
        tags.status_code = 200
        tags.json.return_value = {"models": [{"name": "llama3.1:8b"}]}
        with (
            patch("breeze.meeting_summary.client.requests.post", side_effect=[missing, ok]) as post,
            patch("breeze.meeting_summary.client.requests.get", return_value=tags),
        ):
            text = OllamaChatClient(model="llama3.1").summarize("x", source_name="a.txt", created_at="t")
        self.assertEqual(text, "# 會議紀錄")
        self.assertEqual(post.call_args_list[1].kwargs["json"]["model"], "llama3.1:8b")


class MeetingSummaryPipelineTest(unittest.TestCase):
    def test_job_writes_summary_after_transcript(self):
        class FakeSummarizer:
            def __init__(self):
                self.called = False

            def summarize_transcript(self, transcript, output_dir):
                self.called = True
                self.text = transcript.text
                output_dir.mkdir(parents=True, exist_ok=True)
                path = output_dir / "會議紀錄_20261014.md"
                path.write_text("# 會議紀錄\n", encoding="utf-8")
                return path

        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            summarizer = FakeSummarizer()
            settings = load_settings()
            from breeze.api import create_app
            from breeze.identity.service import AuthService
            from breeze.identity.store import IdentityStore

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
            )
            app = create_app(service, auth, settings.web_dir)
            client = authed_client(app)
            created = client.post(
                "/api/transcribe",
                files={"file": ("hello.wav", tone_wav(), "audio/wav")},
            )
            self.assertEqual(created.status_code, 200, created.text)
            self.assertTrue(summarizer.called)
            self.assertEqual(created.json()["text"], summarizer.text)
            user_id = client.get("/api/auth/me").json()["id"]
            self.assertTrue((root / "summaries" / user_id / "會議紀錄_20261014.md").is_file())
            fetched = client.get(f"/api/transcripts/{created.json()['id']}")
            self.assertEqual(fetched.status_code, 200)
            self.assertEqual(fetched.json()["summary"].strip(), "# 會議紀錄")

            job = client.post(
                "/api/jobs",
                files={"file": ("hello.wav", tone_wav(), "audio/wav")},
            )
            self.assertEqual(job.status_code, 200, job.text)
            body = None
            for _ in range(80):
                body = client.get(f"/api/jobs/{job.json()['id']}").json()
                if body.get("status") in {"done", "failed"}:
                    break
                time.sleep(0.05)
            self.assertIsNotNone(body)
            self.assertEqual(body["status"], "done")
            self.assertEqual(body["transcript"]["text"], "測試逐字稿")
            self.assertEqual(body["transcript"]["source_filename"], "hello.wav")
            self.assertTrue(body["transcript"]["created_at"])
            self.assertEqual(body["transcript"]["summary"].strip(), "# 會議紀錄")


if __name__ == "__main__":
    unittest.main()
