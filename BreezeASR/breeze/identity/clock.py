from datetime import datetime, timezone
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    """用作業系統時區。稽核時間同時寫本地與 UTC。"""

    def now(self) -> datetime:
        return datetime.now().astimezone()

    def utcnow(self) -> datetime:
        return datetime.now(timezone.utc)


def stamp(clock: Clock) -> dict[str, str]:
    local = clock.now().astimezone()
    utc = local.astimezone(timezone.utc)
    tz = local.tzname() or str(local.tzinfo)
    return {
        "time": local.isoformat(timespec="seconds"),
        "time_utc": utc.isoformat(timespec="seconds"),
        "tz": tz,
    }


def utc_iso(moment: datetime) -> str:
    """可比對的絕對時間。不同時區的 ISO 字串不能直接用文字排序。"""
    if moment.tzinfo is None:
        moment = moment.astimezone()
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")
