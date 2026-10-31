from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile, status
from pydantic import BaseModel, Field

from app.deps import api_error, client_ip, get_current_user
from app.services import asr_models
from app.services import meeting_service as svc

router = APIRouter(
    prefix="/api/v1/meetings", tags=["meetings"], dependencies=[Depends(get_current_user)]
)


def _parse_id(meeting_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(meeting_id)
    except ValueError:
        raise api_error(404, "MEETING_NOT_FOUND", "找不到這場會議") from None


def _iso(v) -> str | None:
    return v.isoformat() if v is not None else None


def _status_url(mid) -> str:
    return f"/api/v1/meetings/{mid}/status"


def _call(fn, *args):
    try:
        return fn(*args)
    except svc.NotFound:
        raise api_error(404, "MEETING_NOT_FOUND", "找不到這場會議") from None
    except svc.Conflict as exc:
        raise api_error(409, "INVALID_STATE", str(exc)) from None
    except svc.BadRequest as exc:
        raise api_error(422, "INVALID_EDIT", str(exc)) from None


@router.post("", status_code=status.HTTP_202_ACCEPTED)
def upload_meeting(
    audio: UploadFile | None = File(None),
    transcript: UploadFile | None = File(None),
    meeting_name: str = Form(...),
    date: str = Form(...),
    start_time: str | None = Form(None),
    end_time: str | None = Form(None),
    asr_language: str = Form("zh"),
    hakka_dialect: str | None = Form(None),
    user: dict = Depends(get_current_user),
) -> dict:
    name = meeting_name.strip()
    if not 1 <= len(name) <= 255:
        raise api_error(422, "INVALID_MEETING_NAME", "會議名稱須為 1–255 字元")
    try:
        d = dt.date.fromisoformat(date)
    except ValueError:
        raise api_error(422, "INVALID_DATE", "日期格式須為 YYYY-MM-DD") from None
    st = _parse_time(start_time, "start_time")
    et = _parse_time(end_time, "end_time")
    if et and not st:
        raise api_error(422, "INVALID_TIME", "填了結束時間就必須填開始時間")
    if st and et and et < st:
        raise api_error(422, "INVALID_TIME", "結束時間不能早於開始時間")

    asr_language = (asr_language or "zh").strip().lower()
    if asr_language not in asr_models.LANGUAGES:
        raise api_error(422, "INVALID_LANGUAGE", f"會議語言只能是 {'、'.join(asr_models.LANGUAGES)}")
    if asr_language == "hak" and hakka_dialect and hakka_dialect.strip().lower() not in asr_models.HAKKA_DIALECTS:
        raise api_error(422, "INVALID_DIALECT", f"客語腔調只能是 {'、'.join(asr_models.HAKKA_DIALECTS)}")

    has_audio = audio is not None and bool(audio.filename)
    has_transcript = transcript is not None and bool(transcript.filename)
    if has_audio == has_transcript:
        raise api_error(422, "INVALID_INPUT", "請上傳錄音檔或逐字稿檔其中一個")

    try:
        if has_audio:
            meeting = svc.create_meeting(
                meeting_name=name, date=d, start_time=st, end_time=et,
                audio_file=audio.file, original_filename=audio.filename or "",
                created_by=user["id"],
                asr_language=asr_language, asr_dialect=hakka_dialect,
            )
        else:
            meeting = svc.create_meeting_from_transcript(
                meeting_name=name, date=d, start_time=st, end_time=et,
                transcript_file=transcript.file, original_filename=transcript.filename or "",
                created_by=user["id"],
            )
    except svc.TooLarge as exc:
        raise api_error(413, "AUDIO_TOO_LARGE", str(exc)) from None
    except ValueError as exc:
        code = "INVALID_AUDIO" if has_audio else "INVALID_TRANSCRIPT"
        raise api_error(422, code, str(exc)) from None

    return {
        "meeting_id": str(meeting["id"]),
        "meeting_name": meeting["meeting_name"],
        "source_type": meeting["source_type"],
        "status": meeting["status"],
        "created_at": _iso(meeting["created_at"]),
        "status_url": _status_url(meeting["id"]),
        "asr_language": asr_language if has_audio else None,
    }


@router.get("/asr-languages")
def list_asr_languages() -> dict:
    return {
        "default": asr_models.DEFAULT_LANGUAGE,
        "languages": [{"code": k, "label": v["label"], "model": v["model_id"]}
                      for k, v in asr_models.LANGUAGES.items()],
        "hakka_dialects": [{"code": k, "label": v[0]} for k, v in asr_models.HAKKA_DIALECTS.items()],
        "default_hakka_dialect": asr_models.DEFAULT_HAKKA_DIALECT,
    }


@router.delete("/{meeting_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_meeting(meeting_id: str, request: Request, user: dict = Depends(get_current_user)) -> Response:
    _call(lambda: svc.delete_owned_meeting(_parse_id(meeting_id), actor=user, ip=client_ip(request)))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _parse_time(value: str | None, field: str) -> dt.time | None:
    if value is None or not value.strip():
        return None
    try:
        return dt.time.fromisoformat(value.strip())
    except ValueError:
        raise api_error(422, "INVALID_TIME", f"{field} 格式須為 HH:mm 或 HH:mm:ss") from None


@router.get("/{meeting_id}/status")
def get_status(meeting_id: str, request: Request, user: dict = Depends(get_current_user)) -> dict:
    m = _call(lambda: svc.get_meeting(_parse_id(meeting_id), actor=user, ip=client_ip(request)))
    return {
        "meeting_id": str(m["id"]),
        "meeting_name": m["meeting_name"],
        "source_type": m["source_type"],
        "status": m["status"],
        "error": m["error"],
        "updated_at": _iso(m["updated_at"]),
    }


@router.get("/{meeting_id}/transcript")
def get_transcript(meeting_id: str, request: Request, user: dict = Depends(get_current_user)) -> dict:
    return _call(lambda: svc.get_transcript(_parse_id(meeting_id), actor=user, ip=client_ip(request)))


class TypoDecision(BaseModel):
    action: str = Field(..., description="accept（套用）/ ignore（保留原文）/ undo（復原）")
    ids: list[str] | None = Field(None, description="要處理的建議 id；不給 = 全部還沒處理的")
    replacement: str | None = Field(None, max_length=200, description="自己輸入的改法（只能一處）")


class TextReplace(BaseModel):
    find: str = Field(..., min_length=1, max_length=200)
    replace: str = Field(..., max_length=200)
    segment_id: str | None = Field(None, description="只改這一段的這一處；不給 = 全部取代")
    offset: int | None = Field(None, ge=0)


class SegmentEdit(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)


@router.get("/{meeting_id}/proofread")
def get_proofread(meeting_id: str, request: Request, user: dict = Depends(get_current_user)) -> dict:
    return _call(lambda: svc.get_proofread(_parse_id(meeting_id), actor=user, ip=client_ip(request)))


@router.post("/{meeting_id}/proofread", status_code=status.HTTP_202_ACCEPTED)
def rerun_proofread(meeting_id: str, request: Request, user: dict = Depends(get_current_user)) -> dict:
    m = _call(lambda: svc.request_proofread(_parse_id(meeting_id), actor=user, ip=client_ip(request)))
    return {"meeting_id": str(m["id"]), "status": m["status"], "status_url": _status_url(m["id"])}


@router.post("/{meeting_id}/proofread/decisions")
def decide_typos(meeting_id: str, body: TypoDecision, request: Request, user: dict = Depends(get_current_user)) -> dict:
    mid = _parse_id(meeting_id)
    return _call(lambda: svc.review_typos(
        mid, action=body.action, ids=body.ids, replacement=body.replacement,
        actor=user, ip=client_ip(request),
    ))


@router.put("/{meeting_id}/transcript/segments/{segment_id}")
def edit_segment(meeting_id: str, segment_id: str, body: SegmentEdit, request: Request,
                 user: dict = Depends(get_current_user)) -> dict:
    return _call(lambda: svc.edit_segment(
        _parse_id(meeting_id), segment_id, body.text, actor=user, ip=client_ip(request),
    ))


@router.post("/{meeting_id}/transcript/replace")
def replace_text(meeting_id: str, body: TextReplace, request: Request, user: dict = Depends(get_current_user)) -> dict:
    mid = _parse_id(meeting_id)
    return _call(lambda: svc.replace_text(
        mid, find=body.find, replace=body.replace, segment_id=body.segment_id, offset=body.offset,
        actor=user, ip=client_ip(request),
    ))


@router.post("/{meeting_id}/transcript/confirm")
def confirm_transcript(meeting_id: str, request: Request, user: dict = Depends(get_current_user)) -> dict:
    m = _call(lambda: svc.confirm_transcript(_parse_id(meeting_id), actor=user, ip=client_ip(request)))
    return {"meeting_id": str(m["id"]), "status": m["status"]}


class SummaryRequest(BaseModel):
    language: str | None = Field(default=None, pattern="^(zh|en)$")


@router.post("/{meeting_id}/summary", status_code=status.HTTP_202_ACCEPTED)
def generate_summary(meeting_id: str, request: Request, body: SummaryRequest | None = None,
                     user: dict = Depends(get_current_user)) -> dict:
    language = body.language if body else None
    m = _call(lambda: svc.request_summary(
        _parse_id(meeting_id), language, actor=user, ip=client_ip(request),
    ))
    return {"meeting_id": str(m["id"]), "status": m["status"], "status_url": _status_url(m["id"]),
            "language": language}


@router.get("/{meeting_id}/summary")
def get_summary(meeting_id: str, request: Request, user: dict = Depends(get_current_user)) -> dict:
    m, s = _call(lambda: svc.get_summary(_parse_id(meeting_id), actor=user, ip=client_ip(request)))
    return {
        "meeting_id": str(m["id"]),
        "summary": {
            "meeting_name": m["meeting_name"],
            "meeting_datetime": {
                "date": _iso(m["date"]),
                "start_time": _iso(m["start_time"]),
                "end_time": _iso(m["end_time"]),
            },
            "headline": s["headline"],
            "meeting_content": s["meeting_content"],
            "review_notes": s["review_notes"],
            "language": s.get("language", "zh"),
        },
        "model_name": s["model_name"],
        "updated_at": _iso(s["updated_at"]),
    }
