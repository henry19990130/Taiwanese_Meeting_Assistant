from __future__ import annotations

import logging
import re
import threading

from app import config

from taigi_asr.audio import AudioConverter
from taigi_asr.config import FASTER_WHISPER_MODEL_ID, HUGGINGFACE_MODEL_ID
from taigi_asr.engines import FakeEngine, build_engine
from taigi_asr.router import EngineKind, EngineRouter, GPUProfiler
from taigi_asr.segments import TimestampedSegment

from app.services import segmenter
from app.services.language import latin_ratio

log = logging.getLogger(__name__)

_PREFER = {
    "fw": EngineKind.FASTER_WHISPER,
    "hf": EngineKind.HUGGINGFACE,
    "auto": None,
    "fake": None,
}

FAKE_MODEL_NAME = "fake-asr"
_FAKE_SCRIPT = [
    TimestampedSegment(0.0, 4.2, "各位好，咱今仔日欲討論新系統的進度。"),
    TimestampedSegment(4.2, 9.8, "語音辨識的部分已經完成，準確率大約八成五。"),
    TimestampedSegment(9.8, 15.0, "上傳功能閣愛兩禮拜，阿明負責。"),
    TimestampedSegment(15.0, 19.6, "好，按呢就決定先完成上傳功能，下禮拜三閣開會。"),
]

_HALLUCINATIONS = {
    "阿嬤", "阿媽", "啊", "阿", "嗯", "嗯嗯", "喔", "哦", "欸", "唉",
    "謝謝收看", "謝謝觀看", "感謝收看", "請不吝點贊訂閱轉發打賞支持明鏡與點點欄目",
    "字幕由amaraorg社群提供", "thanks for watching",
}

def _normalize(text: str) -> str:
    return re.sub(r"[\s\.,!?，。！？、…~～'\"「」]+", "", text).lower()

def is_hallucination(text: str, speech_seconds: float) -> bool:
    limit = config.ASR_HALLUCINATION_MAX_S
    if limit <= 0 or speech_seconds > limit:
        return False
    norm = _normalize(text)
    return norm in {_normalize(h) for h in _HALLUCINATIONS}

_s2tw = None
_s2tw_failed = False

def to_traditional(text: str) -> str:
    global _s2tw, _s2tw_failed
    if not text or not config.ASR_TO_TRADITIONAL or _s2tw_failed:
        return text
    if _s2tw is None:
        try:
            from opencc import OpenCC

            try:
                _s2tw = OpenCC("s2tw")
            except Exception:
                _s2tw = OpenCC("s2tw.json")
        except Exception as exc:
            _s2tw_failed = True
            log.warning("OpenCC 無法載入（%s），逐字稿不做簡轉繁。pip install opencc-python-reimplemented", exc)
            return text
    return _s2tw.convert(text)

