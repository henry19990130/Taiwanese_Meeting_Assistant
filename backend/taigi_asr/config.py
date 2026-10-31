from __future__ import annotations

import os
from pathlib import Path

HUGGINGFACE_MODEL_ID = (
    os.environ.get("ASR_HF_MODEL_ID", "").strip()
    or "adi-gov-tw/Taiwan-Tongues-ASR-CE-pretrained-v1.0"
)
FASTER_WHISPER_MODEL_ID = (
    os.environ.get("ASR_FW_MODEL_ID", "").strip()
    or "adi-gov-tw/Taiwan-Tongues-ASR-CE-v1.0"
)

HF_CACHE_DIR: Path = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))

TARGET_SAMPLE_RATE = 16000
TARGET_CHANNELS = 1

SUPPORTED_AUDIO_EXTS: frozenset[str] = frozenset(
    {
        ".mp3",
        ".m4a",
        ".wav",
        ".flac",
        ".ogg",
        ".webm",
        ".mp4",
        ".mkv",
        ".mov",
        ".aac",
        ".opus",
        ".wma",
    }
)

DEFAULT_BEAM_SIZE = 5
MAX_BEAM_SIZE_4GB = 12
DEFAULT_BEST_OF = 5
DEFAULT_PATIENCE = 1.0
DEFAULT_TEMPERATURE = 0.0
DEFAULT_VAD_MIN_SILENCE_MS = 500
DEFAULT_VAD_SPEECH_PAD_MS = 200
DEFAULT_LANGUAGE = "zh"
DEFAULT_CHUNK_LENGTH_S = 30
DEFAULT_STRIDE_LENGTH_S = (4, 2)
DEFAULT_NO_REPEAT_NGRAM_SIZE = 3
DEFAULT_MAX_NEW_TOKENS = 440

GRADIO_HOST = os.environ.get("TAIGI_ASR_HOST", "127.0.0.1")


def _parse_port(raw: str | None, default: int = 7860) -> int:
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        import logging

        logging.getLogger(__name__).warning(
            "TAIGI_ASR_PORT=%r is not a valid integer, falling back to %d", raw, default
        )
        return default


GRADIO_PORT = _parse_port(os.environ.get("TAIGI_ASR_PORT"))
