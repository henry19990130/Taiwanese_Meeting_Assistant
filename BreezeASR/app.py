import os

from breeze.api import create_app
from breeze.asr import BreezeRecognizer
from breeze.audio import FfmpegConverter, prefer_local_ffmpeg
from breeze.identity.service import AuthService
from breeze.identity.store import IdentityStore
from breeze.jobs import MemoryJobStore
from breeze.meeting_summary import MeetingSummaryService, OllamaChatClient
from breeze.meeting_summary.journal import SummaryJournal
from breeze.service import TranscriptionService
from breeze.tag_suggest import LlmTagSuggester
from breeze.settings import load_settings
from breeze.store import UserTranscriptStores

settings = load_settings()
prefer_local_ffmpeg(settings.ffmpeg_path)
auth = AuthService(
    IdentityStore(settings.identity_dir / "identity.sqlite"),
    max_failures=settings.login_max_failures,
    lockout_seconds=settings.lockout_seconds,
    session_hours=settings.session_hours,
)

ollama_kwargs = {
    "host": os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"),
    "temperature": 0.2,
}
if "OLLAMA_MODEL" in os.environ:
    ollama_kwargs["model"] = os.environ["OLLAMA_MODEL"]
chat = OllamaChatClient(**ollama_kwargs)

service = TranscriptionService(
    converter=FfmpegConverter(settings.ffmpeg_path),
    recognizer=BreezeRecognizer(settings.model_dir),
    stores=UserTranscriptStores(settings.transcripts_dir),
    jobs=MemoryJobStore(),
    allowed_suffixes=settings.allowed_suffixes,
    max_upload_bytes=settings.max_upload_bytes,
    summarizer=MeetingSummaryService(chat),
    summaries_dir=settings.summaries_dir,
    summary_journal=SummaryJournal(settings.summary_logs_dir),
    tag_suggester=LlmTagSuggester(chat),
)
app = create_app(service, auth, settings.web_dir)
