from __future__ import annotations

import re
import uuid
from pathlib import Path

from app import config
from taigi_asr.config import SUPPORTED_AUDIO_EXTS

TRANSCRIPT_EXTS = frozenset({".txt", ".srt", ".vtt", ".json"})
_HEX32 = re.compile(r"^[0-9a-fA-F]{32}$")
_UUID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def safe_storage_id(value: str) -> str:
    raw = str(value).strip()
    if _HEX32.fullmatch(raw):
        return raw.lower()
    if _UUID.fullmatch(raw):
        return uuid.UUID(raw).hex
    raise ValueError("識別碼格式不正確")


def audio_suffix(filename: str) -> str:
    ext = Path(filename or "").suffix.lower()
    if ext not in SUPPORTED_AUDIO_EXTS:
        raise ValueError("不接受的音檔格式")
    return ext


def transcript_suffix(filename: str) -> str:
    ext = Path(filename or "").suffix.lower()
    if ext not in TRANSCRIPT_EXTS:
        raise ValueError("不接受的逐字稿格式")
    return ext


def audio_destination(root: Path, meeting_id, filename: str) -> Path:
    return root / f"{safe_storage_id(str(meeting_id))}{audio_suffix(filename)}"


def too_large(num_bytes: int) -> bool:
    return num_bytes > config.MAX_UPLOAD_MB * 1024 * 1024


def unlink_inside(root: Path, path: str | None) -> bool:
    if not path:
        return False
    base = root.resolve()
    target = Path(path).resolve()
    if target == base or base not in target.parents:
        return False
    if not target.is_file():
        return False
    target.unlink()
    return True
