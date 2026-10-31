from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response, status
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
    registration_error,
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


_USERNAME_MSG = "帳號只允許 3 到 32 碼的英數字或底線"
_PASSWORD_MSG = "密碼至少 12 碼，而且要同時含英文字母和數字"
_EXISTS_MSG = "這個帳號已經有人使用"


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
        "user": {"id": str(user["id"]), "username": user["username"]},
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
        raise api_error(422, "INVALID_PASSWORD", _PASSWORD_MSG)

    user = None
    token = ""
    taken = False
    try:
        with get_conn() as conn:
            if users.get_by_username(conn, username) is not None:
                taken = True
            else:
                user = users.create_user(conn, username, hash_password(password))
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
    return {"id": str(user["id"]), "username": user["username"]}
