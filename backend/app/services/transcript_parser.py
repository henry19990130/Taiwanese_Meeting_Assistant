from __future__ import annotations

import json
import re

MAX_SEGMENT_CHARS = 120

_TS = r"(?:(\d{1,2}):)?(\d{1,2}):(\d{2})(?:[.,](\d{1,3}))?"
_CUE_LINE = re.compile(rf"^\s*{_TS}\s*-->\s*{_TS}")
_TXT_RANGE = re.compile(rf"^\s*[\[(]?\s*{_TS}\s*(?:-|–|~|-->)\s*{_TS}\s*[\])]?\s*(.*)$")
_TXT_START = re.compile(rf"^\s*[\[(]?\s*{_TS}\s*[\])]?\s+(.*)$")
_SENTENCE_END = re.compile(r"(?<=[。！？!?；;])")


class TranscriptParseError(ValueError):
    pass


def parse_transcript(data: bytes, filename: str) -> list[dict]:
    text = _decode(data)
    ext = (filename.rsplit(".", 1)[-1] if "." in filename else "").lower()
    stripped = text.lstrip()

    if ext == "json" or stripped.startswith("{") or (stripped.startswith("[") and _looks_like_json(text)):
        segs = _parse_json(text)
    elif ext in ("srt", "vtt") or "-->" in text:
        segs = _parse_cues(text)
    else:
        segs = _parse_txt(text)

    segs = [s for s in segs if s["text"]]
    if not segs:
        raise TranscriptParseError("逐字稿檔案裡沒有可用的文字")
    return [{**s, "segment_index": i} for i, s in enumerate(segs)]


def _looks_like_json(text: str) -> bool:
    try:
        json.loads(text)
        return True
    except ValueError:
        return False


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp950", "big5hkscs"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise TranscriptParseError("無法辨識檔案編碼，請存成 UTF-8 文字檔")


def _ms(groups) -> int:
    h, m, s, frac = groups
    ms = int((frac or "0").ljust(3, "0")[:3])
    return ((int(h or 0) * 60 + int(m)) * 60 + int(s)) * 1000 + ms


_CJK = re.compile(r"[\u3000-\u303f\u3400-\u9fff\uff00-\uffef]")


def _join(parts: list[str]) -> str:
    out = ""
    for p in (x.strip() for x in parts):
        if not p:
            continue
        if out and not (_CJK.match(out[-1]) or _CJK.match(p[0])):
            out += " "
        out += p
    return out


def _seg(start, end, text) -> dict:
    return {"start_ms": start, "end_ms": end, "text": _join(text.split())}


def _parse_cues(text: str) -> list[dict]:
    segs = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
        lines = [ln for ln in block.strip().split("\n") if ln.strip()]
        for i, ln in enumerate(lines):
            m = _CUE_LINE.match(ln)
            if m:
                g = m.groups()
                body = _join([re.sub(r"<[^>]+>", "", x) for x in lines[i + 1:]])
                segs.append(_seg(_ms(g[0:4]), _ms(g[4:8]), body))
                break
    if not segs:
        raise TranscriptParseError("字幕檔格式無法辨識")
    return segs


def _parse_json(text: str) -> list[dict]:
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise TranscriptParseError(f"JSON 格式錯誤：{exc}") from exc
    items = data.get("segments") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise TranscriptParseError("JSON 裡找不到 segments 清單")
    segs = []
    for it in items:
        if not isinstance(it, dict) or not str(it.get("text", "")).strip():
            continue
        if "start_ms" in it or "end_ms" in it:
            start, end = it.get("start_ms"), it.get("end_ms")
        else:
            start = round(float(it["start"]) * 1000) if it.get("start") is not None else None
            end = round(float(it["end"]) * 1000) if it.get("end") is not None else None
        segs.append(_seg(_int_or_none(start), _int_or_none(end), str(it["text"])))
    return segs


def _int_or_none(v):
    return int(v) if v is not None else None


def _parse_txt(text: str) -> list[dict]:
    lines = [ln.strip() for ln in text.replace("\r\n", "\n").split("\n") if ln.strip()]
    timed = []
    for ln in lines:
        m = _TXT_RANGE.match(ln)
        if m:
            g = m.groups()
            timed.append((_ms(g[0:4]), _ms(g[4:8]), g[8]))
            continue
        m = _TXT_START.match(ln)
        if m:
            g = m.groups()
            timed.append((_ms(g[0:4]), None, g[4]))
            continue
        timed.append((None, None, ln))

    has_time = sum(1 for s, _, _ in timed if s is not None) >= max(1, len(timed) // 2)
    if not has_time:
        segs = []
        for _, _, ln in timed:
            for piece in _split_sentences(ln):
                segs.append(_seg(None, None, piece))
        return segs

    segs = []
    for i, (start, end, body) in enumerate(timed):
        if start is not None and end is None:
            nxt = next((t[0] for t in timed[i + 1:] if t[0] is not None), None)
            end = nxt if nxt is not None and nxt >= start else None
        segs.append(_seg(start, end, body))
    return segs


def _split_sentences(line: str) -> list[str]:
    if len(line) <= MAX_SEGMENT_CHARS:
        return [line]
    parts, buf = [], ""
    for sent in (p for p in _SENTENCE_END.split(line) if p):
        if buf and len(buf) + len(sent) > MAX_SEGMENT_CHARS:
            parts.append(buf)
            buf = ""
        buf += sent
        while len(buf) > MAX_SEGMENT_CHARS * 1.5:
            parts.append(buf[:MAX_SEGMENT_CHARS])
            buf = buf[MAX_SEGMENT_CHARS:]
    if buf:
        parts.append(buf)
    return parts
