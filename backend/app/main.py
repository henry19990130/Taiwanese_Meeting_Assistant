from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import config
from app.routers import assistant, auth, glossary, meetings
from app.security.headers import SecurityHeadersMiddleware
from app.services import meeting_service

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    meeting_service.on_startup()
    yield


app = FastAPI(
    title="台語 AI 會議助理",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.add_middleware(SecurityHeadersMiddleware)
app.include_router(auth.router)
app.include_router(meetings.router)
app.include_router(glossary.router)
app.include_router(assistant.router)


@app.get("/api/v1/health", tags=["system"])
def health() -> dict:
    return {"status": "ok"}


app.mount("/", StaticFiles(directory=config.FRONTEND_DIR / "dist", html=True), name="frontend")
