from __future__ import annotations

import secrets
import time
import urllib.parse

import httpx
from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import RedirectResponse
from psycopg.errors import UniqueViolation
from pydantic import BaseModel, Field

from app import audit, config
from app.db import get_conn
from app.deps import api_error, client_ip, get_current_user
from app.repositories import sessions, users
from app.security import (
    DUMMY_PASSWORD_HASH,
    hash_password,
    hash_token,
    new_session_token,
    normalize_display_name,
    registration_error,
    validate_display_name,
    validate_password,
    validate_username,
    verify_password,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

_COOKIE = "session"
_INVALID = "帳號或密碼錯誤"
_LOCKED = "已達 5 次上限，請 15 分鐘後再試"


class LoginRequest(BaseModel):
    username: str = Field(min_length=0, max_length=200)
    password: str = Field(min_length=0, max_length=200)


class RegisterRequest(BaseModel):
    username: str = Field(min_length=0, max_length=200)
    password: str = Field(min_length=0, max_length=200)
    display_name: str = Field(default="", max_length=200)


_USERNAME_MSG = "帳號只允許 3 到 32 碼的英數字或底線"
_PASSWORD_MSG = "密碼至少 12 碼，而且要同時含英文字母和數字"
_EXISTS_MSG = "這個帳號已經有人使用"
_DISPLAY_MSG = "稱呼最多 20 個字"


def _user_out(user: dict) -> dict:
    return {
        "id": str(user["id"]),
        "username": user["username"],
        "display_name": user.get("display_name") or None,
    }


def _open_session(conn, user: dict) -> str:
    token = new_session_token()
    sessions.delete_expired(conn)
    sessions.create_session(conn, hash_token(token), user["id"], config.SESSION_TTL_SECONDS)
    return token


def _session_body(response: Response, user: dict, token: str) -> dict:
    response.set_cookie(
        key=_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        path="/",
        max_age=config.SESSION_TTL_SECONDS,
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": config.SESSION_TTL_SECONDS,
        "user": _user_out(user),
    }


def _reject(username: str, ip: str, password: str, *, action: str, reason: str, message: str) -> None:
    audit.record(
        username=username,
        ip=ip,
        action=action,
        detail={"reason": reason},
        secrets=(password,),
    )
    raise api_error(status.HTTP_401_UNAUTHORIZED, "INVALID_CREDENTIALS", message)


@router.post("/login")
def login(body: LoginRequest, request: Request, response: Response) -> dict:
    username = body.username.strip()
    password = body.password
    ip = client_ip(request)
    failure: tuple[str, str] | None = None
    token = ""
    with get_conn() as conn:
        user = users.get_by_username(conn, username) if validate_username(username) else None
        if user is None:
            verify_password(password, DUMMY_PASSWORD_HASH)
            failure = ("登入失敗", "invalid_credentials")
        elif users.lock_active(users.get_lock(conn, username)):
            verify_password(password, user["password_hash"])
            failure = ("鎖定", "locked")
        elif not validate_password(password):
            verify_password(password, DUMMY_PASSWORD_HASH)
            failure = ("登入失敗", "invalid_credentials")
        elif not verify_password(password, user["password_hash"]):
            state = users.record_login_failure(conn, username)
            failure = ("鎖定", "locked") if state["locked"] else ("登入失敗", "invalid_credentials")
        else:
            users.clear_login_failures(conn, username)
            token = _open_session(conn, user)
    if failure is not None:
        _reject(
            username, ip, password,
            action=failure[0],
            reason=failure[1],
            message=_LOCKED if failure[1] == "locked" else _INVALID,
        )
    audit.record(
        user_id=user["id"],
        username=user["username"],
        ip=ip,
        action="登入成功",
        detail={},
        secrets=(password, token),
    )
    return _session_body(response, user, token)


@router.post("/register")
def register(body: RegisterRequest, request: Request, response: Response) -> dict:
    username = body.username.strip()
    password = body.password
    ip = client_ip(request)
    reason = registration_error(username, password)
    if reason is None and not validate_display_name(body.display_name):
        reason = "display_name"
    if reason is not None:
        audit.record(
            username=username,
            ip=ip,
            action="註冊被拒",
            detail={"reason": reason},
            secrets=(password,),
        )
        if reason == "username":
            raise api_error(422, "INVALID_USERNAME", _USERNAME_MSG)
        if reason == "display_name":
            raise api_error(422, "INVALID_DISPLAY_NAME", _DISPLAY_MSG)
        raise api_error(422, "INVALID_PASSWORD", _PASSWORD_MSG)

    user = None
    token = ""
    taken = False
    try:
        with get_conn() as conn:
            if users.get_by_username(conn, username) is not None:
                taken = True
            else:
                user = users.create_user(
                    conn, username, hash_password(password),
                    display_name=normalize_display_name(body.display_name),
                )
                token = _open_session(conn, user)
    except UniqueViolation:
        taken = True
    if taken:
        audit.record(
            username=username,
            ip=ip,
            action="註冊被拒",
            detail={"reason": "exists"},
            secrets=(password,),
        )
        raise api_error(status.HTTP_409_CONFLICT, "ACCOUNT_EXISTS", _EXISTS_MSG)
    audit.record(
        user_id=user["id"],
        username=user["username"],
        ip=ip,
        action="建立帳號",
        detail={},
        secrets=(password, token),
    )
    return _session_body(response, user, token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, user: dict = Depends(get_current_user)) -> Response:
    with get_conn() as conn:
        sessions.delete_session(conn, user["token_hash"])
    audit.record(
        user_id=user["id"],
        username=user["username"],
        ip=client_ip(request),
        action="登出",
        detail={},
    )
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(_COOKIE, path="/")
    return response


@router.get("/me")
def me(user: dict = Depends(get_current_user)) -> dict:
    return _user_out(user)


# ---------------------------------------------------------------------------
# Google 登入（僅雲端模式）
#
# 流程：
#   1. App 呼叫 GET /auth/google/start → 取得 Google 授權網址
#   2. App 用系統瀏覽器開啟授權網址
#   3. Google 導回 GET /auth/google/callback → 後端換 token、建立使用者與 session
#   4. 後端以 302 導回 meetsum://auth?token=... ，App 攔截深層連結完成登入
#
# 不使用原生 Google SDK，因此換簽章 bundle id 也不會壞。
# ---------------------------------------------------------------------------

_OAUTH_STATES: dict[str, float] = {}
_STATE_TTL = 600  # 10 分鐘
_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"


def _prune_states() -> None:
    now = time.time()
    for key in [k for k, ts in _OAUTH_STATES.items() if now - ts > _STATE_TTL]:
        _OAUTH_STATES.pop(key, None)


def _redirect_base(request: Request) -> str:
    """Google 導回網址的基底。

    優先使用 GOOGLE_REDIRECT_BASE；但 Colab 每次啟動的 tunnel 網域都不同，
    所以設定為空或 localhost 時，改以本次請求的來源推導（支援反向代理的
    X-Forwarded-* 標頭）。start 與 callback 都走同一個函式，兩邊才會一致。
    """
    base = (config.GOOGLE_REDIRECT_BASE or "").rstrip("/")
    if base and "localhost" not in base and "127.0.0.1" not in base:
        return base
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme or "http"
    host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    if host:
        return f"{proto.split(',')[0].strip()}://{host.split(',')[0].strip()}".rstrip("/")
    if base:
        return base
    return str(request.base_url).rstrip("/")


def _safe_username(email: str | None, sub: str) -> str:
    base = (email or "").split("@")[0]
    base = "".join(ch for ch in base if ch.isalnum() or ch == "_")
    if len(base) < 3:
        base = f"google_{sub[:8]}"
    return base[:28]


def _unique_username(conn, wanted: str) -> str:
    if users.get_by_username(conn, wanted) is None:
        return wanted
    for i in range(1, 1000):
        suffix = f"_{i}"
        candidate = wanted[: max(3, 32 - len(suffix))] + suffix
        if users.get_by_username(conn, candidate) is None:
            return candidate
    return f"google_{secrets.token_hex(6)}"


@router.get("/google/start")
def google_start(request: Request) -> dict:
    if not config.GOOGLE_CLIENT_ID or not config.GOOGLE_CLIENT_SECRET:
        raise api_error(
            status.HTTP_501_NOT_IMPLEMENTED,
            "GOOGLE_NOT_CONFIGURED",
            "後端尚未設定 Google 登入（GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET）",
        )
    _prune_states()
    state = secrets.token_urlsafe(24)
    _OAUTH_STATES[state] = time.time()
    redirect_uri = f"{_redirect_base(request)}/api/v1/auth/google/callback"
    params = {
        "client_id": config.GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    return {"auth_url": f"{_AUTH_URL}?{urllib.parse.urlencode(params)}", "state": state}


def _deep_link(**params: str) -> str:
    return f"{config.APP_URL_SCHEME}://auth?{urllib.parse.urlencode(params)}"


@router.get("/google/callback")
def google_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    if error:
        return RedirectResponse(_deep_link(error=error))
    if not code or not state:
        return RedirectResponse(_deep_link(error="missing_code"))
    created = _OAUTH_STATES.pop(state, None)
    if created is None or time.time() - created > _STATE_TTL:
        return RedirectResponse(_deep_link(error="invalid_state"))

    redirect_uri = f"{_redirect_base(request)}/api/v1/auth/google/callback"
    try:
        with httpx.Client(timeout=15) as client:
            token_res = client.post(
                _TOKEN_URL,
                data={
                    "code": code,
                    "client_id": config.GOOGLE_CLIENT_ID,
                    "client_secret": config.GOOGLE_CLIENT_SECRET,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
            token_res.raise_for_status()
            access_token = token_res.json().get("access_token")
            if not access_token:
                return RedirectResponse(_deep_link(error="no_access_token"))
            info_res = client.get(
                _USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}
            )
            info_res.raise_for_status()
            info = info_res.json()
    except Exception:
        return RedirectResponse(_deep_link(error="google_exchange_failed"))

    sub = str(info.get("sub") or "")
    email = info.get("email")
    name = info.get("name") or email
    if not sub:
        return RedirectResponse(_deep_link(error="no_sub"))

    try:
        with get_conn() as conn:
            user = users.get_by_google_sub(conn, sub)
            if user is None:
                username = _unique_username(conn, _safe_username(email, sub))
                user = users.create_google_user(
                    conn, username, (name or username)[:20], sub, email
                )
            token = _open_session(conn, user)
    except UniqueViolation:
        return RedirectResponse(_deep_link(error="account_conflict"))
    except Exception:
        return RedirectResponse(_deep_link(error="db_error"))

    audit.record(
        user_id=user["id"],
        username=user["username"],
        ip="google-oauth",
        action="Google 登入成功",
        detail={},
        secrets=(token,),
    )
    return RedirectResponse(_deep_link(token=token))
