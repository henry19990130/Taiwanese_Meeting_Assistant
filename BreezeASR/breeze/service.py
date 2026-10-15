import threading
import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from breeze.jobs import Job
from breeze.models import Transcript
from breeze.meeting_summary.errors import SummaryError
from breeze.meeting_summary.journal import SummaryJournal
from breeze.ports import (
    AudioConverter,
    JobRepository,
    MeetingSummarizer,
    SpeechRecognizer,
    TagSuggester,
    TranscriptStoreFactory,
)
from breeze.tags import TagError, normalize_tags
from breeze.titles import TitleError, normalize_title

ProgressFn = Callable[[str, int, str], None]


class RequestError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


class TranscriptionService:
    """上傳、轉檔、辨識、存 JSON。逐字稿路徑由使用者 id 決定。"""

    def __init__(
        self,
        converter: AudioConverter,
        recognizer: SpeechRecognizer,
        stores: TranscriptStoreFactory,
        jobs: JobRepository,
        *,
        allowed_suffixes: frozenset[str],
        max_upload_bytes: int,
        summarizer: MeetingSummarizer | None = None,
        summaries_dir: Path | None = None,
        summary_journal: SummaryJournal | None = None,
        tag_suggester: TagSuggester | None = None,
    ):
        self._converter = converter
        self._recognizer = recognizer
        self._stores = stores
        self._jobs = jobs
        self._allowed_suffixes = allowed_suffixes
        self._max_upload_bytes = max_upload_bytes
        self._summarizer = summarizer
        self._summaries_dir = summaries_dir
        self._summary_journal = summary_journal
        self._tag_suggester = tag_suggester

    def status(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "status": "ok",
            "model": "Breeze-ASR-26",
            "ffmpeg": self._converter.available(),
            "model_files": self._recognizer.available(),
            "model_loaded": self._recognizer.loaded(),
        }
        if self._recognizer.loaded():
            payload["device"] = self._recognizer.device_name()
        return payload

    def transcribe_bytes(
        self,
        owner_id: str,
        filename: str,
        content: bytes,
        on_progress: ProgressFn | None = None,
    ) -> Transcript:
        safe_name, suffix = self._validate_upload(filename, content)
        return self._run_pipeline(owner_id, safe_name, suffix, content, on_progress)

    def start_job(self, owner_id: str, filename: str, content: bytes) -> Job:
        safe_name, suffix = self._validate_upload(filename, content)
        job = self._jobs.create(
            Job(
                id=uuid.uuid4().hex,
                owner_id=owner_id,
                status="queued",
                percent=5,
                stage="queued",
                message="已收到音檔，等待轉檔。",
                filename=safe_name,
            )
        )
        worker = threading.Thread(
            target=self._run_job,
            args=(job.id, owner_id, safe_name, suffix, content),
            daemon=True,
        )
        worker.start()
        return job

    def get_job(self, owner_id: str, job_id: str) -> Job | None:
        job = self._jobs.get(job_id)
        if job is None or job.owner_id != owner_id:
            return None
        return job

    def list_transcripts(self, owner_id: str) -> list[Transcript]:
        return self._stores.for_user(owner_id).list_all()

    def get_transcript(self, owner_id: str, transcript_id: str) -> Transcript | None:
        return self._stores.for_user(owner_id).get(transcript_id)

    def read_summary(self, owner_id: str, record: Transcript) -> str:
        name = Path(record.summary_filename).name
        if not name or name != record.summary_filename or self._summaries_dir is None:
            return ""
        path = self._summaries_dir / owner_id / name
        if not path.is_file():
            return ""
        return path.read_text(encoding="utf-8")

    def summary_log(self, owner_id: str, transcript_id: str) -> dict[str, object]:
        if self._summary_journal is None:
            return {"original": "", "edited": False, "regenerated": False, "deleted": False, "versions": []}
        return self._summary_journal.read(owner_id, transcript_id)

    def replace_summary(
        self,
        owner_id: str,
        transcript_id: str,
        summary: object,
    ) -> Transcript | None:
        if not isinstance(summary, str) or not summary.strip():
            raise RequestError("會議紀錄不能是空白")
        store = self._stores.for_user(owner_id)
        record = store.get(transcript_id)
        if record is None:
            return None
        previous = self.read_summary(owner_id, record)
        record = self._write_summary(owner_id, record, summary.strip())
        self._remember_summary(owner_id, transcript_id, "edit", previous)
        return record

    def regenerate_summary(self, owner_id: str, transcript_id: str) -> Transcript | None:
        if self._summarizer is None or self._summaries_dir is None:
            raise RequestError("尚未設定摘要模型", status_code=503)
        store = self._stores.for_user(owner_id)
        record = store.get(transcript_id)
        if record is None:
            return None
        if not record.text.strip():
            raise RequestError("沒有逐字稿可以重新生成摘要")
        previous = self.read_summary(owner_id, record)
        try:
            summary_path = self._summarizer.summarize_transcript(
                record,
                self._summaries_dir / owner_id,
            )
        except SummaryError as exc:
            raise RequestError(str(exc), status_code=502) from exc
        record = store.save(replace(record, summary_filename=summary_path.name))
        self._remember_summary(owner_id, transcript_id, "regenerate", previous)
        return record

    def delete_summary(self, owner_id: str, transcript_id: str) -> Transcript | None:
        store = self._stores.for_user(owner_id)
        record = store.get(transcript_id)
        if record is None:
            return None
        previous = self.read_summary(owner_id, record)
        if not previous.strip():
            raise RequestError("沒有摘要可以刪除")
        self._remove_summary_file(owner_id, record)
        self._remember_summary(owner_id, transcript_id, "delete", previous)
        return record

    def delete_transcript(self, owner_id: str, transcript_id: str) -> bool:
        store = self._stores.for_user(owner_id)
        record = store.get(transcript_id)
        if record is None:
            return False
        previous = self.read_summary(owner_id, record)
        if not store.delete(transcript_id):
            return False
        self._remember_summary(owner_id, transcript_id, "delete", previous)
        return True

    def _remember_summary(
        self,
        owner_id: str,
        transcript_id: str,
        action: str,
        previous: str,
    ) -> None:
        if self._summary_journal is None:
            return
        self._summary_journal.record(owner_id, transcript_id, action, previous)

    def _write_summary(self, owner_id: str, record: Transcript, text: str) -> Transcript:
        if self._summaries_dir is None:
            raise RequestError("尚未設定摘要資料夾", status_code=503)
        folder = self._summaries_dir / owner_id
        folder.mkdir(parents=True, exist_ok=True)
        name = Path(record.summary_filename).name
        if name and name == record.summary_filename:
            path = folder / name
        else:
            stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
            path = folder / f"會議紀錄_{stamp}.md"
            record = self._stores.for_user(owner_id).save(
                replace(record, summary_filename=path.name)
            )
        path.write_text(text.rstrip() + "\n", encoding="utf-8")
        return record

    def _remove_summary_file(self, owner_id: str, record: Transcript) -> None:
        if self._summaries_dir is None:
            raise RequestError("尚未設定摘要資料夾", status_code=503)
        name = Path(record.summary_filename).name
        if not name or name != record.summary_filename:
            return
        path = self._summaries_dir / owner_id / name
        if path.is_file():
            path.unlink()

    def update_transcript_tags(
        self,
        owner_id: str,
        transcript_id: str,
        tags: object,
    ) -> Transcript | None:
        try:
            cleaned = normalize_tags(tags)
        except TagError as exc:
            raise RequestError(str(exc)) from exc
        store = self._stores.for_user(owner_id)
        record = store.get(transcript_id)
        if record is None:
            return None
        return store.save(replace(record, tags=tuple(cleaned)))

    def suggest_tags(self, owner_id: str, transcript_id: str) -> list[str] | None:
        store = self._stores.for_user(owner_id)
        record = store.get(transcript_id)
        if record is None:
            return None
        if self._tag_suggester is None:
            raise RequestError("標籤推薦尚未設定", status_code=503)
        source = self.read_summary(owner_id, record).strip() or record.text.strip()
        if not source:
            raise RequestError("沒有內容可以推薦標籤")
        try:
            suggested = self._tag_suggester.suggest(source)
        except SummaryError as exc:
            raise RequestError(str(exc), status_code=502) from exc
        if not isinstance(suggested, list):
            raise RequestError("標籤推薦格式不正確", status_code=502)
        current = {tag.casefold() for tag in record.tags}
        kept: list[str] = []
        seen: set[str] = set()
        for tag in suggested:
            if not isinstance(tag, str):
                continue
            try:
                cleaned = normalize_tags([tag])[0]
            except TagError:
                continue
            key = cleaned.casefold()
            if key in current or key in seen:
                continue
            seen.add(key)
            kept.append(cleaned)
        return kept

    def update_transcript_title(
        self,
        owner_id: str,
        transcript_id: str,
        title: object,
    ) -> Transcript | None:
        try:
            cleaned = normalize_title(title)
        except TitleError as exc:
            raise RequestError(str(exc)) from exc
        store = self._stores.for_user(owner_id)
        record = store.get(transcript_id)
        if record is None:
            return None
        return store.save(replace(record, title=cleaned))

    def _validate_upload(self, filename: str, content: bytes) -> tuple[str, str]:
        safe_name = Path(filename).name or "audio"
        suffix = Path(safe_name).suffix.lower()
        if suffix not in self._allowed_suffixes:
            raise RequestError(f"不支援的音檔格式：{suffix or '（沒有副檔名）'}")
        if not content:
            raise RequestError("音檔是空的")
        if len(content) > self._max_upload_bytes:
            limit_mb = self._max_upload_bytes // (1024 * 1024)
            raise RequestError(f"音檔超過 {limit_mb} MB", status_code=413)
        if len(safe_name) > 180:
            safe_name = safe_name[-180:]
        return safe_name, suffix

    def _run_pipeline(
        self,
        owner_id: str,
        safe_name: str,
        suffix: str,
        content: bytes,
        on_progress: ProgressFn | None,
    ) -> Transcript:
        def report(stage: str, percent: int, message: str) -> None:
            if on_progress is not None:
                on_progress(stage, percent, message)

        with TemporaryDirectory() as temporary:
            folder = Path(temporary)
            source = folder / f"upload{suffix}"
            wav_path = folder / "speech.wav"
            source.write_bytes(content)
            report("converting", 20, "正在用 ffmpeg 轉成 16 kHz 單聲道 WAV。")
            self._converter.to_wav(source, wav_path)
            report("recognizing", 45, "正在用 Breeze-ASR-26 辨識語音。")
            recognition = self._recognizer.transcribe(wav_path)

        report("saving", 90, "正在把逐字稿寫入 JSON。")
        record = self._stores.for_user(owner_id).save(
            Transcript(
                id=uuid.uuid4().hex,
                source_filename=safe_name,
                text=recognition.text,
                model=recognition.model,
                device=recognition.device,
                created_at=datetime.now().astimezone().isoformat(timespec="seconds"),
                tags=(),
            )
        )
        if self._summarizer is None or self._summaries_dir is None:
            report("done", 100, "辨識完成。")
            return record
        report("summarizing", 95, "正在用本機 LLM 整理會議摘要。")
        try:
            summary_path = self._summarizer.summarize_transcript(
                record,
                self._summaries_dir / owner_id,
            )
        except SummaryError as exc:
            report("done", 100, f"辨識完成。摘要未產生：{exc}")
            return record
        record = self._stores.for_user(owner_id).save(
            replace(record, summary_filename=summary_path.name),
        )
        report("done", 100, f"辨識完成。會議紀錄已存成 {summary_path.name}。")
        return record

    def _run_job(
        self,
        job_id: str,
        owner_id: str,
        safe_name: str,
        suffix: str,
        content: bytes,
    ) -> None:
        def on_progress(stage: str, percent: int, message: str) -> None:
            self._jobs.update(
                job_id,
                status="running",
                stage=stage,
                percent=percent,
                message=message,
            )

        self._jobs.update(
            job_id,
            status="running",
            stage="converting",
            percent=10,
            message="開始處理音檔。",
        )
        try:
            record = self._run_pipeline(owner_id, safe_name, suffix, content, on_progress)
        except Exception as exc:
            self._jobs.update(
                job_id,
                status="failed",
                stage="failed",
                message="辨識失敗。",
                error=f"{type(exc).__name__}: {exc}",
            )
            return
        self._jobs.update(
            job_id,
            status="done",
            stage="done",
            percent=100,
            message="辨識完成。",
            transcript_id=record.id,
            error=None,
        )
