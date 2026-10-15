import json
import re
from datetime import datetime
from pathlib import Path

from breeze.meeting_summary.sqlite_log import SqliteSummaryLog


_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_ACTIONS = frozenset({"edit", "regenerate", "delete"})


class SummaryJournal:
    """同一份摘要日誌同時寫入 JSON 與 SQLite。每次改動都留下被換掉的全文。"""

    def __init__(self, root: Path, database: Path | None = None):
        self._root = root
        self._sqlite = SqliteSummaryLog(database or (root / "journal.sqlite"))

    def read(self, owner_id: str, transcript_id: str) -> dict[str, object]:
        self._import_json(owner_id, transcript_id)
        return _public(self._sqlite.list(owner_id, transcript_id))

    def record(
        self,
        owner_id: str,
        transcript_id: str,
        action: str,
        previous: str,
    ) -> dict[str, object]:
        if action not in _ACTIONS:
            raise ValueError(f"不支援的摘要日誌動作：{action}")
        self._import_json(owner_id, transcript_id)
        at = datetime.now().astimezone().isoformat(timespec="seconds")
        payload = self._load_json(owner_id, transcript_id)
        if not payload["original"] and previous.strip():
            payload["original"] = previous
        payload["entries"].append(
            {
                "action": action,
                "at": at,
                "summary": previous,
            }
        )
        self._save_json(owner_id, transcript_id, payload)
        self._sqlite.append(owner_id, transcript_id, action, previous, at)
        return _public(self._sqlite.list(owner_id, transcript_id))

    def delete(self, owner_id: str, transcript_id: str) -> None:
        path = self._json_path(owner_id, transcript_id)
        if path.is_file():
            path.unlink()
        self._sqlite.delete(owner_id, transcript_id)

    def _import_json(self, owner_id: str, transcript_id: str) -> None:
        if self._sqlite.count(owner_id, transcript_id) > 0:
            return
        payload = self._load_json(owner_id, transcript_id)
        entries = payload["entries"]
        if not entries:
            return
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            action = entry.get("action")
            if action not in _ACTIONS:
                continue
            summary = entry.get("summary") if isinstance(entry.get("summary"), str) else ""
            if not summary and index == 0:
                summary = str(payload["original"] or "")
            at = entry.get("at") if isinstance(entry.get("at"), str) else ""
            self._sqlite.append(owner_id, transcript_id, action, summary, at)

    def _load_json(self, owner_id: str, transcript_id: str) -> dict[str, object]:
        path = self._json_path(owner_id, transcript_id)
        if not path.is_file():
            return {"original": "", "entries": []}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"original": "", "entries": []}
        if not isinstance(payload, dict):
            return {"original": "", "entries": []}
        original = payload.get("original")
        entries = payload.get("entries")
        return {
            "original": original if isinstance(original, str) else "",
            "entries": entries if isinstance(entries, list) else [],
        }

    def _save_json(self, owner_id: str, transcript_id: str, payload: dict[str, object]) -> None:
        path = self._json_path(owner_id, transcript_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)

    def _json_path(self, owner_id: str, transcript_id: str) -> Path:
        if _ID_RE.fullmatch(owner_id) is None or _ID_RE.fullmatch(transcript_id) is None:
            raise ValueError("摘要日誌 id 不合法")
        return self._root / owner_id / f"{transcript_id}.json"


def _public(versions: list[dict[str, str]]) -> dict[str, object]:
    actions = {item["action"] for item in versions}
    original = next((item["summary"] for item in versions if item["summary"].strip()), "")
    return {
        "original": original,
        "edited": "edit" in actions,
        "regenerated": "regenerate" in actions,
        "deleted": "delete" in actions,
        "versions": versions,
    }
