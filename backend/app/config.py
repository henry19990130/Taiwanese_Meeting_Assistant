from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent

load_dotenv(PROJECT_DIR / ".env")

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "meeting_assistant")
DB_USER = os.getenv("DB_USER", "meeting")
DB_PASSWORD = os.getenv("DB_PASSWORD", "meeting")
DATABASE_URL = " ".join(
    f"{k}='{str(v).replace(chr(92), chr(92) * 2).replace(chr(39), chr(92) + chr(39))}'"
    for k, v in {
        "host": DB_HOST, "port": DB_PORT, "dbname": DB_NAME, "user": DB_USER, "password": DB_PASSWORD,
    }.items()
)

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen3.8:27b")
LLM_BACKEND = os.getenv("LLM_BACKEND", "ollama").lower()
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0"))
LLM_SEED = int(os.getenv("LLM_SEED", "42"))
LLM_NUM_CTX = int(os.getenv("LLM_NUM_CTX", "40960"))
LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "900"))
_think = os.getenv("LLM_THINK", "true").strip().lower()
LLM_THINK = None if _think == "" else _think in ("1", "true", "yes")

TYPO_CHECK = os.getenv("TYPO_CHECK", "true").strip().lower() in ("1", "true", "yes")
TYPO_CHUNK = int(os.getenv("TYPO_CHUNK", "40"))
TYPO_THINK = os.getenv("TYPO_THINK", "false").strip().lower() in ("1", "true", "yes")

ASSISTANT_THINK = os.getenv("ASSISTANT_THINK", "false").strip().lower() in ("1", "true", "yes")
ASSISTANT_MAX_STEPS = int(os.getenv("ASSISTANT_MAX_STEPS", "5"))
TIMEZONE = os.getenv("TIMEZONE", "Asia/Taipei")

ASR_ENGINE = os.getenv("ASR_ENGINE", "hf").lower()
ASR_TO_TRADITIONAL = os.getenv("ASR_TO_TRADITIONAL", "true").strip().lower() in ("1", "true", "yes")

ASR_HALLUCINATION_MAX_S = float(os.getenv("ASR_HALLUCINATION_MAX_S", "2.0"))

ASR_MERGE_GAP_S = float(os.getenv("ASR_MERGE_GAP_S", "1.0"))
ASR_MERGE_MAX_S = float(os.getenv("ASR_MERGE_MAX_S", "20"))
ASR_MERGE_SHORT_S = float(os.getenv("ASR_MERGE_SHORT_S", "3.0"))
ASR_DROP_QUIET_DB = float(os.getenv("ASR_DROP_QUIET_DB", "35"))

AUDIO_DIR = Path(os.getenv("AUDIO_DIR", str(BACKEND_DIR / "storage" / "audio")))
AUDIO_DIR.mkdir(parents=True, exist_ok=True)
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "500"))
FRONTEND_DIR = PROJECT_DIR / "frontend"

SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", "28800"))
