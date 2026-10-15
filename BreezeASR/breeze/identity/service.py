import secrets
import uuid
from datetime import timedelta

from breeze.identity.clock import Clock, SystemClock, stamp
from breeze.identity.models import AuditEvent, User
from breeze.identity.passwords import (
    MIN_PASSWORD_LENGTH,
    PasswordError,
    dummy_verify,
    hash_password,
    validate_password,
    validate_username,
    verify_password,
)
from breeze.identity.store import DuplicateUsername, IdentityStore

LOGIN_FAILED = "帳號或密碼錯誤"
DEFAULT_ROLE = "user"
COOKIE_NAME = "breeze_session"


class AuthError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


class AuthService:
    """註冊、登入、鎖定、session、稽核。不碰逐字稿。"""

    def __init__(
        self,
        store: IdentityStore,
        *,
        clock: Clock | None = None,
        max_failures: int = 5,
        lockout_seconds: int = 15 * 60,
        session_hours: int = 12,
    ):
        self._store = store
        self._clock = clock or SystemClock()
        self._max_failures = max_failures
        self._lockout_seconds = lockout_seconds
        self._session_hours = session_hours

    @property
    def lockout_minutes(self) -> int:
        return max(1, self._lockout_seconds // 60)

    @property
    def session_max_age(self) -> int:
        return self._session_hours * 3600

    def register(self, username: str, password: str, ip: str) -> tuple[User, str]:
        try:
            username = validate_username(username)
            validate_password(password)
        except PasswordError as exc:
            raise AuthError(str(exc)) from exc

        marks = stamp(self._clock)
        user = User(
            id=uuid.uuid4().hex,
            username=username,
            role=DEFAULT_ROLE,
            created_at=marks["time"],
        )
        try:
            self._store.create_user(user, hash_password(password))
        except DuplicateUsername as exc:
            self._audit(username, ip, "register_rejected", "duplicate_username")
            raise AuthError("這個帳號已被使用", status_code=409) from exc

        self._audit(username, ip, "account_created", f"user_id={user.id};role={user.role}")
        token = self._start_session(user)
        self._audit(username, ip, "login_success", "registered_and_signed_in")
        return user, token

    def login(self, username: str, password: str, ip: str) -> tuple[User, str]:
        account = username.strip() or "-"
        if self._is_locked(f"ip:{ip}") or self._is_locked(f"user:{account.lower()}"):
            self._audit(account, ip, "login_blocked", "locked")
            raise AuthError(self._lock_message(), status_code=423)

        user = self._store.get_user_by_username(account) if account != "-" else None
        if user is None:
            dummy_verify(password)
            self._register_failure(account, ip)
            self._audit(account, ip, "login_failure", "unknown_or_invalid")
            raise AuthError(LOGIN_FAILED, status_code=401)

        stored = self._store.password_hash_for(user.id) or ""
        if not verify_password(password, stored):
            self._register_failure(account, ip)
            self._audit(user.username, ip, "login_failure", "unknown_or_invalid")
            raise AuthError(LOGIN_FAILED, status_code=401)

        self._store.clear_lockout(f"user:{user.username.lower()}")
        token = self._start_session(user)
        self._audit(user.username, ip, "login_success", f"user_id={user.id}")
        return user, token

    def logout(self, token: str | None, ip: str) -> None:
        user = self.user_for_token(token)
        if token:
            self._store.delete_session(token)
        account = user.username if user else "-"
        self._audit(account, ip, "logout", "session_ended")

    def user_for_token(self, token: str | None) -> User | None:
        if not token:
            return None
        marks = stamp(self._clock)
        user_id = self._store.session_user_id(token, marks["time"])
        if user_id is None:
            return None
        return self._store.get_user_by_id(user_id)

    def change_role(self, actor: User, target_username: str, role: str, ip: str) -> User:
        if actor.role != "admin":
            self._audit(actor.username, ip, "permission_denied", "change_role")
            raise AuthError("沒有權限變更角色", status_code=403)
        target = self._store.get_user_by_username(target_username)
        if target is None:
            raise AuthError("找不到使用者", status_code=404)
        previous = target.role
        updated = self._store.set_role(target.id, role)
        if updated is None:
            raise AuthError("找不到使用者", status_code=404)
        self._audit(
            actor.username,
            ip,
            "permission_change",
            f"target={updated.username};from={previous};to={updated.role}",
        )
        return updated

    def recent_logs(self, limit: int = 100) -> list[AuditEvent]:
        return self._store.list_audit(limit)

    def _start_session(self, user: User) -> str:
        marks = stamp(self._clock)
        expires = (self._clock.now() + timedelta(hours=self._session_hours)).isoformat(
            timespec="seconds"
        )
        token = secrets.token_urlsafe(32)
        self._store.drop_sessions_for_user(user.id)
        self._store.create_session(token, user.id, marks["time"], expires)
        return token

    def _register_failure(self, account: str, ip: str) -> None:
        self._bump(f"user:{account.lower()}")
        self._bump(f"ip:{ip}")

    def _bump(self, key: str) -> None:
        marks = stamp(self._clock)
        failures, locked_until = self._store.lockout(key)
        if locked_until and locked_until > marks["time"]:
            return
        failures += 1
        locked = None
        if failures >= self._max_failures:
            locked = (self._clock.now() + timedelta(seconds=self._lockout_seconds)).isoformat(
                timespec="seconds"
            )
            failures = 0
            self._audit(key, "-", "lockout", f"until={locked}")
        self._store.set_lockout(key, failures, locked, marks["time"])

    def _is_locked(self, key: str) -> bool:
        _failures, locked_until = self._store.lockout(key)
        if not locked_until:
            return False
        return locked_until > stamp(self._clock)["time"]

    def _lock_message(self) -> str:
        return f"嘗試次數過多，請 {self.lockout_minutes} 分鐘後再試"

    def _audit(self, account: str, ip: str, action: str, detail: str) -> None:
        marks = stamp(self._clock)
        self._store.append_audit(
            AuditEvent(
                time=marks["time"],
                time_utc=marks["time_utc"],
                tz=marks["tz"],
                account=account,
                ip=ip,
                action=action,
                detail=detail,
            )
        )


# re-export for settings/docs
PASSWORD_MIN_LENGTH = MIN_PASSWORD_LENGTH
