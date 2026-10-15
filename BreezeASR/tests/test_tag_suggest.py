import unittest
from dataclasses import replace
from tempfile import TemporaryDirectory

from breeze.meeting_summary.errors import SummaryError
from breeze.tag_suggest import LlmTagSuggester, parse_suggested_tags
from helpers import authed_client, build_app, tone_wav
from test_summary_journal import _client, _seed_summary


class ParseSuggestedTagsTest(unittest.TestCase):
    def test_reads_json_and_drops_invalid_duplicates(self):
        raw = """推薦如下：
```json
["菜場採買", "水果台語", "菜場採買", "#不合法", "一二三四五六七八九十一二三四五六七八九十一"]
```
"""
        self.assertEqual(parse_suggested_tags(raw), ["菜場採買", "水果台語"])

    def test_reads_objects_nested_lists_and_chinese_separators(self):
        objects = """[
  {"tag": "台語課", "type": "主題"},
  {"tag": "鉛筆", "type": "產品"}
]"""
        self.assertEqual(parse_suggested_tags(objects), ["台語課", "鉛筆"])
        nested = '[["三分鐘台語課", "開學"], ["鉛筆", "書簿"]]'
        self.assertEqual(parse_suggested_tags(nested), ["三分鐘台語課", "開學", "鉛筆", "書簿"])
        prose = "- 菜場採買\n- 水果台語\n南門市場、供應商"
        self.assertEqual(parse_suggested_tags(prose), ["菜場採買", "水果台語", "南門市場", "供應商"])

    def test_empty_reply_is_asked_again(self):
        class Client:
            def __init__(self):
                self.calls = 0

            def complete(self, *, system, user, temperature=None):
                self.calls += 1
                if self.calls == 1:
                    return "[]"
                return '["菜場採買", "水果台語"]'

        client = Client()
        self.assertEqual(LlmTagSuggester(client).suggest("買水果"), ["菜場採買", "水果台語"])
        self.assertEqual(client.calls, 2)

    def test_object_reply_does_not_ask_again(self):
        class Client:
            def __init__(self):
                self.calls = 0

            def complete(self, *, system, user, temperature=None):
                self.calls += 1
                return '[{"tag": "菜場採買"}]'

        client = Client()
        self.assertEqual(LlmTagSuggester(client).suggest("買水果"), ["菜場採買"])
        self.assertEqual(client.calls, 1)


class SuggestTagsApiTest(unittest.TestCase):
    def test_uses_summary_and_skips_tags_already_on_the_record(self):
        class Recorder:
            def __init__(self):
                self.text = ""

            def suggest(self, text):
                self.text = text
                return ["菜場採買", "水果台語", "太長了" * 8, 12]

        with TemporaryDirectory() as temporary:
            client, service, root = _client(temporary)
            recorder = Recorder()
            service._tag_suggester = recorder
            record_id, _user_id = _seed_summary(client, service, root, "# 菜市場\n買水果。\n")
            tagged = client.put(
                f"/api/transcripts/{record_id}/tags",
                json={"tags": ["水果台語"]},
            )
            self.assertEqual(tagged.status_code, 200, tagged.text)
            suggested = client.post(f"/api/transcripts/{record_id}/tags/suggest")
            self.assertEqual(suggested.status_code, 200, suggested.text)
            self.assertEqual(suggested.json()["tags"], ["菜場採買"])
            self.assertIn("菜市場", recorder.text)
            self.assertNotIn("測試逐字稿", recorder.text)

    def test_missing_suggester_is_unavailable(self):
        with TemporaryDirectory() as temporary:
            _settings, _auth, _service, _root, app = build_app(temporary)
            client = authed_client(app)
            created = client.post(
                "/api/transcribe",
                files={"file": ("hello.wav", tone_wav(), "audio/wav")},
            )
            record_id = created.json()["id"]
            suggested = client.post(f"/api/transcripts/{record_id}/tags/suggest")
            self.assertEqual(suggested.status_code, 503)

    def test_ollama_error_becomes_bad_gateway(self):
        class Broken:
            def suggest(self, text):
                raise SummaryError("連不到 Ollama。")

        with TemporaryDirectory() as temporary:
            client, service, _root = _client(temporary)
            service._tag_suggester = Broken()
            created = client.post(
                "/api/transcribe",
                files={"file": ("hello.wav", tone_wav(), "audio/wav")},
            )
            suggested = client.post(f"/api/transcripts/{created.json()['id']}/tags/suggest")
            self.assertEqual(suggested.status_code, 502)
            self.assertIn("Ollama", suggested.json()["detail"])

    def test_blank_transcript_is_rejected(self):
        with TemporaryDirectory() as temporary:
            client, service, _root = _client(temporary)

            class Recorder:
                def suggest(self, text):
                    raise AssertionError("沒有內容時不該呼叫模型")

            service._tag_suggester = Recorder()
            created = client.post(
                "/api/transcribe",
                files={"file": ("hello.wav", tone_wav(), "audio/wav")},
            )
            user_id = client.get("/api/auth/me").json()["id"]
            record = service.get_transcript(user_id, created.json()["id"])
            service._stores.for_user(user_id).save(replace(record, text="  "))
            suggested = client.post(f"/api/transcripts/{record.id}/tags/suggest")
            self.assertEqual(suggested.status_code, 400)
