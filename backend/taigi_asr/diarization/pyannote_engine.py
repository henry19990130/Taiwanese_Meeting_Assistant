from __future__ import annotations

import logging
import os

from taigi_asr.diarization.base import DiarizationEngine, SpeakerSegment

log = logging.getLogger(__name__)


class PyannoteEngine(DiarizationEngine):
    """pyannote.audio 3.x 語者辨識引擎

    使用 pyannote/speaker-diarization-3.1 模型。
    需要 HuggingFace token（需先在 HF 接受授權條款）。
    """

    def __init__(
        self,
        device: str = "cuda",
        hf_token: str | None = None,
        pipeline_name: str = "pyannote/speaker-diarization-3.1",
    ) -> None:
        self.device = device
        self.hf_token = hf_token or os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_TOKEN")
        self.pipeline_name = pipeline_name
        self._pipeline = None
        self._loaded = False

    def load(self) -> None:
        if self._loaded:
            return

        try:
            import torch
            from pyannote.audio import Pipeline
        except ImportError as exc:
            raise RuntimeError(
                "pyannote.audio 未安裝。請執行：pip install pyannote.audio"
            ) from exc

        if not self.hf_token:
            log.warning(
                "未提供 HF_TOKEN，pyannote 需要 HuggingFace token（需先在 "
                "https://huggingface.co/pyannote/speaker-diarization-3.1 接受授權）。"
            )

        try:
            log.info("載入 pyannote 語者辨識模型：%s 到 %s", self.pipeline_name, self.device)
            self._pipeline = Pipeline.from_pretrained(
                self.pipeline_name,
                use_auth_token=self.hf_token,
            ).to(torch.device(self.device))
            self._loaded = True
            log.info("pyannote 語者辨識模型載入完成")
        except Exception as exc:
            raise RuntimeError(f"載入 pyannote 模型失敗：{exc}") from exc

    def diarize(self, wav_path: str) -> list[SpeakerSegment]:
        if not self._loaded:
            self.load()
        assert self._pipeline is not None

        try:
            log.debug("執行語者辨識：%s", wav_path)
            diarization = self._pipeline(wav_path)

            segments: list[SpeakerSegment] = []
            for turn, _, speaker in diarization.itertracks(yield_label=True):
                segments.append(
                    SpeakerSegment(
                        start=float(turn.start),
                        end=float(turn.end),
                        speaker=speaker,
                    )
                )

            # 確保按時間排序
            segments.sort(key=lambda s: s.start)
            log.info("語者辨識完成：%d 個語者分段", len(segments))
            return segments
        except Exception as exc:
            raise RuntimeError(f"語者辨識推論失敗：{exc}") from exc

    def unload(self) -> None:
        if self._pipeline is not None:
            del self._pipeline
            self._pipeline = None
        self._loaded = False
        try:
            import torch
            import gc

            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass
        log.debug("pyannote 模型已卸載")


class PyannoteEngineV2(DiarizationEngine):
    """pyannote.audio 2.x 相容引擎（備用）"""

    def __init__(
        self,
        device: str = "cuda",
        hf_token: str | None = None,
    ) -> None:
        self.device = device
        self.hf_token = hf_token or os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_TOKEN")
        self._pipeline = None
        self._loaded = False

    def load(self) -> None:
        if self._loaded:
            return
        try:
            import torch
            from pyannote.audio import Pipeline
        except ImportError as exc:
            raise RuntimeError("pyannote.audio 未安裝") from exc

        try:
            log.info("載入 pyannote v2 語者辨識模型")
            self._pipeline = Pipeline.from_pretrained(
                "pyannote/speaker-diarization",
                use_auth_token=self.hf_token,
            ).to(torch.device(self.device))
            self._loaded = True
        except Exception as exc:
            raise RuntimeError(f"載入 pyannote v2 模型失敗：{exc}") from exc

    def diarize(self, wav_path: str) -> list[SpeakerSegment]:
        if not self._loaded:
            self.load()
        assert self._pipeline is not None

        try:
            diarization = self._pipeline(wav_path)
            segments: list[SpeakerSegment] = []
            for turn, _, speaker in diarization.itertracks(yield_label=True):
                segments.append(
                    SpeakerSegment(
                        start=float(turn.start),
                        end=float(turn.end),
                        speaker=speaker,
                    )
                )
            segments.sort(key=lambda s: s.start)
            return segments
        except Exception as exc:
            raise RuntimeError(f"語者辨識推論失敗：{exc}") from exc

    def unload(self) -> None:
        if self._pipeline is not None:
            del self._pipeline
            self._pipeline = None
        self._loaded = False
        try:
            import torch
            import gc

            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass