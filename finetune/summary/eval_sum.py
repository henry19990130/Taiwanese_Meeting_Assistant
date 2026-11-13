"""摘要評測：原版（不掛 LoRA）vs 微調版（掛 LoRA），和我寫的參考摘要比較。

指標（每場會議算完取平均）：
- json_ok：輸出是合法 JSON 且結構正確
- quote_ok：引用原文確實出現在逐字稿的比例（有沒有捏造）
- count_diff：四類項目（報告／討論／決議／待辦）數量和參考摘要的平均差距（越小越好）
- topic_f1：報告＋討論的議題，和參考摘要逐一配對的 F1（字元相似度 ≥ 0.5 算配對成功）
- action_f1：待辦事項和參考摘要配對的 F1
- text_sim：整份摘要文字（headline＋各項摘要＋待辦）和參考摘要的字元 ROUGE-L F1
- headline_sim：一句話總結的字元 ROUGE-L F1
"""
from __future__ import annotations

import argparse
import contextlib
import difflib
import json
import re
import sys
import time
from pathlib import Path

CATS = ["reports", "discussions", "decisions", "action_items"]


def parse(text: str):
    t = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    try:
        j = json.loads(t)
    except Exception:
        m = re.search(r"\{.*\}", t, flags=re.S)
        if not m:
            return None
        try:
            j = json.loads(m.group(0))
        except Exception:
            return None
    if not isinstance(j, dict) or not isinstance(j.get("meeting_content"), dict):
        return None
    return j


def _items(j, cat):
    v = (j or {}).get("meeting_content", {}).get(cat) or []
    return [x for x in v if isinstance(x, dict)]


