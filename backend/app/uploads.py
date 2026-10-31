"""相容入口。實作在 app.security.uploads。"""

from app.security.uploads import (
    TRANSCRIPT_EXTS,
    audio_destination,
    audio_suffix,
    safe_storage_id,
    too_large,
    transcript_suffix,
    unlink_inside,
)

__all__ = [
    "TRANSCRIPT_EXTS",
    "audio_destination",
    "audio_suffix",
    "safe_storage_id",
    "too_large",
    "transcript_suffix",
    "unlink_inside",
]
