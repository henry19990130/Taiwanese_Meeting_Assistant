"""重點摘要的模型選擇：中文用微調版（不思考）、英文用原版；Ollama 沒有微調版時自動改用原版。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app import config
from app.services import summarizer_service as S

TRANSCRIPT = {"segments": [{"segment_id": "S0001", "start": 0, "end": 3, "speaker": "A", "text": "下週一前交報告"}]}


class _Resp:
    def __init__(self, status: int, body: dict | None = None, text: str = ""):
        self.status_code, self._body, self.text = status, body, text

    def json(self):
        return self._body


def _ok():
    return _Resp(200, {"message": {"content": '{"headline": "測試"}'}, "done_reason": "stop",
                       "prompt_eval_count": 10, "eval_count": 5, "total_duration": 1})


class SummaryModelTest(unittest.TestCase):
    def setUp(self):
        self.calls: list[tuple[str, object]] = []
        self.missing = False
        self.svc = S.SummarizerService()
        self.svc.backend = "ollama"
        self.svc.model_name = "qwen3.8:27b"

    def _post(self, _url, json=None, timeout=None):
        self.calls.append((json["model"], json.get("think")))
        if self.missing and json["model"] == "meetsum-summary":
            return _Resp(404, text='{"error":"model \'meetsum-summary\' not found"}')
        return _ok()

    def _run(self, language: str):
        with patch.object(config, "SUMMARY_MODEL", "meetsum-summary"), \
                patch.object(config, "SUMMARY_THINK", False), \
                patch.object(config, "SUMMARY_LANGS", frozenset({"zh"})), \
                patch.object(config, "LLM_THINK", True), \
                patch.object(S.httpx, "post", self._post):
            self.svc._last.model = None
            self.svc._call_ollama_with_retry(TRANSCRIPT, {}, language)
        return self.calls, self.svc.used_model

    def test_chinese_uses_finetuned_without_thinking(self):
        calls, used = self._run("zh")
        self.assertEqual(calls, [("meetsum-summary", False)])
        self.assertEqual(used, "meetsum-summary")

    def test_english_keeps_base_model_with_thinking(self):
        calls, used = self._run("en")
        self.assertEqual(calls, [("qwen3.8:27b", True)])
        self.assertEqual(used, "qwen3.8:27b")

    def test_missing_finetuned_model_falls_back_to_base(self):
        self.missing = True
        calls, used = self._run("zh")
        self.assertEqual(calls, [("meetsum-summary", False), ("qwen3.8:27b", True)])
        self.assertEqual(used, "qwen3.8:27b")

    def test_empty_summary_model_disables_it(self):
        with patch.object(config, "SUMMARY_MODEL", ""):
            self.assertEqual(self.svc.pick_model("zh"), ("qwen3.8:27b", config.LLM_THINK))

    def test_other_ollama_errors_are_not_swallowed(self):
        def boom(_url, json=None, timeout=None):
            return _Resp(500, text="internal error")
        with patch.object(config, "SUMMARY_MODEL", "meetsum-summary"), \
                patch.object(config, "SUMMARY_LANGS", frozenset({"zh"})), \
                patch.object(S.httpx, "post", boom):
            with self.assertRaises(RuntimeError):
                self.svc._call_ollama_with_retry(TRANSCRIPT, {}, "zh")


if __name__ == "__main__":
    unittest.main()
