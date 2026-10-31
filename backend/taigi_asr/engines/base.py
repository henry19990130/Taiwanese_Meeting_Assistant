from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from taigi_asr.segments import TimestampedSegment


@runtime_checkable
class ASREngine(Protocol):

    def load(self) -> None:
        ...

    def is_loaded(self) -> bool:
        ...

    def transcribe(
        self,
        wav_path: str | Path,
        *,
        word_timestamps: bool = False,
    ) -> list[TimestampedSegment]:
        ...

    def unload(self) -> None:
        ...
