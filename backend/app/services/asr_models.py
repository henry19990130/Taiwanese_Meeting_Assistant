"""四個會議語言各自對應一個語音模型。匯入這個模組不會下載或載入模型。"""

from __future__ import annotations

import os

from app import config  # 先讀 .env，ASR_MODEL_* 才吃得到

DEFAULT_LANGUAGE = "zh"
DEFAULT_HAKKA_DIALECT = "sixian"


def _repo(env_name: str, default: str) -> str:
    return os.getenv(env_name, "").strip() or default


# whisper_language 是 transformers 管線的 language；qwen 走官方套件，不吃這個欄位。
LANGUAGES: dict[str, dict] = {
    "zh": {
        "label": "中文（國語）",
        "model_id": _repo("ASR_MODEL_ZH", "MediaTek-Research/Breeze-ASR-25"),
        "backend": "hf",
        "whisper_language": "zh",
    },
    "nan": {
        "label": "台語",
        "model_id": _repo("ASR_MODEL_NAN", "MediaTek-Research/Breeze-ASR-26"),
        "backend": "hf",
        "whisper_language": "zh",
    },
    "hak": {
        "label": "客語",
        "model_id": _repo("ASR_MODEL_HAK", "formospeech/whisper-large-v3-taiwanese-hakka"),
        "backend": "hf",
        "whisper_language": "zh",
        "gated": True,
    },
    "en": {
        "label": "英文",
        "model_id": _repo("ASR_MODEL_EN", "Qwen/Qwen3-ASR-1.7B"),
        "backend": "qwen",
    },
}

# 值的第 0 項是畫面上的腔調名稱。
HAKKA_DIALECTS: dict[str, tuple[str, ...]] = {
    "sixian": ("四縣",),
    "hailu": ("海陸",),
    "dapu": ("大埔",),
    "raoping": ("饒平",),
    "zhaoan": ("詔安",),
    "nansixian": ("南四縣",),
}


def normalize_language(language: str | None) -> str:
    code = (language or DEFAULT_LANGUAGE).strip().lower()
    if code not in LANGUAGES:
        raise ValueError(f"會議語言只能是 {'、'.join(LANGUAGES)}")
    return code


def normalize_dialect(dialect: str | None) -> str:
    code = (dialect or DEFAULT_HAKKA_DIALECT).strip().lower()
    if code not in HAKKA_DIALECTS:
        raise ValueError(f"客語腔調只能是 {'、'.join(HAKKA_DIALECTS)}")
    return code


def model_label(language: str, dialect: str | None = None) -> str:
    return LANGUAGES[normalize_language(language)]["model_id"]


class _HuggingFaceBinding:
    """把模型 id 與語言綁在現有的 HuggingFace 引擎上。模型套件留到 load() 才匯入。"""

    def __init__(self, model_id: str, whisper_language: str):
        from taigi_asr.engines.huggingface import HuggingFaceEngine

        self._engine = HuggingFaceEngine()
        self._engine.MODEL_ID = model_id
        self._whisper_language = whisper_language

    def load(self) -> None:
        self._engine.load()

    def unload(self) -> None:
        self._engine.unload()

    def is_loaded(self) -> bool:
        return self._engine.is_loaded()

    def transcribe_clips(self, clips, sr: int = 16000, language: str | None = None) -> list[str]:
        return self._engine.transcribe_clips(clips, sr, language or self._whisper_language)


class _QwenEngine:
    """英文模型。qwen-asr 只在真正辨識時匯入。"""

    def __init__(self, model_id: str):
        self.model_id = model_id
        self._model = None

    def load(self) -> None:
        if self._model is not None:
            return
        import torch
        from qwen_asr import Qwen3ASRModel

        device = "cuda:0" if torch.cuda.is_available() else "cpu"
        dtype = torch.bfloat16 if device.startswith("cuda") else torch.float32
        self._model = Qwen3ASRModel.from_pretrained(
            self.model_id,
            dtype=dtype,
            device_map=device,
        )

    def unload(self) -> None:
        self._model = None
        try:
            import gc

            import torch

            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

    def is_loaded(self) -> bool:
        return self._model is not None

    def transcribe_clips(self, clips, sr: int = 16000, language: str | None = None) -> list[str]:
        if self._model is None:
            self.load()
        results = self._model.transcribe(
            audio=[(clip, sr) for clip in clips],
            language="English",
        )
        return [(getattr(item, "text", "") or "").strip() for item in results]


def build_engine(language: str, dialect: str | None = None):
    code = normalize_language(language)
    if code == "hak":
        normalize_dialect(dialect)
    spec = LANGUAGES[code]
    if spec["backend"] == "qwen":
        return _QwenEngine(spec["model_id"])
    return _HuggingFaceBinding(spec["model_id"], spec["whisper_language"])
