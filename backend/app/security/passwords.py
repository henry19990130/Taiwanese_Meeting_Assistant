from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import re
import secrets

PBKDF2_ALGO = "pbkdf2_sha256"
PBKDF2_ITERATIONS = 260_000
_DKLEN = 32
LOCK_AFTER = 5
LOCK_MINUTES = 15

USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,32}$")


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _aware(value: dt.datetime | None) -> dt.datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.timezone.utc)
    return value


def validate_username(username: str) -> bool:
    return bool(USERNAME_RE.fullmatch(username or ""))


def validate_password(password: str) -> bool:
    if not isinstance(password, str) or not 12 <= len(password) <= 200:
        return False
    has_letter = any("a" <= c.lower() <= "z" for c in password)
    has_digit = any(c in "0123456789" for c in password)
    return has_letter and has_digit


def registration_error(username: str, password: str) -> str | None:
    if not validate_username(username):
        return "username"
    if not validate_password(password):
        return "password"
    return None


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS, dklen=_DKLEN)
    return f"{PBKDF2_ALGO}${PBKDF2_ITERATIONS}${_b64e(salt)}${_b64e(dk)}"


def _verify_pbkdf2(password: str, stored: str) -> bool:
    try:
        algo, rounds, salt, expected = stored.split("$")
        if algo != PBKDF2_ALGO:
            return False
        expected_b = _b64d(expected)
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), _b64d(salt), int(rounds), dklen=len(expected_b),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(dk, expected_b)


def _verify_scrypt(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, expected = stored.split("$")
        if algo != "scrypt":
            return False
        expected_b = _b64d(expected)
        dk = hashlib.scrypt(
            password.encode(), salt=_b64d(salt), n=int(n), r=int(r), p=int(p),
            dklen=len(expected_b),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(dk, expected_b)


def verify_password(password: str, stored: str) -> bool:
    if not isinstance(stored, str) or "$" not in stored:
        return False
    algo = stored.split("$", 1)[0]
    if algo == PBKDF2_ALGO:
        return _verify_pbkdf2(password, stored)
    if algo == "scrypt":
        return _verify_scrypt(password, stored)
    return False


DUMMY_PASSWORD_HASH = hash_password("dummy-password-not-used")


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def lock_is_active(locked_until: dt.datetime | None, now: dt.datetime) -> bool:
    until = _aware(locked_until)
    if until is None:
        return False
    return until > _aware(now)


def next_failure(
    failed_count: int, locked_until: dt.datetime | None, now: dt.datetime,
) -> tuple[int, dt.datetime | None, bool]:
    now = _aware(now)
    until = _aware(locked_until)
    if lock_is_active(until, now):
        return failed_count, until, True
    if until is not None:
        failed_count = 0
    failed_count += 1
    if failed_count >= LOCK_AFTER:
        return failed_count, now + dt.timedelta(minutes=LOCK_MINUTES), True
    return failed_count, None, False
