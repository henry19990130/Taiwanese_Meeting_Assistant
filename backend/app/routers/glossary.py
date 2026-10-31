from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from app.db import get_conn
from app.deps import api_error, get_current_user
from app.repositories import terms

router = APIRouter(prefix="/api/v1/glossary", tags=["glossary"])


class AddTerms(BaseModel):
    terms: list[str] = Field(..., min_length=1, max_length=terms.MAX_TERMS)


def _view(rows: list[dict]) -> dict:
    return {
        "terms": [{"id": str(r["id"]), "term": r["term"]} for r in rows],
        "count": len(rows),
        "limit": terms.MAX_TERMS,
        "max_length": terms.MAX_TERM_LEN,
    }


@router.get("")
def list_glossary(user: dict = Depends(get_current_user)) -> dict:
    with get_conn() as conn:
        return _view(terms.list_terms(conn, user["id"]))


@router.post("")
def add_glossary(body: AddTerms, user: dict = Depends(get_current_user)) -> dict:
    with get_conn() as conn:
        result = terms.add_terms(conn, user["id"], body.terms)
        rows = terms.list_terms(conn, user["id"])
    return {**_view(rows), "result": result}


@router.delete("/{term_id}", status_code=status.HTTP_200_OK)
def delete_glossary(term_id: str, user: dict = Depends(get_current_user)) -> dict:
    try:
        tid = uuid.UUID(term_id)
    except ValueError:
        raise api_error(404, "TERM_NOT_FOUND", "找不到這個詞") from None
    with get_conn() as conn:
        if not terms.delete_term(conn, user["id"], tid):
            raise api_error(404, "TERM_NOT_FOUND", "找不到這個詞")
        rows = terms.list_terms(conn, user["id"])
    return _view(rows)
