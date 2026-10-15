from pathlib import Path

from breeze.meeting_summary.errors import SummaryError

ALLOWED_SUFFIXES = {".txt", ".md"}


def read_transcript_file(path: Path) -> str:
    if not path.is_file():
        raise SummaryError(f"找不到逐字稿：{path}")
    if path.suffix.lower() not in ALLOWED_SUFFIXES:
        raise SummaryError("只接受 .txt 或 .md 逐字稿。")
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise SummaryError("逐字稿必須是 UTF-8 文字檔。") from exc
    if not text.strip():
        raise SummaryError("逐字稿是空的。")
    return text
