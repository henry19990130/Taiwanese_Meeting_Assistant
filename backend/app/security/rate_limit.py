"""登入、註冊、上傳、摘要、小幫手的記憶體速率限制。行程重啟後計數歸零。"""

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
}


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()

    def allow(self, key: str, limit: int, window_seconds: float) -> bool:
        now = time.monotonic()
        with self._lock:
            recent = [stamp for stamp in self._hits.get(key, []) if now - stamp < window_seconds]
            if len(recent) >= limit:
                self._hits[key] = recent
                return False
            recent.append(now)
            self._hits[key] = recent
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
