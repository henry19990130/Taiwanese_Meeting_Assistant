from dataclasses import dataclass


@dataclass(frozen=True)
class User:
    id: str
    username: str
    role: str
    created_at: str


@dataclass(frozen=True)
class AuditEvent:
    time: str
    time_utc: str
    tz: str
    account: str
    ip: str
    action: str
    detail: str