class ASRService:
    def __init__(self, engine: str | None = None) -> None:
        self.engine_name = (engine or config.ASR_ENGINE).lower()
        if self.engine_name not in _PREFER:
            raise ValueError(f"ASR_ENGINE 只能是 fw / hf / auto / fake，收到：{self.engine_name}")
        self._engine = None
        self.spec = None
        self._lock = threading.Lock()

        self.last_language: str | None = None
        self.last_language_probs: dict[str, float] = {}
        self.last_detect: dict = {}

    def load(self) -> None:
        with self._lock:
            if self._engine is not None:
                return
            if self.engine_name == "fake":
                engine = FakeEngine(_FAKE_SCRIPT)
                engine.load()
                self._engine = engine
                log.info("ASR: 使用假引擎（ASR_ENGINE=fake），不載入模型")
                return
            gpu = GPUProfiler.detect()
            self.spec = EngineRouter.select(gpu, prefer=_PREFER[self.engine_name])
            log.info(
                "ASR: GPU=%s (%.1f GB) → engine=%s compute=%s batch=%d",
                gpu.name, gpu.vram_gb, self.spec.kind.value,
                self.spec.compute_type, self.spec.batch_size,
            )
            engine = build_engine(self.spec)
            engine.load()
            self._engine = engine

    @property
    def model_name(self) -> str:
        if self.engine_name != "fake" and self.spec is None:
            self.load()
        if self.engine_name == "fake":
            return FAKE_MODEL_NAME
        if self.spec.kind is EngineKind.FASTER_WHISPER:
            return FASTER_WHISPER_MODEL_ID
        return HUGGINGFACE_MODEL_ID

    def transcribe(self, audio_path: str) -> list[dict]:
        self.load()
        if self.engine_name == "fake":
            segments = self._engine.transcribe(audio_path)
            return [
                {"segment_index": i, "start_ms": int(s.start_time * 1000),
                 "end_ms": int(s.end_time * 1000), "text": to_traditional(s.text)}
                for i, s in enumerate(segments)
            ]

        wav_path, _duration = AudioConverter.convert(audio_path)
        try:
            import soundfile as sf

            audio, sr = sf.read(str(wav_path), dtype="float32")
        finally:
            AudioConverter.cleanup(wav_path)
        if audio.ndim > 1:
            audio = audio.mean(axis=1)

        raw_regions = segmenter.speech_regions(audio, sr)
        regions = segmenter.drop_quiet(audio, sr, raw_regions, config.ASR_DROP_QUIET_DB)
        groups = segmenter.merge_groups(
            regions,
            max_gap=config.ASR_MERGE_GAP_S,
            max_len=config.ASR_MERGE_MAX_S,
            short_len=config.ASR_MERGE_SHORT_S,
        )
        log.info("ASR: VAD %d 段 → 去掉安靜 %d 段 → 合併成 %d 段",
                 len(raw_regions), len(raw_regions) - len(regions), len(groups))

        language = self._decide_language(audio, regions, sr)

        clips = [segmenter.group_audio(audio, sr, g) for g in groups]
        texts = self._engine.transcribe_clips(clips, sr, language=language)
        out = []
        dropped = 0
        for g, clip, text in zip(groups, clips, texts):
            start, end = g[0][0], g[-1][1]
            if is_hallucination(text, len(clip) / sr):
                dropped += 1
                continue
            text = to_traditional(text)
            if text:
                out.append({
                    "segment_index": len(out),
                    "start_ms": int(round(start * 1000)),
                    "end_ms": int(round(end * 1000)),
                    "text": text,
                })
        if dropped:
            log.info("ASR: 去掉 %d 段短片段的常見幻覺（例如「阿嬤」「啊」）", dropped)
        return out

    def _decide_language(self, audio, regions, sr: int) -> str:
        self.last_language_probs = {}
        self.last_detect = {"method": "fixed"}
        if config.ASR_LANGUAGE != "auto":
            self.last_language = config.ASR_LANGUAGE
            log.info("ASR: 語言固定為 %s（ASR_LANGUAGE）", self.last_language)
            return self.last_language

        import numpy as np

        limit = config.ASR_LANG_DETECT_SECONDS
        pieces = [audio[int(s * sr): int(min(e, limit) * sr)] for s, e in regions if s < limit]
        speech = np.concatenate(pieces) if pieces else np.zeros(0, dtype=np.float32)
        win = 30 * sr
        windows = [speech[i: i + win] for i in range(0, len(speech), win)]
        windows = [w for w in windows if len(w) >= sr] or windows[:1]
        lang = config.ASR_LANG_FALLBACK
        self.last_detect = {"method": "fallback"}
        if len(speech) >= sr and windows:
            try:
                probs = self._engine.language_probs(windows, config.ASR_LANG_CANDIDATES, sr)
                if probs:
                    self.last_language_probs = {k: round(v, 4) for k, v in probs.items()}
                    lang = max(probs, key=probs.get)
                    self.last_detect = {"method": "token"}
            except Exception:
                log.exception("ASR: 語言標記判斷失敗")
            cands = set(config.ASR_LANG_CANDIDATES)
            if config.ASR_LANG_DETECT_METHOD == "text" and {"zh", "en"} <= cands:
                try:
                    sample = self._engine.transcribe_clips(windows, sr, language="zh")
                    ratio, n_lat, n_cjk = latin_ratio(sample)
                    th = config.ASR_LANG_TEXT_THRESHOLD
                    self.last_detect = {"method": "text", "latin_ratio": round(ratio, 3),
                                        "latin_words": n_lat, "cjk_chars": n_cjk}
                    if n_lat + n_cjk >= 10:
                        if ratio >= th:
                            lang = "en"
                        elif ratio <= 1 - th:
                            lang = "zh"
                        else:
                            self.last_detect["method"] = "text+token"
                except Exception:
                    log.exception("ASR: 文字判斷失敗，改用語言標記的結果")
        log.info("ASR: 前 %.0f 秒語音（實際 %.0f 秒、%d 段）判斷語言 → %s；標記分數 %s；%s",
                 limit, len(speech) / sr, len(windows), lang, self.last_language_probs, self.last_detect)
        self.last_language = lang
        return lang

    def unload(self) -> None:
        with self._lock:
            if self._engine is not None:
                self._engine.unload()
                self._engine = None

_service: ASRService | None = None

def get_asr_service() -> ASRService:
    global _service
    if _service is None:
        _service = ASRService()
    return _service

if __name__ == "__main__":
    import json
    import sys
    import time

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    path = sys.argv[1] if len(sys.argv) > 1 else "storage/samples/test.m4a"
    svc = get_asr_service()
    t0 = time.time()
    svc.load()
    t1 = time.time()
    result = svc.transcribe(path)
    t2 = time.time()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n載入模型 {t1 - t0:.1f}s，辨識 {t2 - t1:.1f}s，共 {len(result)} 段")
