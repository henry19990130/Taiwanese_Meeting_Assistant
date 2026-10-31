from __future__ import annotations

import gc
import logging
import os
import threading
from pathlib import Path

os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

from taigi_asr.config import (
    DEFAULT_CHUNK_LENGTH_S,
    DEFAULT_LANGUAGE,
    DEFAULT_MAX_NEW_TOKENS,
    DEFAULT_NO_REPEAT_NGRAM_SIZE,
    DEFAULT_STRIDE_LENGTH_S,
    HUGGINGFACE_MODEL_ID,
)
from taigi_asr.errors import InsufficientVRAMError, ModelLoadError, TranscriptionError
from taigi_asr.segments import TimestampedSegment

log = logging.getLogger(__name__)


class HuggingFaceEngine:

    MODEL_ID: str = HUGGINGFACE_MODEL_ID

    def __init__(
        self,
        device: str = "cuda",
        compute_type: str = "float16",
        batch_size: int = 4,
        chunk_length_s: int = DEFAULT_CHUNK_LENGTH_S,
    ) -> None:
        self.device = device
        self.compute_type = compute_type
        self.batch_size = batch_size
        self.chunk_length_s = chunk_length_s
        self.pipe = None
        self._loaded = False
        self._lock = threading.Lock()

    def load(self) -> None:
        with self._lock:
            if self._loaded:
                return
            try:
                import torch
                from transformers import (
                    AutoModelForSpeechSeq2Seq,
                    AutoProcessor,
                    pipeline,
                )
            except ImportError as exc:
                raise ModelLoadError(
                    'transformers / torch not installed. Run: pip install -e ".[hf]"'
                ) from exc

            try:
                processor = AutoProcessor.from_pretrained(self.MODEL_ID)

                model_kwargs: dict = {
                    "low_cpu_mem_usage": True,
                    "attn_implementation": "sdpa" if self.device != "cpu" else "eager",
                }

                dtype = torch.float16
                key = "torch_dtype"
                if self.compute_type == "int8":
                    try:
                        from transformers import BitsAndBytesConfig

                        model_kwargs["quantization_config"] = BitsAndBytesConfig(load_in_8bit=True)
                    except ImportError as exc:
                        raise InsufficientVRAMError(
                            "HuggingFace int8 path requires bitsandbytes, which failed "
                            "to import. Fall back to the FasterWhisperEngine."
                        ) from exc
                else:
                    import transformers
                    from packaging.version import Version

                    key = "dtype" if Version(transformers.__version__) >= Version("4.56") else "torch_dtype"
                    model_kwargs[key] = dtype

                model = AutoModelForSpeechSeq2Seq.from_pretrained(self.MODEL_ID, **model_kwargs)
                if self.compute_type != "int8":
                    model.to(self.device)

                if os.environ.get("TAIGI_ASR_TORCH_COMPILE") == "1":
                    try:
                        model = torch.compile(model, mode="reduce-overhead")
                    except Exception:
                        log.info("torch.compile unavailable; using eager mode.")

                self.pipe = pipeline(
                    "automatic-speech-recognition",
                    model=model,
                    tokenizer=processor.tokenizer,
                    feature_extractor=processor.feature_extractor,
                    device=self.device if self.compute_type != "int8" else None,
                    **({key: dtype} if self.compute_type != "int8" else {}),
                    chunk_length_s=self.chunk_length_s,
                    stride_length_s=DEFAULT_STRIDE_LENGTH_S,
                    return_timestamps=True,
                )

                if self.device != "cpu":
                    try:
                        import numpy as np

                        dummy = np.zeros(16000, dtype=np.float32)
                        self.pipe(
                            dummy,
                            generate_kwargs={
                                "language": DEFAULT_LANGUAGE,
                                "task": "transcribe",
                                "max_new_tokens": 10,
                            },
                        )
                    except Exception:
                        log.debug("CUDA warmup skipped.")

                self._loaded = True
            except InsufficientVRAMError:
                raise
            except Exception as exc:
                self.pipe = None
                try:
                    import torch

                    gc.collect()
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                except ImportError:
                    pass
                raise ModelLoadError(f"Failed to load HuggingFace model: {exc}") from exc

    def is_loaded(self) -> bool:
        return self._loaded

    def transcribe(
        self,
        wav_path: str | Path,
        *,
        word_timestamps: bool = False,
    ) -> list[TimestampedSegment]:
        if not self._loaded:
            self.load()
        assert self.pipe is not None

        try:
            result = self.pipe(
                str(wav_path),
                batch_size=self.batch_size,
                generate_kwargs={
                    "max_new_tokens": DEFAULT_MAX_NEW_TOKENS,
                    "language": DEFAULT_LANGUAGE,
                    "task": "transcribe",
                    "no_repeat_ngram_size": DEFAULT_NO_REPEAT_NGRAM_SIZE,
                },
                return_timestamps="word" if word_timestamps else True,
            )
        except Exception as exc:
            raise TranscriptionError(f"HuggingFace pipeline failed: {exc}") from exc

        out: list[TimestampedSegment] = []
        chunks = result.get("chunks")
        if isinstance(chunks, list):
            for chunk in chunks:
                text = (chunk.get("text") or "").strip()
                if not text:
                    continue
                ts = chunk.get("timestamp")
                if isinstance(ts, tuple) and len(ts) >= 2:
                    start = float(ts[0]) if ts[0] is not None else 0.0
                    end = float(ts[1]) if ts[1] is not None else start + 1.0
                else:
                    start, end = 0.0, 0.0
                out.append(TimestampedSegment(start, end, text))
        else:
            text = (result.get("text") or "").strip()
            if text:
                out.append(TimestampedSegment(0.0, 0.0, text))
        return out

    def language_probs(self, windows, candidates: list[str], sr: int = 16000) -> dict[str, float]:
        if not self._loaded:
            self.load()
        assert self.pipe is not None
        import torch

        model = self.pipe.model
        gen = model.generation_config
        lang_to_id = getattr(gen, "lang_to_id", None) or {}
        ids = {c: lang_to_id.get(f"<|{c}|>") for c in candidates}
        ids = {c: i for c, i in ids.items() if i is not None}
        if not ids or not windows:
            return {}
        fe = self.pipe.feature_extractor
        step = max(1, self.batch_size)
        total = None
        for i in range(0, len(windows), step):
            feats = fe(list(windows[i: i + step]), sampling_rate=sr, return_tensors="pt").input_features
            dtype = getattr(model, "dtype", None) or next(model.parameters()).dtype
            feats = feats.to(model.device, dtype=dtype)
            start = torch.full((feats.shape[0], 1), gen.decoder_start_token_id,
                               device=model.device, dtype=torch.long)
            with torch.no_grad():
                logits = model(input_features=feats, decoder_input_ids=start, use_cache=False).logits[:, -1]
            probs = torch.softmax(logits[:, list(ids.values())].float(), dim=-1).sum(0)
            total = probs if total is None else total + probs
        total = (total / len(windows)).tolist()
        return {c: float(p) for c, p in zip(ids, total)}

    def transcribe_regions(self, audio, regions, sr: int = 16000, language: str | None = None) -> list[str]:
        return self.transcribe_clips([audio[int(s * sr): int(e * sr)] for s, e in regions], sr, language)

    def transcribe_clips(self, clips, sr: int = 16000, language: str | None = None) -> list[str]:
        if not self._loaded:
            self.load()
        assert self.pipe is not None
        if not clips:
            return []
        inputs = [{"raw": c, "sampling_rate": sr} for c in clips]
        try:
            outputs = self.pipe(
                inputs,
                batch_size=self.batch_size,
                generate_kwargs={
                    "max_new_tokens": DEFAULT_MAX_NEW_TOKENS,
                    "language": language or DEFAULT_LANGUAGE,
                    "task": "transcribe",
                    "no_repeat_ngram_size": DEFAULT_NO_REPEAT_NGRAM_SIZE,
                },
                return_timestamps=False,
            )
        except Exception as exc:
            raise TranscriptionError(f"HuggingFace pipeline failed: {exc}") from exc
        return [(o.get("text") or "").strip() for o in outputs]

    def unload(self) -> None:
        with self._lock:
            if self.pipe is not None:
                model = getattr(self.pipe, "model", None)
                self.pipe = None
                if model is not None:
                    del model
            self._loaded = False
            try:
                import torch

                gc.collect()
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except ImportError:
                pass
