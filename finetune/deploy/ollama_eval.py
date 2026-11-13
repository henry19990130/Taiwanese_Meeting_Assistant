"""用和覓聲正式系統相同的方式呼叫 Ollama（/api/chat、format=json、temperature 0、seed 42），
在 8 場測試會議上比較：
- 原版 qwen3.8:27b（思考模式開啟，= 目前 .env 的 LLM_THINK=True）
- 微調版（思考模式關閉，= 訓練時的設定）
分數用和 Colab 評測相同的 eval_sum.score。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import eval_sum as E  # noqa: E402


def call(host: str, model: str, ex: dict, think: bool, num_ctx: int) -> tuple[str, dict]:
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": ex["system"]}, {"role": "user", "content": ex["user"]}],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0, "seed": 42, "num_ctx": num_ctx},
        "think": think,
    }
    t0 = time.time()
    r = requests.post(f"{host}/api/chat", json=payload, timeout=3600)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:500]}")
    body = r.json()
    msg = body.get("message") or {}
    stat = {"secs": round(time.time() - t0, 1), "prompt_tokens": body.get("prompt_eval_count"),
            "out_tokens": body.get("eval_count"), "thinking_chars": len(msg.get("thinking") or ""),
            "done_reason": body.get("done_reason")}
    return msg.get("content") or "", stat


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="sft_test.jsonl")
    ap.add_argument("--host", default="http://127.0.0.1:11434")
    ap.add_argument("--model", required=True)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--think", choices=["true", "false"], required=True)
    ap.add_argument("--num-ctx", type=int, default=40960)
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = [json.loads(x) for x in open(a.data, encoding="utf-8") if x.strip()]
    if a.limit:
        rows = rows[: a.limit]
    pred = out / f"{a.tag}.predictions.jsonl"
    done = {}
    if pred.exists():
        done = {json.loads(l)["id"]: json.loads(l) for l in pred.open(encoding="utf-8")}
    with pred.open("a", encoding="utf-8") as f:
        for r in rows:
            if r["id"] in done:
                continue
            reply, stat = call(a.host, a.model, r, a.think == "true", a.num_ctx)
            rec = {"id": r["id"], "reply": reply, **stat}
            done[r["id"]] = rec
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            print(f"  {a.tag} {r['id']}  {stat}", flush=True)
    per = []
    for r in rows:
        s = E.score(done[r["id"]]["reply"], json.loads(r["target"]), r["transcript"])
        s.update(id=r["id"], lang=r["lang"], secs=done[r["id"]]["secs"], out_tokens=done[r["id"]]["out_tokens"])
        per.append(s)
    rep = {"all": E.summarize(per), "zh": E.summarize([p for p in per if p["lang"] == "zh"]),
           "en": E.summarize([p for p in per if p["lang"] == "en"]), "per_meeting": per,
           "avg_secs": round(sum(p["secs"] for p in per) / len(per), 1)}
    (out / f"{a.tag}.report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(a.tag, json.dumps(rep["all"], ensure_ascii=False), "平均秒數", rep["avg_secs"], flush=True)


if __name__ == "__main__":
    main()
