from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent

load_dotenv(PROJECT_DIR / ".env")

_LOCAL_DB_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_SSLMODES = frozenset({"disable", "allow", "prefer", "require", "verify-ca", "verify-full"})


def _raw(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def database_settings() -> dict:
    """沒有帳密就拒絕啟動。連線只允許本機，並把 sslmode 放進連線字串。"""
    user = _raw("DB_USER")
    password = _raw("DB_PASSWORD")
    if not user or not password:
        raise RuntimeError("必須設定 DB_USER 與 DB_PASSWORD，不再使用預設帳密")
    host = _raw("DB_HOST") or "localhost"
    if host not in _LOCAL_DB_HOSTS:
        raise RuntimeError(f"資料庫只允許連本機，目前是 {host}")
    sslmode = _raw("DB_SSLMODE") or "prefer"
    if sslmode not in _SSLMODES:
        raise RuntimeError("DB_SSLMODE 不合法")
    name = _raw("DB_NAME") or "meeting_assistant"
    port = int(_raw("DB_PORT") or "5432")
    parts = {
        "host": host, "port": port, "dbname": name, "user": user, "password": password,
        "sslmode": sslmode,
    }
    url = " ".join(
        f"{k}='{str(v).replace(chr(92), chr(92) * 2).replace(chr(39), chr(92) + chr(39))}'"
        for k, v in parts.items()
    )
    return {"host": host, "port": port, "name": name, "user": user, "password": password,
            "sslmode": sslmode, "url": url}


_db = database_settings()
DB_HOST = _db["host"]
DB_PORT = _db["port"]
DB_NAME = _db["name"]
DB_USER = _db["user"]
DB_PASSWORD = _db["password"]
DB_SSLMODE = _db["sslmode"]
DATABASE_URL = _db["url"]

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
ACCESS_TTL_SECONDS = 60 * 60
REFRESH_TTL_SECONDS = 30 * 24 * 60 * 60
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "true").strip().lower() in ("1", "true", "yes")
