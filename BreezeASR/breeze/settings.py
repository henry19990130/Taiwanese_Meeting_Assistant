import os
from dataclasses import dataclass
from pathlib import Path


ALLOWED_SUFFIXES = frozenset({
    ".wav",
    ".mp3",
    ".m4a",
    ".flac",
    ".ogg",
    ".webm",
    ".mp4",
    ".aac",
})


@dataclass(frozen=True)
class Settings:
    root: Path
    model_dir: Path
    ffmpeg_path: Path
    transcripts_dir: Path
    summaries_dir: Path
    summary_logs_dir: Path
    identity_dir: Path
    web_dir: Path
    max_upload_bytes: int
    allowed_suffixes: frozenset[str]
    login_max_failures: int
    lockout_seconds: int
    session_hours: int


def load_settings() -> Settings:
    root = Path(__file__).resolve().parents[1]
    return Settings(
        root=root,
        model_dir=Path(os.environ.get("BREEZEASR_MODEL_DIR", root / "model")),
        ffmpeg_path=Path(
            os.environ.get("BREEZEASR_FFMPEG", root / "ffmpeg" / "bin" / "ffmpeg.exe")
        ),
        transcripts_dir=Path(
            os.environ.get("BREEZEASR_TRANSCRIPTS_DIR", root / "data" / "transcripts")
        ),
        summaries_dir=Path(
            os.environ.get("BREEZEASR_SUMMARIES_DIR", root / "data" / "summaries")
        ),
        summary_logs_dir=Path(
            os.environ.get("BREEZEASR_SUMMARY_LOGS_DIR", root / "data" / "summary_logs")
        ),
        identity_dir=Path(
            os.environ.get("BREEZEASR_IDENTITY_DIR", root / "data" / "identity")
        ),
        web_dir=Path(os.environ.get("BREEZEASR_WEB_DIR", root / "frontend" / "dist")),
        max_upload_bytes=int(os.environ.get("BREEZEASR_MAX_UPLOAD_BYTES", 200 * 1024 * 1024)),
        allowed_suffixes=ALLOWED_SUFFIXES,
        login_max_failures=int(os.environ.get("BREEZEASR_LOGIN_MAX_FAILURES", 5)),
        lockout_seconds=int(os.environ.get("BREEZEASR_LOCKOUT_SECONDS", 15 * 60)),
        session_hours=int(os.environ.get("BREEZEASR_SESSION_HOURS", 12)),
    )
