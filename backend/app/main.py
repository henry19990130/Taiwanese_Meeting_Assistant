from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import config
from app.routers import assistant, auth, glossary, meetings
from app.services import asr_models, meeting_service

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    meeting_service.on_startup()
    yield


app = FastAPI(title="台語 AI 會議助理", version="0.1.0", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(meetings.router)
app.include_router(glossary.router)
app.include_router(assistant.router)


@app.get("/api/v1/health", tags=["system"])
def health() -> dict:
    return {
        "status": "ok",
        "asr_engine": config.ASR_ENGINE,
        "asr_models": {k: v["model_id"] for k, v in asr_models.LANGUAGES.items()},
        "llm_backend": config.LLM_BACKEND,
        "llm_model": config.LLM_MODEL,
        "llm_temperature": config.LLM_TEMPERATURE,
        "llm_seed": config.LLM_SEED,
        "llm_num_ctx": config.LLM_NUM_CTX,
        "llm_think": config.LLM_THINK,
    }


app.mount("/", StaticFiles(directory=config.FRONTEND_DIR, html=True), name="frontend")
