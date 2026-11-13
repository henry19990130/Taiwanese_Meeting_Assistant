"""步驟 1（Colab GPU）：下載公開會議語料 → 用「專案正式的 ASR 模型與後處理」辨識 → 存成 hyp/ref 成對的會議檔。

國語：AISHELL-4（真實會議錄音、人工逐字稿，Apache-2.0）
英文：AMI Meeting Corpus 的 sdm（單一遠距麥克風，最像實際會議錄音，CC BY 4.0）

輸出：{OUT}/meetings_{lang}_{split}.jsonl，每行一場會議
  {"meeting_id", "lang", "split", "segments": [{"segment_id": "S0001", "hyp": ..., "ref": ...}]}
已經做過的會議會跳過（Colab 斷線後重跑會接著做）。
"""
from __future__ import annotations

import argparse
import io
import os
import json
import re
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ft_common as F  # noqa: E402

SR = 16000
MERGE_GAP_S = 1.0     # 與專案 ASR_MERGE_GAP_S 相同
MERGE_MAX_S = 20.0    # 與專案 ASR_MERGE_MAX_S 相同

# 會議切分：split → [(資料夾, 第幾場起, 第幾場止)]；dev 與 train 取 train_M 不重疊的部分
AISHELL_SPLITS = {"train": [("train_L", 0, 30), ("train_S", 0, 6)],
                  "dev": [("train_M", 0, 3)], "test": [("test", 0, 8)]}
AMI_SPLITS = {"train": ("train", 6), "dev": ("validation", 1), "test": ("test", 2)}   # (HF split, 取幾個 parquet 分片)


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def done_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {json.loads(line)["meeting_id"] for line in path.open(encoding="utf-8") if line.strip()}


def merge_intervals(items: list[dict]) -> list[list[dict]]:
    """items: [{start, end, ref, ...}] 已依時間排序、且不重疊。依專案規則合併成段落。"""
    groups, cur = [], []
    for it in items:
        if cur and (it["start"] - cur[-1]["end"] <= MERGE_GAP_S) and (it["end"] - cur[0]["start"] <= MERGE_MAX_S):
            cur.append(it)
        else:
            if cur:
                groups.append(cur)
            cur = [it]
    if cur:
        groups.append(cur)
    return groups


def drop_overlaps(items: list[dict]) -> list[dict]:
    """多人同時講話的片段，參考答案的先後順序不明確 → 去掉。"""
    items = sorted(items, key=lambda x: x["start"])
    keep = []
    for i, it in enumerate(items):
        prev_end = max((x["end"] for x in items[max(0, i - 8):i]), default=-1)
        nxt = items[i + 1]["start"] if i + 1 < len(items) else 1e9
        if it["start"] >= prev_end and it["end"] <= nxt:
            keep.append(it)
    return keep


class ProjectASR:
    """直接用專案的 build_engine / is_hallucination / to_traditional，辨識結果和正式系統一致。"""

    def __init__(self, lang: str, batch_size: int):
        b = str(F.project_backend())
        if b not in sys.path:
            sys.path.insert(0, b)
        from app.services import asr_models
        from app.services.asr_service import is_hallucination, to_traditional
        self.lang = lang
        self.engine = asr_models.build_engine(lang)
        inner = getattr(self.engine, "_engine", None)
        if inner is not None:
            inner.batch_size = batch_size
        self.is_hallucination, self.to_traditional = is_hallucination, to_traditional
        log("載入 ASR：", asr_models.LANGUAGES[lang]["model_id"])
        self.engine.load()

    def run(self, clips: list[np.ndarray], step: int = 64) -> list[str | None]:
        texts = []
        for i in range(0, len(clips), step):     # 分批送，避免一場會議幾百段一次塞爆顯示卡
            texts += self.engine.transcribe_clips(clips[i:i + step], SR)
        out = []
        for clip, t in zip(clips, texts):
            if self.is_hallucination(t, len(clip) / SR):
                out.append(None)
                continue
            if self.lang != "en":
                t = self.to_traditional(t)
            out.append(t.strip() or None)
        return out

    def unload(self):
        self.engine.unload()


def build_meeting(meeting_id: str, lang: str, split: str, groups: list[list[dict]], clips, asr: ProjectASR) -> dict:
    hyps = asr.run(clips)
    segs = []
    for g, hyp in zip(groups, hyps):
        ref = " ".join(x["ref"] for x in g) if lang == "en" else "".join(x["ref"] for x in g)
        if not hyp or not ref.strip():
            continue
        segs.append({"segment_id": f"S{len(segs) + 1:04d}", "hyp": hyp, "ref": ref,
                     "start": round(g[0]["start"], 2), "end": round(g[-1]["end"], 2)})
    return {"meeting_id": meeting_id, "lang": lang, "split": split, "segments": segs}


# ------------------------------------------------------------------ AISHELL-4

def parse_textgrid(text: str) -> list[dict]:
    items = []
    for tier in re.split(r"item \[\d+\]:", text)[1:]:
        for m in re.finditer(r"xmin = ([\d.]+)\s*\n\s*xmax = ([\d.]+)\s*\n\s*text = \"(.*?)\"", tier, flags=re.S):
            ref = F.clean_zh_ref(m.group(3))
            if len(F.zh_chars(ref)) >= 2:
                items.append({"start": float(m.group(1)), "end": float(m.group(2)), "ref": ref})
    return items


