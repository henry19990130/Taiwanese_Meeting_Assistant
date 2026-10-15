import io
import math
import struct
import threading
import wave
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from breeze.api import create_app
from breeze.audio import FfmpegConverter
from breeze.identity.service import AuthService
from breeze.identity.store import IdentityStore
from breeze.jobs import MemoryJobStore
from breeze.models import Recognition
from breeze.service import TranscriptionService
from breeze.settings import load_settings
from breeze.store import UserTranscriptStores

PASSWORD = "Abcdefghijk1"


class FakeRecognizer:
    def __init__(self):
        self.calls = []

    def available(self) -> bool:
        return True

    def loaded(self) -> bool:
        return True

    def device_name(self) -> str:
        return "cpu"

    def transcribe(self, wav_path: Path) -> Recognition:
        self.calls.append(wav_path)
        data = wav_path.read_bytes()
        if data[0:4] != b"RIFF" or data[8:12] != b"WAVE":
            raise AssertionError("辨識器收到的不是 WAV")
        return Recognition(text="測試逐字稿", model="Breeze-ASR-26", device="cpu")


class BlockingRecognizer(FakeRecognizer):
    def __init__(self):
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()

    def transcribe(self, wav_path: Path) -> Recognition:
        self.started.set()
        if not self.release.wait(timeout=5):
            raise TimeoutError("測試閘門逾時")
        return super().transcribe(wav_path)


def tone_wav() -> bytes:
    buffer = io.BytesIO()
    rate = 16000
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        frames = bytearray()
        for index in range(rate // 10):
            sample = int(8000 * math.sin(2 * math.pi * 440 * index / rate))
            frames.extend(struct.pack("<h", sample))
        handle.writeframes(bytes(frames))
    return buffer.getvalue()


def build_app(temporary: str, recognizer=None, **auth_kwargs):
    settings = load_settings()
    root = Path(temporary)
    auth = AuthService(
        IdentityStore(root / "identity.sqlite"),
        max_failures=auth_kwargs.get("max_failures", 5),
        lockout_seconds=auth_kwargs.get("lockout_seconds", 15 * 60),
        session_hours=auth_kwargs.get("session_hours", 12),
        clock=auth_kwargs.get("clock"),
    )
    service = TranscriptionService(
        converter=FfmpegConverter(settings.ffmpeg_path),
        recognizer=recognizer or FakeRecognizer(),
        stores=UserTranscriptStores(root / "transcripts"),
        jobs=MemoryJobStore(),
        allowed_suffixes=settings.allowed_suffixes,
        max_upload_bytes=settings.max_upload_bytes,
    )
    app = create_app(service, auth, settings.web_dir)
    return settings, auth, service, root, app


def authed_client(app, username: str = "alice", password: str = PASSWORD) -> TestClient:
    client = TestClient(app)
    created = client.post(
        "/api/auth/register",
        json={"username": username, "password": password},
    )
    if created.status_code not in {200, 409}:
        raise AssertionError(created.text)
    if created.status_code == 409:
        logged = client.post(
            "/api/auth/login",
            json={"username": username, "password": password},
        )
        if logged.status_code != 200:
            raise AssertionError(logged.text)
    return client
