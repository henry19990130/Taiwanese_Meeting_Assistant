"""步驟 5：原版 vs 微調版，產生比較報告與「要不要換上去」的判定。

判定規則（每個語言各自判斷）：
  1. F0.5 比原版高（F0.5 偏重準確率：寧可少抓，不要亂抓，和 prompt 的要求一致）
  2. 準確率（precision）沒有比原版低超過 2 個百分點
  3. 套用模型建議後的 CER/WER 不比原版差
三項都過才建議換上微調版。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

LABEL = {"zh": "國語", "en": "英文"}


def pct(x):
    return "—" if x is None else f"{x * 100:.1f}%"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True)
    ap.add_argument("--base", default="auto")
    ap.add_argument("--ft", default="auto")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    R = Path(a.results)
    if a.base == "auto":   # 有 transformers A/B 的結果就用它（同權重、只差 LoRA，最公平）
        a.base, a.ft = (("base_hf", "ft_hf") if (R / "base_hf.json").exists() and (R / "ft_hf.json").exists()
                        else ("base_ollama", "ft_ollama"))
    base = json.loads((R / f"{a.base}.json").read_text(encoding="utf-8"))
    ft = json.loads((R / f"{a.ft}.json").read_text(encoding="utf-8"))
    lines = ["# 錯字校正微調結果", "",
             f"- 原版：`{base['_meta']['model']}`　微調版：`{ft['_meta']['model']}`",
             "- 測試資料：沒有參與訓練的會議（國語 AISHELL-4 test、英文 AMI test），只用真實 ASR 錯誤，不含人工注入的錯字",
             "- 一筆建議算「對」= 套用後和人工逐字稿一致；評分用的是專案正式的解析程式"]
    if a.base == "base_hf":
        lines += ["- 比較方式：同一份 Qwen3.8-27B（bf16）權重，掛 LoRA vs 不掛 LoRA，其餘完全相同"]
        if (R / "base_ollama.json").exists():
            o = json.loads((R / "base_ollama.json").read_text(encoding="utf-8"))
            lines += ["- 參考：正式系統的 Ollama 版 qwen3.8:27b（4-bit 量化）在同一份測試上的結果："
                      + "；".join(f"{LABEL[k]} 準確率 {pct(o[k]['precision'])}、寬鬆改對 {pct(o[k].get('helpful_rate'))}、"
                                 f"改錯 {pct(o[k].get('harmful_rate'))}" for k in ("zh", "en") if k in o)]
    lines += [""]
    verdict = {}
    for lang in ["zh", "en"]:
        if lang not in base or lang not in ft:
            continue
        b, f = base[lang], ft[lang]
        m = b.get("error_rate_metric", "CER")
        lines += [f"## {LABEL[lang]}（{b['chunks']} 批、標準答案 {b['gold']} 處）", "",
                  "| 指標 | 原版 | 微調版 |", "|---|---|---|",
                  f"| 準確率（建議中有幾成是對的） | {pct(b['precision'])} | {pct(f['precision'])} |",
                  f"| 召回率（錯字被抓到幾成） | {pct(b['recall'])} | {pct(f['recall'])} |",
                  f"| F0.5（綜合，偏重準確率） | {b['f0.5']:.3f} | {f['f0.5']:.3f} |",
                  f"| 建議總數 / 正確數 | {b['pred']} / {b['tp']} | {f['pred']} / {f['tp']} |",
                  f"| 寬鬆：建議讓文字更接近人工逐字稿的比例 | {pct(b.get('helpful_rate'))} | {pct(f.get('helpful_rate'))} |",
                  f"| 寬鬆：建議反而改錯的比例 | {pct(b.get('harmful_rate'))} | {pct(f.get('harmful_rate'))} |",
                  f"| 沒有錯字的批次被亂報的比例 | {pct(b['false_alarm_rate_on_clean_chunks'])} | {pct(f['false_alarm_rate_on_clean_chunks'])} |",
                  f"| {m}：原始 ASR | {pct(b['error_rate']['before'])} | {pct(f['error_rate']['before'])} |",
                  f"| {m}：全部套用模型建議後 | {pct(b['error_rate']['after_model'])} | {pct(f['error_rate']['after_model'])} |",
                  f"| {m}：全部套用標準答案（上限） | {pct(b['error_rate']['after_gold'])} | {pct(f['error_rate']['after_gold'])} |", ""]
        ok3 = f["error_rate"]["after_model"] <= b["error_rate"]["after_model"]
        if b["gold"] >= 50:
            ok1 = f["f0.5"] > b["f0.5"]
            ok2 = f["precision"] >= b["precision"] - 0.02
            names = ("F0.5 提升", "準確率沒下降")
        else:   # 標準答案太少，F0.5 沒有統計意義 → 改看寬鬆指標與誤報
            net = lambda r: r.get("helpful", 0) - r.get("harmful", 0)
            ok1 = net(f) >= net(b) and f.get("harmful_rate", 0) <= b.get("harmful_rate", 0)
            ok2 = f["false_alarm_rate_on_clean_chunks"] <= b["false_alarm_rate_on_clean_chunks"]
            names = ("改對減改錯沒變少、改錯比例沒變高", "乾淨批次誤報沒變多")
            if ok1 and ok2 and not (net(f) > net(b) or f["false_alarm_rate_on_clean_chunks"] < b["false_alarm_rate_on_clean_chunks"]):
                ok1 = False   # 完全沒進步就不換
            lines += [f"（標準答案只有 {b['gold']} 處，F0.5 不具統計意義，改用寬鬆指標與誤報率判定）"]
        verdict[lang] = ok1 and ok2 and ok3
        lines += [f"判定：{'✅ 建議換上微調版' if verdict[lang] else '❌ 維持原版'}"
                  f"（{names[0]} {'是' if ok1 else '否'}、{names[1]} {'是' if ok2 else '否'}、{m} 沒變差 {'是' if ok3 else '否'}）", ""]
    (Path(a.out)).write_text("\n".join(lines), encoding="utf-8")
    (R / "verdict.json").write_text(json.dumps(verdict, ensure_ascii=False), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
