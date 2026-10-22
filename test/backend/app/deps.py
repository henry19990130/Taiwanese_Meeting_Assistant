from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.db import get_conn
from app.repositories import sessions
from app.security import hash_token

_bearer = HTTPBearer(auto_error=False)

def api_error(http_status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=http_status, detail={"code": code, "message": message})

def get_current_user(
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict:
    if cred is None or not cred.credentials:
        raise api_error(status.HTTP_401_UNAUTHORIZED, "NOT_LOGGED_IN", "請先登入")
    token_hash = hash_token(cred.credentials)
    with get_conn() as conn:
        session = sessions.get_valid_session(conn, token_hash)
    if session is None:
        raise api_error(status.HTTP_401_UNAUTHORIZED, "SESSION_EXPIRED", "登入已失效，請重新登入")
    return {"id": session["user_id"], "username": session["username"], "token_hash": token_hash}
