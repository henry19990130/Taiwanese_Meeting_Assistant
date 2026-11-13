"""顯示卡管家與英文語音模型分批：不需要顯示卡也能跑。"""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DB_USER", "x")
os.environ.setdefault("DB_PASSWORD", "verify-only-12345")

from app import config  # noqa: E402
from app.services import asr_models, gpu_guard  # noqa: E402


class GpuGuardTest(unittest.TestCase):
    def test_enough_memory_keeps_llm(self):
        with mock.patch.object(gpu_guard, "free_mb", return_value=20000), \
             mock.patch.object(gpu_guard, "unload_llm") as unload:
            self.assertFalse(gpu_guard.make_room_for_asr("zh"))
            unload.assert_not_called()

    def test_not_enough_memory_unloads_llm(self):
        with mock.patch.object(gpu_guard, "free_mb", return_value=4000), \
             mock.patch.object(gpu_guard, "unload_llm", return_value=["meetsum-summary:latest"]) as unload:
            self.assertTrue(gpu_guard.make_room_for_asr("zh"))
            unload.assert_called_once()

    def test_no_gpu_or_disabled_does_nothing(self):
        with mock.patch.object(gpu_guard, "free_mb", return_value=None), \
             mock.patch.object(gpu_guard, "unload_llm") as unload:
            self.assertFalse(gpu_guard.make_room_for_asr("en"))
            unload.assert_not_called()
        with mock.patch.object(config, "ASR_GPU_GUARD", False), \
             mock.patch.object(gpu_guard, "free_mb", return_value=10), \
             mock.patch.object(gpu_guard, "unload_llm") as unload:
            self.assertFalse(gpu_guard.make_room_for_asr("zh"))
            unload.assert_not_called()

    def test_need_override(self):
        with mock.patch.object(config, "ASR_VRAM_NEED_MB", 1234):
            self.assertEqual(gpu_guard.need_mb("zh"), 1234)

    def test_keep_alive_is_number_for_minus_one(self):
        self.assertEqual(config.LLM_KEEP_ALIVE, -1)


class QwenBatchTest(unittest.TestCase):
    def test_english_clips_sent_in_batches(self):
        calls = []

        class Item:
            def __init__(self, t):
                self.text = t

        class FakeModel:
            def transcribe(self, audio, language):
                calls.append(len(audio))
                return [Item(f"t{len(calls)}-{i}") for i in range(len(audio))]

        eng = asr_models._QwenEngine("fake")
        eng._model = FakeModel()
        with mock.patch.object(config, "ASR_BATCH_SIZE", 4):
            out = eng.transcribe_clips([0] * 10)
        self.assertEqual(calls, [4, 4, 2])
        self.assertEqual(len(out), 10)


if __name__ == "__main__":
    unittest.main()
