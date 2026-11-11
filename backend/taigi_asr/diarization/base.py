from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SpeakerSegment:
    """語者分段資料結構"""
    start: float      # 開始時間（秒）
    end: float        # 結束時間（秒）
    speaker: str      # 語者標籤，如 "SPEAKER_00", "SPEAKER_01"


class DiarizationEngine(ABC):
    """語者辨識引擎抽象基類"""

    @abstractmethod
    def load(self) -> None:
        """載入模型"""
        ...

    @abstractmethod
    def diarize(self, wav_path: str) -> list[SpeakerSegment]:
        """對音檔進行語者辨識

        Args:
            wav_path: 16kHz WAV 檔案路徑

        Returns:
            語者分段列表，按時間排序
        """
        ...

    @abstractmethod
    def unload(self) -> None:
        """卸載模型，釋放資源"""
        ...


def get_diarization_engine(
    engine_name: str = "pyannote",
    device: str = "cuda",
    hf_token: str | None = None,
) -> DiarizationEngine:
    """取得語者辨識引擎實例

    Args:
        engine_name: 引擎名稱 ("pyannote" 或 "whisperx")
        device: 運算裝置 ("cuda" 或 "cpu")
        hf_token: HuggingFace token（pyannote 需要）

    Returns:
        DiarizationEngine 實例
    """
    if engine_name == "pyannote":
        from taigi_asr.diarization.pyannote_engine import PyannoteEngine
        return PyannoteEngine(device=device, hf_token=hf_token)
    elif engine_name == "whisperx":
        from taigi_asr.diarization.whisperx_engine import WhisperXEngine
        return WhisperXEngine(device=device)
    else:
        raise ValueError(f"不支援的 diarization 引擎：{engine_name}")