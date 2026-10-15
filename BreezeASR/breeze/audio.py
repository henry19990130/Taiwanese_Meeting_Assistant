import os
import subprocess
from pathlib import Path


def prefer_local_ffmpeg(ffmpeg_path: Path) -> None:
    """讓後續辨識讀音檔時找得到專案內的 ffmpeg，不用另外安裝到系統 PATH。"""
    directory = str(ffmpeg_path.resolve().parent)
    parts = [part for part in os.environ.get("PATH", "").split(os.pathsep) if part]
    if directory not in parts:
        os.environ["PATH"] = directory + os.pathsep + os.environ.get("PATH", "")


class AudioError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


class FfmpegConverter:
    """把上傳的音檔轉成 Whisper 要的 16 kHz、單聲道、16-bit WAV。"""

    def __init__(self, ffmpeg_path: Path):
        self._ffmpeg = ffmpeg_path

    def available(self) -> bool:
        return self._ffmpeg.is_file()

    def to_wav(self, source: Path, destination: Path) -> None:
        if not self.available():
            raise AudioError(f"找不到 ffmpeg：{self._ffmpeg}", status_code=500)

        try:
            completed = subprocess.run(
                [
                    str(self._ffmpeg),
                    "-y",
                    "-i",
                    str(source),
                    "-vn",
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    "-c:a",
                    "pcm_s16le",
                    str(destination),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=600,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise AudioError("ffmpeg 轉檔逾時", status_code=500) from exc
        if completed.returncode != 0 or not destination.is_file() or destination.stat().st_size == 0:
            raise AudioError(_ffmpeg_message(completed.stderr))


def _ffmpeg_message(stderr: str) -> str:
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    message = lines[-1] if lines else "ffmpeg 轉檔失敗"
    return message[:300]
