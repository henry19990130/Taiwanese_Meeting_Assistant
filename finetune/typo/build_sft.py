"""步驟 2（CPU 即可）：把 hyp/ref 會議檔轉成訓練／評測樣本。

每個樣本 = 正式系統送給 Qwen 的一批（40 段 + 前面 3 段 [context]），格式與 typo_service 完全相同；
標準答案 = 人工逐字稿與 ASR 結果之間「同音／近音替換」的差異（＋train 才有的規則式同音字注入）。
所有標準答案都會先用正式的 parse_reply / parse_reply_en 跑過一次，解析不出來的不收。

輸出：{DATA}/sft_train.jsonl、sft_dev.jsonl、sft_test.jsonl、stats.json
"""
from __future__ import annotations

import argparse
import collections
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ft_common as F  # noqa: E402

INJECT_RATE = {"zh": 0.10, "en": 0.06}   # train 擴充版本中，沒有真實錯字的段落被注入同音字的比例


def load_meetings(data: Path, lang: str, split: str) -> list[dict]:
    p = data / f"meetings_{lang}_{split}.jsonl"
    if not p.exists():
        return []
    return [json.loads(x) for x in p.open(encoding="utf-8") if x.strip()]


def verified(lang: str, seg_text: dict[str, str], edits: list[dict]) -> list[dict]:
    """只保留正式解析器解析得出、而且位置一致的標準答案。"""
    ts = F.typo_service()
    ok = []
    for e in edits:
        line = F.target_text([e], lang)
        parsed = (ts.parse_reply_en if lang == "en" else ts.parse_reply)(line, {e["segment_id"]: seg_text[e["segment_id"]]})
        if parsed and parsed[0]["offset"] == e["offset"]:
            ok.append(e)
    return ok


def meeting_examples(m: dict, rng: random.Random, augment: bool, offsets: list[int], injector) -> list[dict]:
    lang = m["lang"]
    segs = [{"segment_id": s["segment_id"], "text": s["hyp"], "ref": s["ref"]} for s in m["segments"]]
    seg_text = {s["segment_id"]: s["text"] for s in segs}
    gold = {s["segment_id"]: verified(lang, seg_text, F.edits_for(lang, s["text"], s["ref"], s["segment_id"])) for s in segs}
    variants = [("real", segs, gold)]
    if augment and injector is not None:
        segs2, gold2 = [], {}
        for s in segs:
            sid = s["segment_id"]
            s2 = dict(s)
            g = list(gold[sid])
            if not g and rng.random() < INJECT_RATE[lang]:
                r = injector.inject(s["text"], sid, rng)
                if r:
                    new_text, e = r
                    if verified(lang, {sid: new_text}, [e]):
                        s2["text"], g = new_text, [e]
            segs2.append(s2)
            gold2[sid] = g
        variants.append(("aug", segs2, gold2))
    out = []
    for kind, ss, gg in variants:
        for off in offsets:
            for start in range(off, len(ss), F.CHUNK):
                end = min(len(ss), start + F.CHUNK)
                if end - start < 5:
                    continue
                batch = ss[start:end]
                edits = [e for s in batch for e in gg[s["segment_id"]]]
                out.append({
                    "id": f"{m['meeting_id']}:{kind}:{start}", "lang": lang, "split": m["split"], "kind": kind,
                    "system": F.system_prompt(lang), "user": F.user_message(ss, start, end),
                    "target": F.target_text(edits, lang),
                    "seg_text": {s["segment_id"]: s["text"] for s in batch},
                    "refs": {s["segment_id"]: s["ref"] for s in batch},
                    "gold": edits,
                })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--langs", default="zh,en")
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    data = Path(a.data)
    rng = random.Random(a.seed)
    stats = {}
    for split in ["train", "dev", "test"]:
        rows = []
        for lang in a.langs.split(","):
            meetings = load_meetings(data, lang, split)
            if not meetings:
                print(f"（沒有 {lang}/{split} 的會議檔，略過）")
                continue
            injector = None
            if split == "train":
                if lang == "zh":
                    injector = F.ZhInjector(min_freq=50)
                else:
                    vocab = collections.Counter(F.en_norm(t) for m in meetings for s in m["segments"] for t in s["ref"].split())
                    injector = F.EnInjector(vocab)
            for m in meetings:
                rows += meeting_examples(m, rng, augment=(split == "train"),
                                         offsets=[0, F.CHUNK // 2] if split == "train" else [0], injector=injector)
        rng.shuffle(rows)
        with (data / f"sft_{split}.jsonl").open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        st = {}
        for lang in a.langs.split(","):
            rr = [r for r in rows if r["lang"] == lang]
            if not rr:
                continue
            src = collections.Counter(e["source"] for r in rr for e in r["gold"])
            st[lang] = {"examples": len(rr), "clean_examples": sum(1 for r in rr if not r["gold"]),
                        "edits": sum(len(r["gold"]) for r in rr), "by_source": dict(src),
                        "kinds": dict(collections.Counter(r["kind"] for r in rr))}
        stats[split] = st
        print(split, json.dumps(st, ensure_ascii=False))
    (data / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
