from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

from app import config

_SECRET_KEYS = {
    "password", "passwd", "token", "access_token", "session", "cookie",
    "password_hash", "token_hash", "authorization", "set-cookie",
}
_KEY_RE = re.compile(r"^[0-9a-f]{32}$")


def log_root() -> Path:
    override = os.environ.get("AUDIT_LOG_DIR")
    if override:
        return Path(override)
    return config.PROJECT_DIR / "logs" / "users"


def account_key(user_id=None, username: str = "") -> str:
    if user_id:
        key = UUID(str(user_id)).hex
    else:
        key = hashlib.sha256((username or "").encode()).hexdigest()[:32]
    if not _KEY_RE.fullmatch(key):
        raise ValueError("帳號日誌路徑不合法")
    return key


def _scrub(value, secrets: tuple[str, ...] = ()):
    secret_set = {s for s in secrets if s}
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if str(key).lower() in _SECRET_KEYS:
                continue
            out[key] = _scrub(item, secrets)
        return out
    if isinstance(value, list):
        return [_scrub(item, secrets) for item in value]
    if isinstance(value, str) and value in secret_set:
        return "[redacted]"
    return value


def _append(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = line if line.endswith("\n") else line + "\n"
    if path.exists() and path.stat().st_size > 0:
        with path.open("rb") as fh:
            fh.seek(-1, os.SEEK_END)
            if fh.read(1) not in (b"\n", b"\r"):
                payload = "\n" + payload
    with path.open("a", encoding="utf-8") as fh:
        fh.write(payload)


def _stamp() -> tuple[str, str]:
    tz_name = config.TIMEZONE
    now = datetime.now(ZoneInfo(tz_name))
    return now.isoformat(), tz_name


def record(
    *,
    username: str,
    ip: str,
    action: str,
    user_id=None,
    detail: dict | None = None,
    secrets: tuple[str, ...] = (),
) -> None:
    moment, tz_name = _stamp()
    event = _scrub(
        {
            "time": moment,
            "timezone": tz_name,
            "username": username,
            "ip": ip or "",
            "action": action,
            "detail": detail or {},
        },
        secrets,
    )
    text = json.dumps(event, ensure_ascii=False, default=str)
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[redacted]")
    path = log_root() / account_key(user_id, username) / "audit.jsonl"
    _append(path, text)


def record_content(
    *,
    user_id,
    username: str,
    action: str,
    previous,
    ip: str = "",
) -> None:
    moment, tz_name = _stamp()
    event = {
        "time": moment,
        "timezone": tz_name,
        "username": username,
        "ip": ip or "",
        "action": action,
        "previous": previous,
    }
    text = json.dumps(event, ensure_ascii=False, default=str)
    path = log_root() / account_key(user_id, username) / "content.jsonl"
    _append(path, text)
