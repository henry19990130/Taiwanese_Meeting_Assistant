from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from breeze.meeting_summary.client import OllamaChatClient
from breeze.meeting_summary.export import export_markdown
from breeze.meeting_summary.io import read_transcript_file
from breeze.models import Transcript

TokenCallback = Callable[[str], None]


class MeetingSummaryService:
    """讀逐字稿、呼叫 LLM、寫出 Markdown。不碰 ASR 與帳號。"""

    def __init__(self, client: OllamaChatClient | None = None):
        self._client = client or OllamaChatClient()

    def summarize_text(
        self,
        transcript: str,
        output_dir: Path,
        *,
        source_name: str,
        created_at: str,
        on_token: TokenCallback | None = None,
        when: datetime | None = None,
    ) -> Path:
        markdown = self._client.summarize(
            transcript,
            source_name=source_name,
            created_at=created_at,
            on_token=on_token,
        )
        stamp = when or _parse_created_at(created_at)
        return export_markdown(markdown, output_dir, stamp)

    def summarize_file(
        self,
        path: Path,
        output_dir: Path,
        *,
        on_token: TokenCallback | None = None,
    ) -> Path:
        text = read_transcript_file(path)
        created_at = datetime.now().astimezone().isoformat(timespec="seconds")
        return self.summarize_text(
            text,
            output_dir,
            source_name=path.name,
            created_at=created_at,
            on_token=on_token,
        )

    def summarize_transcript(self, transcript: Transcript, output_dir: Path) -> Path:
        return self.summarize_text(
            transcript.text,
            output_dir,
            source_name=transcript.source_filename,
            created_at=transcript.created_at,
        )


def _parse_created_at(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return datetime.now().astimezone()
