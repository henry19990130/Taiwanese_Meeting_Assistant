"""評分：把測試樣本送給模型，用正式解析器解析，跟標準答案比較。

後端：
  --backend ollama  走和正式系統一模一樣的 /api/chat 呼叫（最終成績以這個為準）
  --backend hf      transformers 直接推論，可掛 LoRA adapter（訓練中快速比較用）
  --backend gold    直接拿標準答案當模型輸出（檢查評分程式本身，應該 100%）

輸出：{OUT}/{name}.json（各項分數）與 {name}.predictions.jsonl（每批原始回覆，方便人工檢查）
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ft_common as F  # noqa: E402


def apply_all(text: str, items: list[dict]) -> str:
    for it in sorted(items, key=lambda x: -x["offset"]):
        if text[it["offset"]:it["offset"] + len(it["wrong"])] == it["wrong"]:
            text = text[:it["offset"]] + it["suggestion"] + text[it["offset"] + len(it["wrong"]):]
    return text


class OllamaBackend:
    def __init__(self, model: str, host: str):
        F.typo_service()          # 把專案 backend 加進 sys.path
        from app import config  # noqa: F401  ← 讀 .env，溫度／seed／num_ctx 和正式設定相同
        self.model, self.host = model, host

    def generate(self, batch: list[dict]) -> list[str]:
        import httpx
        from app import config
        out = []
        for ex in batch:
            payload = {
                "model": self.model,
                "messages": [{"role": "system", "content": ex["system"]}, {"role": "user", "content": ex["user"]}],
                "stream": False, "think": config.TYPO_THINK,
                "options": {"temperature": config.LLM_TEMPERATURE, "seed": config.LLM_SEED, "num_ctx": config.LLM_NUM_CTX},
            }
            r = httpx.post(f"{self.host}/api/chat", json=payload, timeout=config.LLM_TIMEOUT_SECONDS)
            r.raise_for_status()
            content = (r.json().get("message") or {}).get("content") or ""
            out.append(re.sub(r"<think>.*?</think>", "", content, flags=re.S))
        return out


class HFBackend:
    def __init__(self, base: str, adapter: str | None, max_new_tokens: int = 512):
        import lm_utils as L
        self.L = L
        self.tok = L.load_tokenizer(base)
        self.tok.padding_side = "left"
        self.model = L.load_model(base, adapter)
        self.max_new_tokens = max_new_tokens

    def generate(self, batch: list[dict]) -> list[str]:
        import torch
        texts = [self.L.chat_prompt(self.tok, ex["system"], ex["user"]) for ex in batch]
        enc = self.tok(texts, return_tensors="pt", padding=True, add_special_tokens=False).to(self.model.device)
        with torch.no_grad():
            gen = self.model.generate(**enc, max_new_tokens=self.max_new_tokens, do_sample=False,
                                      pad_token_id=self.tok.pad_token_id)
        outs = self.tok.batch_decode(gen[:, enc["input_ids"].shape[1]:], skip_special_tokens=True)
        return [re.sub(r"<think>.*?</think>", "", o, flags=re.S).strip() for o in outs]


class GoldBackend:
    def generate(self, batch):
        return [ex["target"] for ex in batch]


def evaluate(examples: list[dict], backend, batch_size: int, pred_path: Path) -> dict:
    ts = F.typo_service()
    done = {}
    if pred_path.exists():   # 斷線後接著跑
        for line in pred_path.open(encoding="utf-8"):
            r = json.loads(line)
            done[r["id"]] = r["reply"]
    todo = [ex for ex in examples if ex["id"] not in done]
    t0 = time.time()
    with pred_path.open("a", encoding="utf-8") as f:
        for i in range(0, len(todo), batch_size):
            batch = todo[i:i + batch_size]
            for ex, rep in zip(batch, backend.generate(batch)):
                done[ex["id"]] = rep
                f.write(json.dumps({"id": ex["id"], "reply": rep}, ensure_ascii=False) + "\n")
            n = i + len(batch)
            print(f"  {n}/{len(todo)}  {(time.time() - t0) / n:.1f}s/批", flush=True)

    rows, groups = [], {}
    err = {}
    for ex in examples:
        lang = ex["lang"]
        reply = done[ex["id"]]
        parser = ts.parse_reply_en if lang == "en" else ts.parse_reply
        pred = ts.merge(parser(reply, ex["seg_text"]), {sid: k for k, sid in enumerate(ex["seg_text"])})
        sc = F.score_chunk(lang, ex["seg_text"], ex["gold"], pred)
        # 寬鬆指標：不管有沒有在標準答案裡，這筆建議有沒有讓段落更接近人工逐字稿
        sc["helpful"] = sc["harmful"] = 0
        for p in pred:
            t, ref = ex["seg_text"][p["segment_id"]], ex["refs"][p["segment_id"]]
            d0, _ = F.error_rate(lang, t, ref)
            d1, _ = F.error_rate(lang, apply_all(t, [p]), ref)
            sc["helpful"] += d1 < d0
            sc["harmful"] += d1 > d0
        rows.append(sc)
        for key in [lang, f"{lang}/{ex['kind']}"]:
            groups.setdefault(key, []).append(sc)
        # 整份逐字稿的錯誤率：原始 ASR、套用模型建議、套用全部標準答案（上限）
        e = err.setdefault(lang, {"before": [0, 0], "after_model": [0, 0], "after_gold": [0, 0]})
        by_seg_pred, by_seg_gold = {}, {}
        for p in pred:
            by_seg_pred.setdefault(p["segment_id"], []).append(p)
        for g in ex["gold"]:
            by_seg_gold.setdefault(g["segment_id"], []).append(g)
        for sid, text in ex["seg_text"].items():
            ref = ex["refs"][sid]
            for k, t in [("before", text), ("after_model", apply_all(text, by_seg_pred.get(sid, []))),
                         ("after_gold", apply_all(text, by_seg_gold.get(sid, [])))]:
                d, n = F.error_rate(lang, t, ref)
                e[k][0] += d
                e[k][1] += n
    res = {k: F.summarize(v) for k, v in sorted(groups.items())}
    res["all"] = F.summarize(rows)
    for lang, e in err.items():
        res[lang]["error_rate"] = {k: round(d / n, 4) if n else None for k, (d, n) in e.items()}
        res[lang]["error_rate_metric"] = "WER" if lang == "en" else "CER"
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="sft_*.jsonl 所在資料夾")
    ap.add_argument("--split", default="test")
    ap.add_argument("--kinds", default="real", help="real / aug / real,aug")
    ap.add_argument("--backend", choices=["ollama", "hf", "gold"], required=True)
    ap.add_argument("--model", default="qwen3.8:27b", help="ollama 模型名稱")
    ap.add_argument("--host", default="http://127.0.0.1:11434")
    ap.add_argument("--base", help="hf：基底模型路徑")
    ap.add_argument("--adapter", help="hf：LoRA adapter 路徑")
    ap.add_argument("--batch-size", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--name", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    examples = [json.loads(x) for x in Path(a.data, f"sft_{a.split}.jsonl").open(encoding="utf-8")]
    kinds = set(a.kinds.split(","))
    examples = sorted([e for e in examples if e["kind"] in kinds], key=lambda e: e["id"])
    if a.limit:
        examples = examples[:a.limit]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    if a.backend == "ollama":
        F.typo_service()
        backend, bs = OllamaBackend(a.model, a.host), 1
    elif a.backend == "hf":
        backend, bs = HFBackend(a.base, a.adapter), a.batch_size
    else:
        backend, bs = GoldBackend(), 64
    print(f"評測 {a.name}：{len(examples)} 批")
    res = evaluate(examples, backend, bs, out / f"{a.name}.predictions.jsonl")
    res["_meta"] = {"name": a.name, "backend": a.backend, "model": a.model if a.backend == "ollama" else a.base,
                    "adapter": a.adapter, "split": a.split, "kinds": sorted(kinds)}
    (out / f"{a.name}.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k != "_meta"}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
