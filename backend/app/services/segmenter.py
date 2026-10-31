from __future__ import annotations

import logging

import numpy as np

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000

MIN_SILENCE_MS = 500
SPEECH_PAD_MS = 200
MIN_SPEECH_MS = 300
MAX_SEGMENT_S = 20.0


def speech_regions(audio: np.ndarray, sr: int = SAMPLE_RATE) -> list[tuple[float, float]]:
    if audio.size == 0:
        return []
    try:
        regions = _silero_regions(audio, sr)
        method = "silero"
    except Exception as exc:
        log.warning("Silero VAD 無法使用（%s），改用音量門檻分段", exc)
        regions = _energy_regions(audio, sr)
        method = "energy"
    regions = _split_long(audio, sr, regions)
    log.info("VAD(%s) 切出 %d 段", method, len(regions))
    return regions


def _silero_regions(audio: np.ndarray, sr: int) -> list[tuple[float, float]]:
    from faster_whisper.vad import get_speech_timestamps

    chunks = get_speech_timestamps(
        audio,
        sampling_rate=sr,
        min_silence_duration_ms=MIN_SILENCE_MS,
        speech_pad_ms=SPEECH_PAD_MS,
        min_speech_duration_ms=MIN_SPEECH_MS,
        max_speech_duration_s=MAX_SEGMENT_S,
    )
    return [(c["start"] / sr, c["end"] / sr) for c in chunks]


FRAME_MS = 30


def _frame_db(audio: np.ndarray, sr: int) -> np.ndarray:
    hop = int(sr * FRAME_MS / 1000)
    n = len(audio) // hop
    if n == 0:
        return np.array([])
    frames = audio[: n * hop].reshape(n, hop).astype(np.float64)
    rms = np.sqrt(np.mean(frames**2, axis=1)) + 1e-10
    return 20 * np.log10(rms)


def _energy_regions(audio: np.ndarray, sr: int) -> list[tuple[float, float]]:
    db = _frame_db(audio, sr)
    if db.size == 0:
        return []
    noise_floor = np.percentile(db, 20)
    threshold = max(noise_floor + 10.0, -50.0)
    voiced = db > threshold

    frame_s = FRAME_MS / 1000
    min_gap = int(MIN_SILENCE_MS / FRAME_MS)
    regions: list[list[int]] = []
    start = None
    silence = 0
    for i, v in enumerate(voiced):
        if v:
            if start is None:
                start = i
            silence = 0
        elif start is not None:
            silence += 1
            if silence >= min_gap:
                regions.append([start, i - silence + 1])
                start, silence = None, 0
    if start is not None:
        regions.append([start, len(voiced) - silence])

    pad = SPEECH_PAD_MS / 1000
    total = len(audio) / sr
    out = []
    for s, e in regions:
        if (e - s) * FRAME_MS < MIN_SPEECH_MS:
            continue
        out.append((max(0.0, s * frame_s - pad), min(total, e * frame_s + pad)))
    return _merge_overlaps(out)


def _merge_overlaps(regions: list[tuple[float, float]]) -> list[tuple[float, float]]:
    merged: list[tuple[float, float]] = []
    for s, e in sorted(regions):
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def _split_long(audio: np.ndarray, sr: int, regions) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for s, e in regions:
        out.extend(_split_one(audio, sr, s, e))
    return out


def _split_one(audio, sr, s: float, e: float) -> list[tuple[float, float]]:
    if e - s <= MAX_SEGMENT_S:
        return [(s, e)]
    seg = audio[int(s * sr): int(e * sr)]
    db = _frame_db(seg, sr)
    frame_s = FRAME_MS / 1000
    lo, hi = int(len(db) * 0.3), int(len(db) * 0.7)
    cut = s + (lo + int(np.argmin(db[lo:hi]))) * frame_s if hi > lo else (s + e) / 2
    return _split_one(audio, sr, s, cut) + _split_one(audio, sr, cut, e)


def drop_quiet(audio: np.ndarray, sr: int, regions, below_db: float = 35.0) -> list[tuple[float, float]]:
    if below_db <= 0 or not regions:
        return list(regions)
    peaks, frames = [], []
    for s, e in regions:
        db = _frame_db(audio[int(s * sr): int(e * sr)], sr)
        peaks.append(float(db.max()) if db.size else -200.0)
        frames.append(db)
    all_db = np.concatenate([f for f in frames if f.size]) if any(f.size for f in frames) else np.array([])
    if all_db.size == 0:
        return []
    loud = float(np.percentile(all_db, 95))
    kept = [r for r, p in zip(regions, peaks) if p >= loud - below_db]
    if len(kept) < len(regions):
        log.info("去掉 %d 段太安靜的片段（低於說話音量 %.0f dB 以上）", len(regions) - len(kept), below_db)
    return kept


def merge_groups(
    regions: list[tuple[float, float]],
    max_gap: float = 1.0,
    max_len: float = 20.0,
    short_len: float = 3.0,
    short_gap: float = 2.0,
) -> list[list[tuple[float, float]]]:
    groups: list[list[tuple[float, float]]] = []
    for s, e in sorted(regions):
        if groups:
            g = groups[-1]
            ps, pe = g[-1]
            gap = s - pe
            short = (pe - ps) < short_len or (e - s) < short_len
            speech_len = sum(b - a for a, b in g) + (e - s)
            if (gap <= max_gap or (short and gap <= short_gap)) and speech_len <= max_len:
                g.append((s, e))
                continue
        groups.append([(s, e)])
    return groups


def group_audio(audio: np.ndarray, sr: int, group: list[tuple[float, float]]) -> np.ndarray:
    return np.concatenate([audio[int(s * sr): int(e * sr)] for s, e in group])
