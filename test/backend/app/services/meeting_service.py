from __future__ import annotations

import datetime as dt
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import BinaryIO

from app import config
from app.db import get_conn
from app.repositories import meetings, summaries, terms, transcripts
from app.services.asr_service import get_asr_service
from app.services.language import SUPPORTED as SUMMARY_LANGUAGES, transcript_language
from app.services.summarizer_service import get_summarizer_service
from app.services.transcript_parser import parse_transcript
from app.services import typo_service
from app.services.typo_service import get_typo_checker

UPLOADED_TRANSCRIPT_MODEL = "uploaded-transcript"

log = logging.getLogger(__name__)

_worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="meeting-job")

class NotFound(Exception):
    pass

class Conflict(Exception):
    pass

class TooLarge(Exception):
    pass

class BadRequest(Exception):
    pass

def on_startup() -> None:
    with get_conn() as conn:
        n = meetings.fail_interrupted(conn)
    if n:
        log.warning("有 %d 場會議因伺服器重啟而中斷，已標記為 failed", n)
    if config.ASR_UNLOAD_AFTER_USE:
        log.info("ASR_UNLOAD_AFTER_USE=true：不預先載入語音模型，每次辨識時才載入、辨識完卸載")
    else:
        _worker.submit(_warmup)

def _warmup() -> None:
    try:
        get_asr_service().load()
        log.info("ASR 模型已載入")
    except Exception:
        log.exception("ASR 模型預先載入失敗（第一次辨識時會再試一次）")

def create_meeting(
    *,
    meeting_name: str,
    date: dt.date,
    start_time: dt.time | None,
    end_time: dt.time | None,
    audio_file: BinaryIO,
    original_filename: str,
    created_by=None,
) -> dict:
    meeting_id = uuid.uuid4()
    suffix = Path(original_filename or "").suffix.lower()[:10] or ".bin"
    audio_path = config.AUDIO_DIR / f"{meeting_id}{suffix}"

    _save_upload(audio_file, audio_path)
    try:
        with get_conn() as conn:
            meeting = meetings.create_meeting(
                conn,
                meeting_id=meeting_id,
                meeting_name=meeting_name,
                date=date,
                start_time=start_time,
                end_time=end_time,
                audio_path=str(audio_path),
                created_by=created_by,
            )
    except Exception:
        audio_path.unlink(missing_ok=True)
        raise

    _worker.submit(_run_transcription, meeting_id)
    return meeting

MAX_TRANSCRIPT_BYTES = 5 * 1024 * 1024

def create_meeting_from_transcript(
    *,
    meeting_name: str,
    date: dt.date,
    start_time: dt.time | None,
    end_time: dt.time | None,
    transcript_file: BinaryIO,
    original_filename: str,
    created_by=None,
) -> dict:
    data = transcript_file.read(MAX_TRANSCRIPT_BYTES + 1)
    if len(data) > MAX_TRANSCRIPT_BYTES:
        raise TooLarge("逐字稿檔超過 5 MB")
    if not data.strip():
        raise ValueError("逐字稿檔是空的")
    segments = parse_transcript(data, original_filename or "")

    with get_conn() as conn:
        meeting = meetings.create_meeting(
            conn,
            meeting_name=meeting_name,
            date=date,
            start_time=start_time,
            end_time=end_time,
            audio_path=None,
            source_type="transcript",
            created_by=created_by,
        )
        transcripts.save_transcript(conn, meeting["id"], segments, UPLOADED_TRANSCRIPT_MODEL)
        meeting = meetings.update_status(conn, meeting["id"], "proofreading")
    log.info("會議 %s 由上傳逐字稿建立，共 %d 段", meeting["id"], len(segments))
    _worker.submit(_run_proofread, meeting["id"])
    return meeting

def _save_upload(src: BinaryIO, dest: Path) -> None:
    limit = config.MAX_UPLOAD_MB * 1024 * 1024
    written = 0
    try:
        with dest.open("wb") as out:
            while chunk := src.read(1024 * 1024):
                written += len(chunk)
                if written > limit:
                    raise TooLarge(f"音檔超過 {config.MAX_UPLOAD_MB} MB")
                out.write(chunk)
        if written == 0:
            raise ValueError("音檔是空的")
    except Exception:
        dest.unlink(missing_ok=True)
        raise

def _run_transcription(meeting_id: uuid.UUID) -> None:
    try:
        with get_conn() as conn:
            meeting = meetings.update_status(conn, meeting_id, "transcribing")
        if meeting is None:
            return

        asr = get_asr_service()
        try:
            segments = asr.transcribe(meeting["audio_path"])
            model_name = asr.model_name
            asr_info = {"language": asr.last_language, "language_probs": asr.last_language_probs,
                        "detect": asr.last_detect}
        finally:
            if config.ASR_UNLOAD_AFTER_USE:
                asr.unload()
                log.info("語音模型已卸載，釋放顯示卡記憶體")
        if not segments:
            raise ValueError("辨識結果是空的，可能是音檔沒有人聲")

        with get_conn() as conn:
            transcripts.save_transcript(conn, meeting_id, segments, model_name, asr_info)
            meetings.update_status(conn, meeting_id, "proofreading")
        log.info("會議 %s 辨識完成，共 %d 段", meeting_id, len(segments))
    except Exception as exc:
        log.exception("會議 %s 辨識失敗", meeting_id)
        _mark_failed(meeting_id, "transcribing", "ASR_FAILED", f"語音辨識失敗：{exc}")
        return
    _run_proofread(meeting_id)

