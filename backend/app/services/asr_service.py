from __future__ import annotations

import logging
import re
import threading
import time

from app import config

from taigi_asr.audio import AudioConverter
from taigi_asr.engines.fake import FakeEngine
from taigi_asr.segments import TimestampedSegment

from app.services import asr_models, segmenter
from app.services.asr_models import HAKKA_DIALECTS, LANGUAGES

log = logging.getLogger(__name__)

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
        name = (engine or config.ASR_ENGINE).lower()
        if name in ("fw", "auto"):
            log.warning("ASR_ENGINE=%s 已不支援（四個語言模型都用 transformers），改用 hf", name)
            name = "hf"
        if name not in ("hf", "fake"):
            raise ValueError(f"ASR_ENGINE 只能是 hf / fake，收到：{name}")
        self.engine_name = name
        self._lock = threading.Lock()
        self._active = None
        self.last_language: str | None = None
        self.last_dialect: str | None = None
        self.last_model: str | None = None

    @property
    def model_name(self) -> str:
        if self.engine_name == "fake":
            return FAKE_MODEL_NAME
        return self.last_model or "-"

    @property
    def is_loaded(self) -> bool:
        return self._active is not None

    def info(self) -> dict:
        out = {"language": self.last_language,
               "language_label": LANGUAGES.get(self.last_language or "", {}).get("label"),
               "selected_by": "user"}
        if self.last_language == "hak" and self.last_dialect:
            out["dialect"] = self.last_dialect
            out["dialect_label"] = HAKKA_DIALECTS[self.last_dialect][0]
        return out

    def transcribe(self, audio_path: str, language: str | None = None, dialect: str | None = None) -> list[dict]:
        language = asr_models.normalize_language(language)
        dialect = asr_models.normalize_dialect(dialect) if language == "hak" else None
        self.last_language, self.last_dialect = language, dialect

        with self._lock:
            if self.engine_name == "fake":
                self.last_model = FAKE_MODEL_NAME
                engine = FakeEngine(_FAKE_SCRIPT)
                engine.load()
                segments = engine.transcribe(audio_path)
                return [
                    {"segment_index": i, "start_ms": int(s.start_time * 1000),
                     "end_ms": int(s.end_time * 1000), "text": to_traditional(s.text)}
                    for i, s in enumerate(segments)
                ]

            self.last_model = asr_models.model_label(language, dialect)

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
            if not groups:
                return []

            clips = [segmenter.group_audio(audio, sr, g) for g in groups]
            engine = asr_models.build_engine(language, dialect)
            self._active = engine
            t0 = time.time()
            try:
                log.info("ASR: 會議語言 %s%s → 載入 %s", LANGUAGES[language]["label"],
                         f"（{HAKKA_DIALECTS[dialect][0]}腔）" if dialect else "", self.last_model)
                engine.load()
                t1 = time.time()
                texts = engine.transcribe_clips(clips, sr)
                log.info("ASR: 載入 %.1fs、辨識 %.1fs", t1 - t0, time.time() - t1)
            finally:
                engine.unload()
                self._active = None
                log.info("ASR: 語音模型已卸載，釋放顯示卡記憶體")

        out = []
        dropped = 0
        for g, clip, text in zip(groups, clips, texts):
            start, end = g[0][0], g[-1][1]
            if is_hallucination(text, len(clip) / sr):
                dropped += 1
                continue
            if language != "en":
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

    def unload(self) -> None:
        engine = self._active
        if engine is not None:
            engine.unload()
            self._active = None


_service: ASRService | None = None


def get_asr_service() -> ASRService:
    global _service
    if _service is None:
        _service = ASRService()
    return _service


if __name__ == "__main__":
    import json
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    path = sys.argv[1] if len(sys.argv) > 1 else "storage/samples/test.m4a"
    lang = sys.argv[2] if len(sys.argv) > 2 else "zh"
    dia = sys.argv[3] if len(sys.argv) > 3 else None
    svc = get_asr_service()
    t0 = time.time()
    result = svc.transcribe(path, lang, dia)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n{svc.model_name}：共 {time.time() - t0:.1f}s（含載入與卸載），{len(result)} 段")
