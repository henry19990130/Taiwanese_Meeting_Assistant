from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.db import get_conn
from app.deps import api_error, get_current_user
from app.repositories import library
from app.services import assistant_search as S
from app.services.assistant_agent import get_agent, today_local

router = APIRouter(prefix="/api/v1/assistant", tags=["assistant"])


def _lib(user: dict) -> list[dict]:
    with get_conn() as conn:
        return library.load_library(conn, user["id"])


class QuoteBody(BaseModel):
    text: str = Field(..., min_length=2, max_length=300)


class ChatTurn(BaseModel):
    role: str
    content: str = Field(..., max_length=4000)


class ChatBody(BaseModel):
    question: str = Field(..., min_length=1, max_length=500)
    history: list[ChatTurn] = Field(default_factory=list, max_length=20)


@router.get("/overview")
def overview(user: dict = Depends(get_current_user)) -> dict:
    lib = _lib(user)
    return {
        "meeting_count": len(lib),
        "recent": [{"meeting_id": m["id"], "name": m["name"], "date": m["date"].isoformat(),
                    "headline": (m["summary"] or {}).get("headline")} for m in lib[:12]],
        "people": S.people(lib),
        "today": today_local().isoformat(),
    }


@router.get("/meetings")
def find_meetings(q: str | None = Query(None, max_length=100), period: str | None = Query(None, max_length=40),
                  person: str | None = Query(None, max_length=40), user: dict = Depends(get_current_user)) -> dict:
    src = S.Sources()
    r = S.search_meetings(_lib(user), src, today_local(), query=q, period=period, person=person)
    return {**r, "sources": src.items}


@router.get("/meetings/{meeting_id}/summary")
def meeting_summary(meeting_id: str, user: dict = Depends(get_current_user)) -> dict:
    src = S.Sources()
    r = S.get_meeting_summary(_lib(user), src, meeting_id)
    if "error" in r:
        raise api_error(404, "MEETING_NOT_FOUND", r["error"])
    return {**r, "sources": src.items}


@router.get("/actions")
def actions(assignee: str | None = Query(None, max_length=40), due: str | None = Query(None, max_length=40),
            unassigned: bool = False, user: dict = Depends(get_current_user)) -> dict:
    src = S.Sources()
    r = S.list_action_items(_lib(user), src, today_local(), assignee=assignee, due_period=due, unassigned=unassigned)
    return {**r, "sources": src.items}


@router.post("/quote")
def quote(body: QuoteBody, user: dict = Depends(get_current_user)) -> dict:
    src = S.Sources()
    r = S.find_quote(_lib(user), src, body.text)
    return {**r, "sources": src.items}


@router.post("/chat")
def chat(body: ChatBody, user: dict = Depends(get_current_user)) -> dict:
    lib = _lib(user)
    if not lib:
        return {"kind": "not_found", "sources": [], "trace": [],
                "text": "你的帳號還沒有已確認逐字稿的會議，先上傳一場會議吧！"}
    try:
        return get_agent().answer(lib, body.question, [t.model_dump() for t in body.history])
    except Exception as exc:
        raise api_error(502, "ASSISTANT_FAILED", f"小幫手暫時無法回答：{exc}") from None
