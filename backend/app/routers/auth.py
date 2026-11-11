from __future__ import annotations

from fastapi import APIRouter, Cookie, Depends, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from psycopg.errors import UniqueViolation
from pydantic import BaseModel, Field

from app import audit, config
from app.db import get_conn
from app.deps import access_digest, api_error, client_ip, get_current_user
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
from app.security.rate_limit import limit_login, limit_refresh, limit_register

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

_COOKIE = "session"
_INVALID = "帳號或密碼錯誤"


class LoginRequest(BaseModel):
    username: str = Field(min_length=0, max_length=200)
    password: str = Field(min_length=0, max_length=200)


class RegisterRequest(BaseModel):
    username: str = Field(min_length=0, max_length=200)
    password: str = Field(min_length=0, max_length=200)
    display_name: str = Field(default="", max_length=200)


_USERNAME_MSG = "帳號只允許 3 到 32 碼的英數字或底線"
_PASSWORD_MSG = "密碼至少 12 碼，而且要同時含英文字母和數字"
_EXISTS_MSG = "無法完成註冊，請改用其他帳號或稍後再試"
_DISPLAY_MSG = "稱呼最多 20 個字"


def _user_out(user: dict) -> dict:
    return {
        "id": str(user["id"]),
        "username": user["username"],
        "display_name": user.get("display_name") or None,
    }


def _refresh_digest(token: str) -> str:
    return hash_token(f"refresh:{token}")


def _issue_tokens(conn, user: dict) -> tuple[str, str]:
    sessions.delete_expired(conn)
    refresh = new_session_token()
    access = new_session_token()
    sessions.create_session(conn, _refresh_digest(refresh), user["id"], config.REFRESH_TTL_SECONDS)
    sessions.create_session(conn, access_digest(access), user["id"], config.ACCESS_TTL_SECONDS)
    return refresh, access


def _issue_access(conn, user_id) -> str:
    access = new_session_token()
    sessions.create_session(conn, access_digest(access), user_id, config.ACCESS_TTL_SECONDS)
    return access


def _set_refresh_cookie(response: Response, refresh: str) -> None:
    response.set_cookie(
        key=_COOKIE,
        value=refresh,
        httponly=True,
        secure=config.COOKIE_SECURE,
        samesite="lax",
        path="/",
        max_age=config.REFRESH_TTL_SECONDS,
    )


def _session_body(response: Response, user: dict, refresh: str, access: str) -> dict:
    _set_refresh_cookie(response, refresh)
    return {
        "access_token": access,
        "expires_in": config.ACCESS_TTL_SECONDS,
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
    limit_login(request)
    username = body.username.strip()
    password = body.password
    ip = client_ip(request)
    failure: tuple[str, str] | None = None
    refresh = ""
    access = ""
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
            refresh, access = _issue_tokens(conn, user)
    if failure is not None:
        _reject(
            username, ip, password,
            action=failure[0],
            reason=failure[1],
            message=_INVALID,
        )
    audit.record(
        user_id=user["id"],
        username=user["username"],
        ip=ip,
        action="登入成功",
        detail={},
        secrets=(password, refresh, access),
    )
    return _session_body(response, user, refresh, access)


@router.post("/register")
def register(body: RegisterRequest, request: Request, response: Response) -> dict:
    limit_register(request)
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
    refresh = ""
    access = ""
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
                refresh, access = _issue_tokens(conn, user)
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
        raise api_error(422, "REGISTRATION_FAILED", _EXISTS_MSG)
    audit.record(
        user_id=user["id"],
        username=user["username"],
        ip=ip,
        action="建立帳號",
        detail={},
        secrets=(password, refresh, access),
    )
    return _session_body(response, user, refresh, access)


_bearer = HTTPBearer(auto_error=False)


@router.post("/refresh")
def refresh(request: Request, session: str | None = Cookie(default=None, alias=_COOKIE)) -> dict:
    limit_refresh(request)
    if not session:
        raise api_error(status.HTTP_401_UNAUTHORIZED, "NOT_LOGGED_IN", "請先登入")
    with get_conn() as conn:
        row = sessions.get_valid_session(conn, _refresh_digest(session))
        if row is None:
            raise api_error(status.HTTP_401_UNAUTHORIZED, "SESSION_EXPIRED", "登入已失效，請重新登入")
        access = _issue_access(conn, row["user_id"])
    return {
        "access_token": access,
        "expires_in": config.ACCESS_TTL_SECONDS,
        "user": {
            "id": str(row["user_id"]),
            "username": row["username"],
            "display_name": row.get("display_name") or None,
        },
    }


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: str | None = Cookie(default=None, alias=_COOKIE),
) -> Response:
    user = None
    with get_conn() as conn:
        if cred is not None and cred.credentials:
            user = sessions.get_valid_session(conn, access_digest(cred.credentials))
        if user is None and session:
            user = sessions.get_valid_session(conn, _refresh_digest(session))
        if user is not None:
            sessions.delete_user_sessions(conn, user["user_id"])
    if user is not None:
        audit.record(
            user_id=user["user_id"],
            username=user["username"],
            ip=client_ip(request),
            action="登出",
            detail={},
        )
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(_COOKIE, path="/", secure=config.COOKIE_SECURE, samesite="lax")
    return response


@router.get("/me")
def me(user: dict = Depends(get_current_user)) -> dict:
    return _user_out(user)