def _run_proofread(meeting_id: uuid.UUID) -> None:
    try:
        with get_conn() as conn:
            row = transcripts.get_row(conn, meeting_id)
            meeting = meetings.get_meeting(conn, meeting_id)
            glossary = terms.term_strings(conn, meeting and meeting.get("created_by"))
        if row is None:
            return
        suggestions, problems = [], []
        checker = get_typo_checker()
        language = transcript_language(row["transcript"])
        if config.TYPO_CHECK:
            try:
                suggestions, problems = checker.check(row["transcript"], glossary)
                language = checker.last_language
            except Exception as exc:
                log.exception("會議 %s 錯字檢查失敗", meeting_id)
                problems = [f"錯字檢查沒有完成：{exc}"]
        proofread = {"enabled": config.TYPO_CHECK, "suggestions": suggestions, "problems": problems,
                     "glossary_count": len(glossary), "language": language,
                     "manual": (row["proofread"] or {}).get("manual", [])}
        with get_conn() as conn:
            transcripts.save_proofread(conn, meeting_id, proofread)
            meetings.update_status(conn, meeting_id, "reviewing")
        log.info("會議 %s 校對完成，%d 處疑似錯字", meeting_id, len(suggestions))
    except Exception as exc:
        log.exception("會議 %s 校對失敗", meeting_id)
        _mark_failed(meeting_id, "proofreading", "PROOFREAD_FAILED", f"錯字校對失敗：{exc}")

def get_proofread(meeting_id: uuid.UUID | str) -> dict:
    with get_conn() as conn:
        meeting = meetings.get_meeting(conn, meeting_id)
        row = transcripts.get_row(conn, meeting_id) if meeting else None
    if meeting is None:
        raise NotFound()
    if row is None:
        raise Conflict(f"逐字稿尚未產生（目前狀態：{meeting['status']}）")
    return _proofread_view(meeting["status"], row["proofread"], row["confirmed_at"])

def _proofread_view(status: str, proofread: dict | None, confirmed_at) -> dict:
    pr = proofread or {"enabled": config.TYPO_CHECK, "suggestions": [], "problems": []}
    return {
        "status": status,
        "checked": proofread is not None,
        "enabled": pr.get("enabled", True),
        "confirmed": confirmed_at is not None,
        "confirmed_at": confirmed_at.isoformat() if confirmed_at else None,
        "counts": typo_service.counts(pr["suggestions"]),
        "suggestions": pr["suggestions"],
        "problems": pr.get("problems") or [],
        "glossary_count": pr.get("glossary_count", 0),
        "language": pr.get("language"),
        "manual": pr.get("manual") or [],
    }

def _edit(meeting_id, fn) -> dict:
    with get_conn() as conn:
        meeting = meetings.get_meeting(conn, meeting_id)
        if meeting is None:
            raise NotFound()
        row = transcripts.get_row(conn, meeting_id, for_update=True)
        if row is None or meeting["status"] != "reviewing" or row["confirmed_at"] is not None:
            raise Conflict(f"目前狀態為 {meeting['status']}，只有校對完成、還沒確認的逐字稿可以修改")
        transcript, proofread = row["transcript"], row["proofread"] or {"suggestions": [], "problems": []}
        result = fn(transcript, proofread["suggestions"], proofread)
        transcripts.save_edits(conn, meeting_id, transcript, proofread)
    return {"result": result, "transcript": transcript,
            "proofread": _proofread_view(meeting["status"], proofread, None)}

def review_typos(meeting_id, *, action: str, ids: list[str] | None, replacement: str | None) -> dict:
    def fn(transcript, suggestions, proofread):
        try:
            return typo_service.apply_decision(transcript, suggestions, ids, action, replacement)
        except ValueError as exc:
            raise BadRequest(str(exc)) from None
    out = _edit(meeting_id, fn)
    out["done"] = out.pop("result")
    return out

def edit_segment(meeting_id, segment_id: str, text: str) -> dict:
    def fn(transcript, suggestions, proofread):
        try:
            typo_service.edit_segment(transcript, suggestions, segment_id, text)
        except KeyError:
            raise BadRequest(f"找不到段落 {segment_id}") from None
        except ValueError as exc:
            raise BadRequest(str(exc)) from None
    out = _edit(meeting_id, fn)
    out.pop("result")
    return out

def replace_text(meeting_id, *, find: str, replace: str, segment_id: str | None, offset: int | None) -> dict:
    def fn(transcript, suggestions, proofread):
        try:
            n = typo_service.replace_text(transcript, suggestions, find, replace, segment_id, offset)
        except KeyError:
            raise BadRequest(f"找不到段落 {segment_id}") from None
        except ValueError as exc:
            raise BadRequest(str(exc)) from None
        if n:
            typo_service.record_manual(proofread, find, replace, n)
        return n
    out = _edit(meeting_id, fn)
    out["replaced"] = out.pop("result")
    return out

