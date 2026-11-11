"""登入、註冊、上傳、摘要、小幫手，以及換發憑證、讀會議、詞彙庫的記憶體速率限制。行程重啟後計數歸零。"""

from __future__ import annotations

import threading
import time

from fastapi import Request

from app.deps import api_error, client_ip

_LIMITS = {
    "login": (20, 60),
    "register": (10, 60),
    "upload": (30, 3600),
    "summary": (10, 3600),
    "assistant": (30, 60),
    "refresh": (30, 60),
    # 會議狀態每 2 秒查一次，每分鐘 30 次。120 次留得出讀逐字稿和重點的餘裕。
    "meeting_read": (120, 60),
    "glossary": (60, 60),
    "proofread": (10, 3600),
    "delete_meeting": (30, 3600),
}


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, tuple[float, list[float]]] = {}
        self._lock = threading.Lock()

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()

    def _drop_expired(self, now: float) -> None:
        stale = [
            key for key, (window, stamps) in self._hits.items()
            if not stamps or now - stamps[-1] >= window
        ]
        for key in stale:
            del self._hits[key]

    def allow(self, key: str, limit: int, window_seconds: float) -> bool:
        now = time.monotonic()
        with self._lock:
            self._drop_expired(now)
            _window, stamps = self._hits.get(key, (window_seconds, []))
            recent = [stamp for stamp in stamps if now - stamp < window_seconds]
            if len(recent) >= limit:
                if recent:
                    self._hits[key] = (window_seconds, recent)
                else:
                    self._hits.pop(key, None)
                return False
            recent.append(now)
            self._hits[key] = (window_seconds, recent)
            return True


limiter = RateLimiter()


def _enforce(bucket: str, identity: str) -> None:
    limit, window = _LIMITS[bucket]
    if limiter.allow(f"{bucket}:{identity}", limit, window):
        return
    raise api_error(429, "RATE_LIMITED", "操作太頻繁，請稍後再試")


def limit_login(request: Request) -> None:
    _enforce("login", client_ip(request))


def limit_register(request: Request) -> None:
    _enforce("register", client_ip(request))


def limit_upload(request: Request, user: dict) -> None:
    _enforce("upload", str(user["id"]))


def limit_summary(request: Request, user: dict) -> None:
    _enforce("summary", str(user["id"]))


def limit_assistant(request: Request, user: dict) -> None:
    _enforce("assistant", str(user["id"]))


def limit_refresh(request: Request) -> None:
    _enforce("refresh", client_ip(request))


def limit_meeting_read(request: Request, user: dict) -> None:
    _enforce("meeting_read", str(user["id"]))


def limit_glossary(request: Request, user: dict) -> None:
    _enforce("glossary", str(user["id"]))


def limit_proofread(request: Request, user: dict) -> None:
    _enforce("proofread", str(user["id"]))


def limit_delete_meeting(request: Request, user: dict) -> None:
    _enforce("delete_meeting", str(user["id"]))
