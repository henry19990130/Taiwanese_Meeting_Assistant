from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, Field

from app import config
from app.db import get_conn
from app.deps import api_error, get_current_user
from app.repositories import sessions, users
from app.security import hash_token, new_session_token, verify_password

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)

@router.post("/login")
def login(body: LoginRequest) -> dict:
    with get_conn() as conn:
        user = users.get_by_username(conn, body.username.strip())

        if user is None or not verify_password(body.password, user["password_hash"]):
            raise api_error(status.HTTP_401_UNAUTHORIZED, "INVALID_CREDENTIALS", "帳號或密碼錯誤")
        token = new_session_token()
        sessions.delete_expired(conn)
        sessions.create_session(conn, hash_token(token), user["id"], config.SESSION_TTL_SECONDS)
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": config.SESSION_TTL_SECONDS,
        "user": {"id": str(user["id"]), "username": user["username"]},
    }

@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(user: dict = Depends(get_current_user)) -> Response:
    with get_conn() as conn:
        sessions.delete_session(conn, user["token_hash"])
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@router.get("/me")
def me(user: dict = Depends(get_current_user)) -> dict:
    return {"id": str(user["id"]), "username": user["username"]}
