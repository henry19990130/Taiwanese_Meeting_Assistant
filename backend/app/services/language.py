from __future__ import annotations

import re

LATIN_WORD = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")
CJK_CHAR = re.compile(r"[㐀-鿿豈-﫿]")
EN_THRESHOLD = 0.6

SUPPORTED = ("zh", "en")


def latin_ratio(texts: list[str]) -> tuple[float, int, int]:
    joined = " ".join(t for t in texts if t)
    n_lat = len(LATIN_WORD.findall(joined))
    n_cjk = len(CJK_CHAR.findall(joined))
    total = n_lat + n_cjk
    return (n_lat / total if total else 0.5), n_lat, n_cjk


def transcript_language(transcript: dict | None) -> str:
    selected = ((transcript or {}).get("asr_info") or {}).get("language")
    if selected == "en":
        return "en"
    if selected in ("zh", "nan", "hak"):
        return "zh"
    texts = [s.get("text") or "" for s in (transcript or {}).get("segments", [])]
    ratio, n_lat, n_cjk = latin_ratio(texts)
    if n_lat + n_cjk == 0:
        return "zh"
    return "en" if ratio >= EN_THRESHOLD else "zh"
