from __future__ import annotations

import logging
import os
from typing import list

from taigi_asr.diarization.base import DiarizationEngine, SpeakerSegment

log = logging.getLogger(__name__)


class WhisperXEngine(DiarizationEngine):
    """whisperX 語者辨識引擎

    whisperX 整合了 whisper ASR 與 pyannote 語者辨識，
    適合資源受限環境或不想管理兩個獨立 pipeline 的場景。
    """

    def __init__(
        self,
        device: str = "cuda",
        compute_type: str = "float16",
        hf_token: str | None = None,
        asr_model: str = "large-v3",
    ) -> None:
        self.device = device
        self.compute_type = compute_type
        self.hf_token = hf_token or os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_TOKEN")
        self.asr_model = asr_model
        self._model = None
        self._diarize_model = None
        self._loaded = False

    def load(self) -> None:
        if self._loaded:
            return

        try:
            import whisperx
            import torch
        except ImportError as exc:
            raise RuntimeError(
                "whisperX 未安裝。請執行：pip install whisperx"
            ) from exc

        try:
            log.info("載入 whisperX ASR 模型：%s", self.asr_model)
            self._model = whisperx.load_model(
                self.asr_model,
                device=self.device,
                compute_type=self.compute_type,
            )

            log.info("載入 whisperX 語者辨識模型")
            self._diarize_model = whisperx.DiarizationPipeline(
                use_auth_token=self.hf_token,
                device=self.device,
            )
            self._loaded = True
            log.info("whisperX 模型載入完成")
        except Exception as exc:
            raise RuntimeError(f"載入 whisperX 模型失敗：{exc}") from exc

    def diarize(self, wav_path: str) -> list[SpeakerSegment]:
        if not self._loaded:
            self.load()
        assert self._model is not None
        assert self._diarize_model is not None

        try:
            import whisperx
            import torch

            log.debug("whisperX 轉錄：%s", wav_path)
            # 先做 ASR
            audio = whisperx.load_audio(wav_path)
            result = self._model.transcribe(audio, batch_size=16)

            # 再做語者辨識
            log.debug("whisperX 語者辨識")
            diarize_segments = self._diarize_model(audio)

            # 合併結果
            result = whisperx.assign_word_speakers(diarize_segments, result)

            segments: list[SpeakerSegment] = []
            for seg in result.get("segments", []):
                speaker = seg.get("speaker", "SPEAKER_00")
                segments.append(
                    SpeakerSegment(
                        start=float(seg["start"]),
                        end=float(seg["end"]),
                        speaker=speaker,
                    )
                )

            segments.sort(key=lambda s: s.start)
            log.info("whisperX 語者辨識完成：%d 個分段", len(segments))
            return segments
        except Exception as exc:
            raise RuntimeError(f"whisperX 推論失敗：{exc}") from exc

    def unload(self) -> None:
        if self._model is not None:
            del self._model
            self._model = None
        if self._diarize_model is not None:
            del self._diarize_model
            self._diarize_model = None
        self._loaded = False
        try:
            import torch
            import gc

            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass
        log.debug("whisperX 模型已卸載")