def lcs_f1(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    a, b = a[:1500], b[:1500]
    prev = [0] * (len(b) + 1)
    for x in a:
        cur = [0]
        for j, y in enumerate(b, 1):
            cur.append(prev[j - 1] + 1 if x == y else max(prev[j], cur[j - 1]))
        prev = cur
    l = prev[-1]
    p, r = l / len(a), l / len(b)
    return 2 * p * r / (p + r) if p + r else 0.0


def match_f1(pred: list[str], ref: list[str], thr=0.5) -> float:
    if not pred and not ref:
        return 1.0
    if not pred or not ref:
        return 0.0
    used, tp = set(), 0
    for p in pred:
        best, bi = 0, None
        for i, r in enumerate(ref):
            if i in used:
                continue
            s = difflib.SequenceMatcher(None, p.lower(), r.lower()).ratio()
            if s > best:
                best, bi = s, i
        if best >= thr:
            used.add(bi)
            tp += 1
    pr, rc = tp / len(pred), tp / len(ref)
    return 2 * pr * rc / (pr + rc) if pr + rc else 0.0


def flat_text(j) -> str:
    parts = [str((j or {}).get("headline") or "")]
    for cat in CATS:
        for it in _items(j, cat):
            parts.append(str(it.get("topic") or ""))
            parts.append(str(it.get("summary") or it.get("task") or ""))
            parts += [str(k) for k in (it.get("key_points") or [])]
    return "".join(parts)


def score(pred_text: str, ref: dict, transcript: dict) -> dict:
    j = parse(pred_text)
    if j is None:
        return {"json_ok": 0, "quote_ok": 0, "count_diff": None, "topic_f1": 0, "action_f1": 0, "text_sim": 0, "headline_sim": 0}
    seg = {s["segment_id"]: s["text"] for s in transcript["segments"]}
    q_tot = q_ok = 0
    for cat in CATS:
        for it in _items(j, cat):
            for e in it.get("evidence") or []:
                if not isinstance(e, dict):
                    continue
                q_tot += 1
                q_ok += bool(e.get("quote")) and str(e.get("quote")) in seg.get(e.get("segment_id"), "")
    topics = lambda x: [str(i.get("topic") or "") for c in ("reports", "discussions") for i in _items(x, c)]
    tasks = lambda x: [str(i.get("task") or "") for i in _items(x, "action_items")]
    return {
        "json_ok": 1,
        "quote_ok": q_ok / q_tot if q_tot else 0.0,
        "count_diff": sum(abs(len(_items(j, c)) - len(_items(ref, c))) for c in CATS) / 4,
        "topic_f1": match_f1(topics(j), topics(ref)),
        "action_f1": match_f1(tasks(j), tasks(ref)),
        "text_sim": lcs_f1(flat_text(j), flat_text(ref)),
        "headline_sim": lcs_f1(str(j.get("headline") or ""), str(ref.get("headline") or "")),
    }


def summarize(rows: list[dict]) -> dict:
    out = {"n": len(rows)}
    for k in ["json_ok", "quote_ok", "count_diff", "topic_f1", "action_f1", "text_sim", "headline_sim"]:
        v = [r[k] for r in rows if r[k] is not None]
        out[k] = round(sum(v) / len(v), 4) if v else None
    return out


class Shared:
    def __init__(self, base, adapter, load_4bit=False):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import lm_utils as L
        self.L = L
        self.tok = L.load_tokenizer(base)
        self.tok.padding_side = "left"
        self.model = L.load_model(base, adapter, load_4bit=load_4bit)
        self.use_adapter = True

    def generate(self, batch, max_new_tokens=5120):
        import torch
        texts = [self.L.chat_prompt(self.tok, ex["system"], ex["user"]) for ex in batch]
        enc = self.tok(texts, return_tensors="pt", padding=True, add_special_tokens=False).to(self.model.device)
        ctx = contextlib.nullcontext() if self.use_adapter else self.model.disable_adapter()
        with torch.no_grad(), ctx:
            gen = self.model.generate(**enc, max_new_tokens=max_new_tokens, do_sample=False, pad_token_id=self.tok.pad_token_id)
        return self.tok.batch_decode(gen[:, enc["input_ids"].shape[1]:], skip_special_tokens=True)


def run(data: Path, base: str, adapter: str, out: Path, batch_size: int, load_4bit: bool):
    out.mkdir(parents=True, exist_ok=True)
    rows = [json.loads(x) for x in (data / "sft_test.jsonl").open(encoding="utf-8")]
    m = Shared(base, adapter, load_4bit)
    report = {}
    for tag, use in [("base", False), ("ft", True)]:
        m.use_adapter = use
        pred_path = out / f"sum_{tag}.predictions.jsonl"
        done = {}
        if pred_path.exists():
            done = {json.loads(l)["id"]: json.loads(l)["reply"] for l in pred_path.open(encoding="utf-8")}
        todo = [r for r in rows if r["id"] not in done]
        t0 = time.time()
        with pred_path.open("a", encoding="utf-8") as f:
            for i in range(0, len(todo), batch_size):
                b = todo[i:i + batch_size]
                for r, rep in zip(b, m.generate(b)):
                    done[r["id"]] = rep
                    f.write(json.dumps({"id": r["id"], "reply": rep}, ensure_ascii=False) + "\n")
                print(f"  {tag} {i + len(b)}/{len(todo)}  {time.time() - t0:.0f}s", flush=True)
        per = []
        for r in rows:
            s = score(done[r["id"]], json.loads(r["target"]), r["transcript"])
            s["id"], s["lang"] = r["id"], r["lang"]
            per.append(s)
        report[tag] = {"all": summarize(per), "zh": summarize([p for p in per if p["lang"] == "zh"]),
                       "en": summarize([p for p in per if p["lang"] == "en"]), "per_meeting": per}
        (out / "sum_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        print(tag, json.dumps(report[tag]["all"], ensure_ascii=False), flush=True)
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--base", required=True)
    ap.add_argument("--adapter", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--batch-size", type=int, default=4)
    ap.add_argument("--load-4bit", action="store_true")
    a = ap.parse_args()
    run(Path(a.data), a.base, a.adapter, Path(a.out), a.batch_size, a.load_4bit)
