from __future__ import annotations

import gc
import logging
import os
import threading
from pathlib import Path

os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

from taigi_asr.config import (
    DEFAULT_BEAM_SIZE,
    DEFAULT_BEST_OF,
    DEFAULT_LANGUAGE,
    DEFAULT_PATIENCE,
    DEFAULT_TEMPERATURE,
    DEFAULT_VAD_MIN_SILENCE_MS,
    DEFAULT_VAD_SPEECH_PAD_MS,
    FASTER_WHISPER_MODEL_ID,
)
from taigi_asr.errors import ModelLoadError, TranscriptionError
from taigi_asr.segments import TimestampedSegment

log = logging.getLogger(__name__)


class FasterWhisperEngine:

    MODEL_ID: str = FASTER_WHISPER_MODEL_ID

    def __init__(
        self,
        device: str = "cuda",
        compute_type: str = "int8_float16",
        batch_size: int = 4,
        cpu_threads: int | None = None,
        *,
        beam_size: int = DEFAULT_BEAM_SIZE,
        best_of: int = DEFAULT_BEST_OF,
        patience: float = DEFAULT_PATIENCE,
        temperature: float = DEFAULT_TEMPERATURE,
    ) -> None:
        self.device = device
        self.compute_type = compute_type
        self.batch_size = batch_size
        self.cpu_threads = cpu_threads or (os.cpu_count() or 4)
        self.beam_size = beam_size
        self.best_of = best_of
        self.patience = patience
        self.temperature = temperature
        self._model = None
        self._batched = None
        self._loaded = False
        self._lock = threading.Lock()

    def load(self) -> None:
        with self._lock:
            if self._loaded:
                return
            try:
                from faster_whisper import BatchedInferencePipeline, WhisperModel
            except ImportError as exc:
                raise ModelLoadError(
                    "faster-whisper not installed. Run: pip install faster-whisper"
                ) from exc

            try:
                log.info(
                    "Loading %s on %s (compute_type=%s)…",
                    self.MODEL_ID,
                    self.device,
                    self.compute_type,
                )
                self._model = WhisperModel(
                    self.MODEL_ID,
                    device=self.device,
                    compute_type=self.compute_type,
                    cpu_threads=self.cpu_threads,
                )
                self._batched = BatchedInferencePipeline(model=self._model)
                self._prewarm()
                self._loaded = True
                log.info("Faster-Whisper engine loaded.")
            except Exception as exc:
                raise ModelLoadError(f"Failed to load faster-whisper model: {exc}") from exc

    def _prewarm(self) -> None:
        if self.device == "cpu":
            return
        try:
            import numpy as np

            dummy = np.zeros(16000, dtype=np.float32)
            seg_iter, _ = self._batched.transcribe(
                dummy,
                batch_size=self.batch_size,
                language=DEFAULT_LANGUAGE,
                beam_size=1,
                best_of=1,
                temperature=0.0,
                vad_filter=False,
                word_timestamps=False,
                without_timestamps=True,
            )
            for _ in seg_iter:
                pass
            log.debug("Faster-Whisper pre-warm complete.")
        except Exception as exc:
            log.warning(
                "Pre-warm failed (%s); first transcribe will pay JIT cost.",
                exc,
            )

    def is_loaded(self) -> bool:
        return self._loaded

    def transcribe(
        self,
        wav_path: str | Path,
        *,
        word_timestamps: bool = False,
        language: str = DEFAULT_LANGUAGE,
        beam_size: int | None = None,
        best_of: int | None = None,
        patience: float | None = None,
        temperature: float | None = None,
        vad_filter: bool = True,
    ) -> list[TimestampedSegment]:
        beam_size = beam_size if beam_size is not None else self.beam_size
        best_of = best_of if best_of is not None else self.best_of
        patience = patience if patience is not None else self.patience
        temperature = temperature if temperature is not None else self.temperature
        with self._lock:
            if not self._loaded:
                pass
        if not self._loaded:
            self.load()
        assert self._batched is not None

        try:
            import numpy as np
            import soundfile as sf

            audio, sr = sf.read(str(wav_path), dtype="float32")
            if audio.ndim > 1:
                audio = audio.mean(axis=1)
            if sr != 16000:
                raise TranscriptionError(f"預期 16 kHz WAV，收到 {sr} Hz：{wav_path}")
            audio = np.ascontiguousarray(audio)

            segments_iter, _info = self._batched.transcribe(
                audio,
                batch_size=self.batch_size,
                language=language,
                beam_size=beam_size,
                best_of=best_of,
                patience=patience,
                temperature=temperature,
                vad_filter=vad_filter,
                vad_parameters={
                    "min_silence_duration_ms": DEFAULT_VAD_MIN_SILENCE_MS,
                    "speech_pad_ms": DEFAULT_VAD_SPEECH_PAD_MS,
                },
                word_timestamps=word_timestamps,
                without_timestamps=False,
            )
            out: list[TimestampedSegment] = []
            for seg in segments_iter:
                text = (seg.text or "").strip()
                if not text:
                    continue
                start = float(seg.start) if seg.start is not None else 0.0
                end = float(seg.end) if seg.end is not None else start + 1.0
                out.append(TimestampedSegment(start_time=start, end_time=end, text=text))
            return out
        except Exception as exc:
            raise TranscriptionError(f"faster-whisper inference failed: {exc}") from exc

    def language_probs(self, windows, candidates: list[str], sr: int = 16000) -> dict[str, float]:
        if not self._loaded:
            self.load()
        assert self._model is not None
        if not windows:
            return {}
        totals = {c: 0.0 for c in candidates}
        for w in windows:
            _segs, info = self._model.transcribe(
                w, language=None, beam_size=1, vad_filter=False, without_timestamps=True,
            )
            probs = dict(getattr(info, "all_language_probs", None) or [(info.language, info.language_probability)])
            sub = {c: float(probs.get(c, 0.0)) for c in candidates}
            norm = sum(sub.values())
            if norm > 0:
                for c in candidates:
                    totals[c] += sub[c] / norm
        return {c: v / len(windows) for c, v in totals.items()}

    def transcribe_regions(self, audio, regions, sr: int = 16000, language: str | None = None) -> list[str]:
        return self.transcribe_clips([audio[int(s * sr): int(e * sr)] for s, e in regions], sr, language)

    def transcribe_clips(self, clips, sr: int = 16000, language: str | None = None) -> list[str]:
        if not self._loaded:
            self.load()
        assert self._model is not None
        texts: list[str] = []
        try:
            for clip in clips:
                segs, _ = self._model.transcribe(
                    clip,
                    language=language or DEFAULT_LANGUAGE,
                    beam_size=self.beam_size,
                    best_of=self.best_of,
                    temperature=self.temperature,
                    vad_filter=False,
                    without_timestamps=True,
                    condition_on_previous_text=False,
                )
                texts.append("".join(seg.text for seg in segs).strip())
        except Exception as exc:
            raise TranscriptionError(f"faster-whisper inference failed: {exc}") from exc
        return texts

    def unload(self) -> None:
        with self._lock:
            if self._batched is not None:
                del self._batched
                self._batched = None
            if self._model is not None:
                del self._model
                self._model = None
            self._loaded = False
            try:
                import torch

                gc.collect()
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except ImportError:
                pass

    @classmethod
    def preload(cls) -> None:
        try:
            from huggingface_hub import snapshot_download

            snapshot_download(cls.MODEL_ID)
            log.info("Faster-Whisper Taiwan-Tongues-ASR-CE model cached.")
        except Exception as exc:
            log.warning("Preload failed (will download on first run): %s", exc)