def run_aishell(out: Path, splits: list[str], batch_size: int, limit_scale: float):
    import soundfile as sf
    from huggingface_hub import HfApi, hf_hub_download
    repo = "AISHELL/AISHELL-4"
    files = [f for f in HfApi().list_repo_files(repo, repo_type="dataset")]
    asr = None
    for split in splits:
        path = out / f"meetings_zh_{split}.jsonl"
        have = done_ids(path)
        for folder, lo, hi in AISHELL_SPLITS[split]:
            hi = lo + max(1, int((hi - lo) * limit_scale))
            tgs = sorted(f for f in files if f.startswith(f"{folder}/TextGrid/") and f.endswith(".TextGrid"))[lo:hi]
            for tg in tgs:
                mid = Path(tg).stem
                if mid in have:
                    continue
                flac = next((f for f in files if f.startswith(f"{folder}/") and Path(f).stem == mid and f.endswith(".flac")), None)
                if flac is None:
                    log("找不到音檔，略過", mid)
                    continue
                dl = Path(os.environ.get("FT_DOWNLOAD", "/tmp/ft_download"))
                items = drop_overlaps(parse_textgrid(Path(hf_hub_download(repo, tg, repo_type="dataset", local_dir=dl)).read_text(encoding="utf-8")))
                flac_path = Path(hf_hub_download(repo, flac, repo_type="dataset", local_dir=dl))
                audio, sr = sf.read(str(flac_path), dtype="float32")
                if audio.ndim > 1:
                    # AISHELL-4 是 8 支麥克風的陣列；直接平均會讓聲音相位互相抵消、辨識變很差。
                    # 取其中一支麥克風 = 一台放在會議桌上的手機或筆電錄音，比較接近實際使用情境。
                    audio = audio[:, 0]
                if sr != SR:
                    import librosa
                    audio = librosa.resample(audio, orig_sr=sr, target_sr=SR)
                groups = merge_intervals(items)
                clips = [audio[int(g[0]["start"] * SR): int(g[-1]["end"] * SR)] for g in groups]
                if asr is None:
                    asr = ProjectASR("zh", batch_size)
                t0 = time.time()
                rec = build_meeting(mid, "zh", split, groups, clips, asr)
                with path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                log(f"[zh/{split}] {mid}：{len(rec['segments'])} 段，{len(audio) / SR / 60:.0f} 分鐘音檔，辨識 {time.time() - t0:.0f}s")
                flac_path.unlink(missing_ok=True)   # 省磁碟
    if asr:
        asr.unload()


# ------------------------------------------------------------------ AMI

def run_ami(out: Path, splits: list[str], batch_size: int, limit_scale: float):
    import pyarrow.parquet as pq
    import soundfile as sf
    from huggingface_hub import HfApi, hf_hub_download
    repo = "edinburghcstr/ami"
    files = HfApi().list_repo_files(repo, repo_type="dataset")
    asr = None
    for split in splits:
        hf_split, n = AMI_SPLITS[split]
        n = max(1, int(n * limit_scale))
        path = out / f"meetings_en_{split}.jsonl"
        have = done_ids(path)
        shards = sorted(f for f in files if f.startswith(f"sdm/{hf_split}-"))[:n]
        by_meeting: dict[str, list[dict]] = {}
        for sh in shards:
            t = pq.read_table(hf_hub_download(repo, sh, repo_type="dataset"))
            for row in t.to_pylist():
                if row["meeting_id"] in have:
                    continue
                by_meeting.setdefault(row["meeting_id"], []).append(
                    {"start": row["begin_time"], "end": row["end_time"], "ref": row["text"], "audio": row["audio"]["bytes"]})
        for mid, items in sorted(by_meeting.items()):
            items = drop_overlaps(items)
            groups = merge_intervals(items)
            clips = []
            for g in groups:
                parts = []
                for k, x in enumerate(g):
                    if k:
                        parts.append(np.zeros(int(min(0.3, max(0.0, x["start"] - g[k - 1]["end"])) * SR), dtype=np.float32))
                    a, sr = sf.read(io.BytesIO(x["audio"]), dtype="float32")
                    if a.ndim > 1:
                        a = a.mean(axis=1)
                    if sr != SR:
                        import librosa
                        a = librosa.resample(a, orig_sr=sr, target_sr=SR)
                    parts.append(a)
                clips.append(np.concatenate(parts))
            if asr is None:
                asr = ProjectASR("en", batch_size)
            t0 = time.time()
            rec = build_meeting(mid, "en", split, groups, clips, asr)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            log(f"[en/{split}] {mid}：{len(rec['segments'])} 段，辨識 {time.time() - t0:.0f}s")
    if asr:
        asr.unload()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--langs", default="zh,en")
    ap.add_argument("--splits", default="train,dev,test")
    ap.add_argument("--batch-size", type=int, default=48)
    ap.add_argument("--scale", type=float, default=1.0, help="會議數量倍率（測試用 0.1）")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    splits = a.splits.split(",")
    if "zh" in a.langs:
        run_aishell(out, splits, a.batch_size, a.scale)
    if "en" in a.langs:
        run_ami(out, splits, a.batch_size, a.scale)
    log("完成")
