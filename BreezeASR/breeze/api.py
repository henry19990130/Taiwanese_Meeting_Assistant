from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from breeze.audio import AudioError
from breeze.identity.models import User
from breeze.identity.service import COOKIE_NAME, AuthError, AuthService
from breeze.jobs import Job
from breeze.models import Transcript
from breeze.service import RequestError, TranscriptionService


class Credentials(BaseModel):
    username: str
    password: str


class TagUpdate(BaseModel):
    tags: list[str]


class TitleUpdate(BaseModel):
    title: str


class SummaryUpdate(BaseModel):
    summary: str


def create_app(
    service: TranscriptionService,
    auth: AuthService,
    web_dir: Path,
) -> FastAPI:
    app = FastAPI(title="Breeze-ASR-26")

    def current_user(request: Request) -> User:
        user = auth.user_for_token(request.cookies.get(COOKIE_NAME))
        if user is None:
            raise HTTPException(status_code=401, detail="請先登入")
        return user

    def optional_user(request: Request) -> User | None:
        return auth.user_for_token(request.cookies.get(COOKIE_NAME))

    def client_ip(request: Request) -> str:
        if request.client is None:
            return "unknown"
        return request.client.host

    def set_session(response: Response, token: str) -> None:
        response.set_cookie(
            key=COOKIE_NAME,
            value=token,
            httponly=True,
            samesite="lax",
            max_age=auth.session_max_age,
            path="/",
        )

    def clear_session(response: Response) -> None:
        response.delete_cookie(COOKIE_NAME, path="/")

    @app.get("/api/health")
    @app.get("/health")
    def health():
        return service.status()

    @app.post("/api/auth/register")
    def register(payload: Credentials, request: Request, response: Response):
        try:
            user, token = auth.register(payload.username, payload.password, client_ip(request))
        except AuthError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        set_session(response, token)
        return _public_user(user)

    @app.post("/api/auth/login")
    def login(payload: Credentials, request: Request, response: Response):
        try:
            user, token = auth.login(payload.username, payload.password, client_ip(request))
        except AuthError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        set_session(response, token)
        return _public_user(user)

    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response):
        auth.logout(request.cookies.get(COOKIE_NAME), client_ip(request))
        clear_session(response)
        return {"ok": True}

    @app.get("/api/auth/me")
    def me(request: Request):
        return _public_user(current_user(request))

    @app.post("/api/jobs")
    async def create_job(request: Request, file: UploadFile = File(...)):
        user = current_user(request)
        try:
            content = await file.read()
            job = service.start_job(user.id, file.filename or "", content)
        except (RequestError, AudioError) as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        finally:
            await file.close()
        return _public_job(job)

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str, request: Request):
        job = service.get_job(current_user(request).id, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="找不到辨識工作")
        payload = _public_job(job)
        if job.transcript_id:
            record = service.get_transcript(job.owner_id, job.transcript_id)
            if record is not None:
                payload["transcript"] = _public_transcript(
                    record,
                    job.owner_id,
                    summary=service.read_summary(job.owner_id, record),
                )
        return payload

    @app.post("/api/transcribe")
    @app.post("/transcribe")
    async def transcribe(request: Request, file: UploadFile = File(...)):
        user = current_user(request)
        try:
            content = await file.read()
            record = service.transcribe_bytes(user.id, file.filename or "", content)
        except (RequestError, AudioError) as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"語音辨識失敗：{type(exc).__name__}: {exc}",
            ) from exc
        finally:
            await file.close()
        return _public_transcript(record, user.id)

    @app.get("/api/transcripts")
    def list_transcripts(request: Request):
        user = current_user(request)
        return [_public_transcript(item, user.id) for item in service.list_transcripts(user.id)]

    @app.get("/api/transcripts/{transcript_id}")
    def get_transcript(transcript_id: str, request: Request):
        user = current_user(request)
        record = service.get_transcript(user.id, transcript_id)
        if record is None:
            raise HTTPException(status_code=404, detail="找不到逐字稿")
        return _public_transcript(
            record,
            user.id,
            summary=service.read_summary(user.id, record),
            summary_log=service.summary_log(user.id, record.id),
        )

    @app.delete("/api/transcripts/{transcript_id}")
    def delete_transcript(transcript_id: str, request: Request):
        user = current_user(request)
        if not service.delete_transcript(user.id, transcript_id):
            raise HTTPException(status_code=404, detail="找不到逐字稿")
        return {"ok": True, "id": transcript_id}

    @app.put("/api/transcripts/{transcript_id}/tags")
    def replace_transcript_tags(transcript_id: str, payload: TagUpdate, request: Request):
        user = current_user(request)
        try:
            record = service.update_transcript_tags(user.id, transcript_id, payload.tags)
        except RequestError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        if record is None:
            raise HTTPException(status_code=404, detail="找不到逐字稿")
        return _public_transcript(record, user.id)

    @app.post("/api/transcripts/{transcript_id}/tags/suggest")
    def suggest_transcript_tags(transcript_id: str, request: Request):
        user = current_user(request)
        try:
            tags = service.suggest_tags(user.id, transcript_id)
        except RequestError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        if tags is None:
            raise HTTPException(status_code=404, detail="找不到逐字稿")
        return {"tags": tags}

    @app.put("/api/transcripts/{transcript_id}/title")
    def replace_transcript_title(transcript_id: str, payload: TitleUpdate, request: Request):
        user = current_user(request)
        try:
            record = service.update_transcript_title(user.id, transcript_id, payload.title)
        except RequestError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        if record is None:
            raise HTTPException(status_code=404, detail="找不到逐字稿")
        return _public_transcript(record, user.id)

    @app.put("/api/transcripts/{transcript_id}/summary")
    def replace_transcript_summary(transcript_id: str, payload: SummaryUpdate, request: Request):
        user = current_user(request)
        try:
            record = service.replace_summary(user.id, transcript_id, payload.summary)
        except RequestError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        if record is None:
            raise HTTPException(status_code=404, detail="找不到逐字稿")
        return _public_transcript(
            record,
            user.id,
            summary=service.read_summary(user.id, record),
            summary_log=service.summary_log(user.id, record.id),
        )

    @app.delete("/api/transcripts/{transcript_id}/summary")
    def delete_transcript_summary(transcript_id: str, request: Request):
        user = current_user(request)
        try:
            record = service.delete_summary(user.id, transcript_id)
        except RequestError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        if record is None:
            raise HTTPException(status_code=404, detail="找不到逐字稿")
        return _public_transcript(
            record,
            user.id,
            summary=service.read_summary(user.id, record),
            summary_log=service.summary_log(user.id, record.id),
        )

    @app.post("/api/transcripts/{transcript_id}/summary/regenerate")
    def regenerate_transcript_summary(transcript_id: str, request: Request):
        user = current_user(request)
        try:
            record = service.regenerate_summary(user.id, transcript_id)
        except RequestError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        if record is None:
            raise HTTPException(status_code=404, detail="找不到逐字稿")
        return _public_transcript(
            record,
            user.id,
            summary=service.read_summary(user.id, record),
            summary_log=service.summary_log(user.id, record.id),
        )

    def spa():
        index = web_dir / "index.html"
        if not index.is_file():
            raise HTTPException(
                status_code=503,
                detail="前端尚未建置，請在 frontend 目錄執行 npm run build。",
            )
        return FileResponse(index)

    @app.get("/")
    def index(request: Request):
        if optional_user(request) is None:
            return RedirectResponse("/login", status_code=302)
        return spa()

    @app.get("/progress")
    def progress_page(request: Request):
        if optional_user(request) is None:
            return RedirectResponse("/login", status_code=302)
        return spa()

    @app.get("/login")
    def login_page(request: Request):
        if optional_user(request) is not None:
            return RedirectResponse("/", status_code=302)
        return spa()

    @app.get("/register")
    def register_page(request: Request):
        if optional_user(request) is not None:
            return RedirectResponse("/", status_code=302)
        return spa()

    @app.get("/background1.jpg")
    def login_background():
        path = web_dir / "background1.jpg"
        if not path.is_file():
            raise HTTPException(status_code=404, detail="找不到背景圖")
        return FileResponse(path)

    assets_dir = web_dir / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")
    return app


def _public_user(user: User) -> dict[str, str]:
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
    }


def _public_transcript(
    record: Transcript,
    owner_id: str,
    *,
    summary: str | None = None,
    summary_log: dict[str, object] | None = None,
) -> dict[str, object]:
    payload = asdict(record)
    payload.pop("summary_filename", None)
    payload["tags"] = list(record.tags)
    payload["json_file"] = f"{owner_id}/{record.id}.json"
    if summary is not None:
        payload["summary"] = summary
    if summary_log is not None:
        payload["summary_log"] = summary_log
    return payload


def _public_job(job: Job) -> dict[str, object]:
    return {
        "id": job.id,
        "status": job.status,
        "percent": job.percent,
        "stage": job.stage,
        "message": job.message,
        "filename": job.filename,
        "error": job.error,
        "transcript_id": job.transcript_id,
    }