def confirm_transcript(meeting_id) -> dict:
    with get_conn() as conn:
        meeting = meetings.get_meeting(conn, meeting_id)
        if meeting is None:
            raise NotFound()
        row = transcripts.get_row(conn, meeting_id, for_update=True)
        if row is None or meeting["status"] != "reviewing" or row["confirmed_at"] is not None:
            raise Conflict(f"目前狀態為 {meeting['status']}，沒有等待確認的逐字稿")
        proofread = row["proofread"]
        if proofread:
            for t in proofread["suggestions"]:
                if t["status"] == "pending":
                    t["status"] = "ignored"
        transcripts.confirm(conn, meeting_id, proofread)
        meeting = meetings.update_status(conn, meeting_id, "transcribed")
    return meeting

def request_proofread(meeting_id) -> dict:
    with get_conn() as conn:
        meeting = meetings.start_proofreading(conn, meeting_id)
        if meeting is None:
            current = meetings.get_meeting(conn, meeting_id)
    if meeting is None:
        if current is None:
            raise NotFound()
        raise Conflict(f"目前狀態為 {current['status']}，逐字稿確認之前才能重新校對")
    _worker.submit(_run_proofread, meeting["id"])
    return meeting

def request_summary(meeting_id: uuid.UUID | str, language: str | None = None) -> dict:
    if language is not None and language not in SUMMARY_LANGUAGES:
        raise BadRequest(f"重點語言只能是 {'、'.join(SUMMARY_LANGUAGES)}，收到：{language}")
    with get_conn() as conn:
        meeting = meetings.start_summarizing(conn, meeting_id)
        if meeting is None:
            current = meetings.get_meeting(conn, meeting_id)
    if meeting is None:
        if current is None:
            raise NotFound()
        raise Conflict(f"目前狀態為 {current['status']}，需要先確認逐字稿才能產生重點")

    _worker.submit(_run_summary, meeting["id"], language)
    return meeting

def _run_summary(meeting_id: uuid.UUID, language: str | None = None) -> None:
    try:
        with get_conn() as conn:
            meeting = meetings.get_meeting(conn, meeting_id)
            transcript = transcripts.get_transcript(conn, meeting_id)
        if meeting is None:
            return
        if transcript is None:
            raise ValueError("找不到逐字稿")

        language = language or transcript_language(transcript)
        summarizer = get_summarizer_service()

        summary = summarizer.summarize(transcript, meeting, language=language)

        with get_conn() as conn:
            summaries.upsert_summary(conn, meeting_id, summary, summarizer.model_name, language)
            meetings.update_status(conn, meeting_id, "completed")
        log.info("會議 %s 重點產生完成", meeting_id)
    except Exception as exc:
        log.exception("會議 %s 產生重點失敗", meeting_id)
        _mark_failed(meeting_id, "summarizing", "SUMMARY_GENERATION_FAILED", f"產生重點失敗：{exc}")

def get_meeting(meeting_id: uuid.UUID | str) -> dict:
    with get_conn() as conn:
        meeting = meetings.get_meeting(conn, meeting_id)
    if meeting is None:
        raise NotFound()
    return meeting

def get_transcript(meeting_id: uuid.UUID | str) -> dict:
    with get_conn() as conn:
        meeting = meetings.get_meeting(conn, meeting_id)
        transcript = transcripts.get_transcript(conn, meeting_id) if meeting else None
    if meeting is None:
        raise NotFound()
    if transcript is None:
        raise Conflict(f"逐字稿尚未產生（目前狀態：{meeting['status']}）")
    return transcript

def get_summary(meeting_id: uuid.UUID | str) -> tuple[dict, dict]:
    with get_conn() as conn:
        meeting = meetings.get_meeting(conn, meeting_id)
        summary = summaries.get_summary(conn, meeting_id) if meeting else None
    if meeting is None:
        raise NotFound()
    if summary is None:
        raise Conflict(f"重點尚未產生（目前狀態：{meeting['status']}）")
    return meeting, summary

def _mark_failed(meeting_id, stage: str, code: str, message: str) -> None:
    try:
        with get_conn() as conn:
            meetings.mark_failed(conn, meeting_id, stage=stage, code=code, message=message[:500])
    except Exception:
        log.exception("無法寫入失敗狀態（會議 %s）", meeting_id)

def wait_for_idle(timeout: float = 30.0) -> None:
    _worker.submit(lambda: None).result(timeout=timeout)

__all__ = [
    "BadRequest", "Conflict", "NotFound", "TooLarge", "confirm_transcript", "create_meeting",
    "create_meeting_from_transcript", "edit_segment", "get_meeting", "get_proofread", "get_summary",
    "get_transcript", "on_startup", "replace_text", "request_proofread", "request_summary", "review_typos",
    "wait_for_idle",
]
