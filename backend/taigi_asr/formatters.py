from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from taigi_asr.segments import TimestampedSegment


def to_txt(segments: Sequence[TimestampedSegment]) -> str:
    if not segments:
        return ""
    return "".join(seg.to_timestamp_line() + "\n" for seg in segments)


def to_srt(segments: Sequence[TimestampedSegment]) -> str:
    if not segments:
        return ""
    blocks = [seg.to_srt_block(idx) for idx, seg in enumerate(segments, 1)]
    return "\n".join(blocks) + "\n"


def to_vtt(segments: Sequence[TimestampedSegment]) -> str:
    if not segments:
        return "WEBVTT\n\n"
    body = "\n".join(seg.to_vtt_block() for seg in segments)
    return f"WEBVTT\n\n{body}"


def to_json(
    segments: Sequence[TimestampedSegment],
    meta: Mapping[str, Any] | None = None,
) -> str:
    payload: dict[str, Any] = {"segments": [seg.to_json_dict() for seg in segments]}
    if meta is not None:
        payload["meta"] = dict(meta)
    return json.dumps(payload, ensure_ascii=False, indent=2)
