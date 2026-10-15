import hashlib
import hmac
import re
import secrets

MIN_PASSWORD_LENGTH = 12
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,32}$")
_ITERATIONS = 260_000
_DUMMY_HASH = None


class PasswordError(Exception):
    pass


def validate_username(username: str) -> str:
    cleaned = username.strip()
    if _USERNAME_RE.fullmatch(cleaned) is None:
        raise PasswordError("帳號限 3 到 32 碼，只能用英數字與底線。")
    return cleaned


def validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordError(f"密碼至少 {MIN_PASSWORD_LENGTH} 碼。")
    if not any(char.isalpha() for char in password):
        raise PasswordError("密碼需包含英文字母。")
    if not any(char.isdigit() for char in password):
        raise PasswordError("密碼需包含數字。")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        _ITERATIONS,
    )
    return f"pbkdf2_sha256${_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iteration_text, salt_hex, digest_hex = stored.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt_hex),
            int(iteration_text),
        )
        return hmac.compare_digest(digest, bytes.fromhex(digest_hex))
    except (ValueError, TypeError):
        return False


def dummy_verify(password: str) -> None:
    """帳號不存在時也做一次雜湊，降低時間差探測。"""
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password("timing-dummy-not-a-real-account")
    verify_password(password, _DUMMY_HASH)
