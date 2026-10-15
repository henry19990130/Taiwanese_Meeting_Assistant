import json
import re
from dataclasses import asdict
from pathlib import Path

from breeze.models import Transcript


_ID_RE = re.compile(r"^[0-9a-f]{32}$")


class UserTranscriptStores:
    """每個使用者一個資料夾，帳號之間看不到彼此的 JSON。"""

    def __init__(self, root: Path):
        self._root = root

    def for_user(self, user_id: str) -> "JsonTranscriptStore":
        if _ID_RE.fullmatch(user_id) is None:
            raise ValueError("使用者 id 不合法")
        return JsonTranscriptStore(self._root / user_id)


class JsonTranscriptStore:
    """一筆逐字稿一個 JSON 檔。檔名就是 id，避免路徑穿越。"""

    def __init__(self, directory: Path):
        self._directory = directory

    def save(self, transcript: Transcript) -> Transcript:
        path = self._path(transcript.id)
        if path is None:
            raise ValueError(f"逐字稿 id 不合法：{transcript.id}")
        self._directory.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(asdict(transcript), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(path)
        return transcript

    def list_all(self) -> list[Transcript]:
        if not self._directory.is_dir():
            return []
        records: list[Transcript] = []
        for path in self._directory.glob("*.json"):
            record = self._read(path)
            if record is not None:
                records.append(record)
        records.sort(key=lambda item: item.created_at, reverse=True)
        return records

    def get(self, transcript_id: str) -> Transcript | None:
        path = self._path(transcript_id)
        if path is None or not path.is_file():
            return None
        return self._read(path)

    def delete(self, transcript_id: str) -> bool:
        path = self._path(transcript_id)
        if path is None or not path.is_file():
            return False
        path.unlink()
        return True

    def _path(self, transcript_id: str) -> Path | None:
        if _ID_RE.fullmatch(transcript_id) is None:
            return None
        return self._directory / f"{transcript_id}.json"

    def _read(self, path: Path) -> Transcript | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            record = Transcript(
                id=str(payload["id"]),
                source_filename=str(payload["source_filename"]),
                text=str(payload["text"]),
                model=str(payload["model"]),
                device=str(payload["device"]),
                created_at=str(payload["created_at"]),
                title=str(payload.get("title") or "").strip(),
                tags=_read_tags(payload),
                summary_filename=str(payload.get("summary_filename") or ""),
            )
        except (OSError, json.JSONDecodeError, KeyError, TypeError):
            return None
        if record.id != path.stem:
            return None
        return record


def _read_tags(payload: dict) -> tuple[str, ...]:
    raw = payload.get("tags", [])
    if not isinstance(raw, list):
        return ()
    tags: list[str] = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            tags.append(item.strip())
    return tuple(tags)
