from __future__ import annotations

import json
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("用法：python check_typos.py transcript-xxx.json 錯字答案.json")
        return 1
    data = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    answer = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    typos = ((data.get("proofread") or {}).get("suggestions")
             if data.get("proofread") else data.get("typo_suggestions"))
    if typos is None:
        sys.exit("這個檔案沒有 AI 校對結果（請在網頁逐字稿旁按「下載 JSON」）")

    truth = {(a["segment_id"], a["position"]): a for a in answer["錯字"]}
    found = {}
    for t in typos:
        for k, (w, s) in enumerate(zip(t["wrong"], t["suggestion"])):
            if w != s:
                found[(t["segment_id"], t["offset"] + k)] = (w, s, t)

    hits = [k for k in found if k in truth]
    fixed = [k for k in hits if found[k][1] == truth[k]["correct"]]
    missed = [k for k in truth if k not in found]
    false_pos = [k for k in found if k not in truth]

    n = len(truth)
    print(f"答案錯字　　{n} 個")
    print(f"AI 標出　　 {len(found)} 個字（{len(typos)} 處建議）")
    print(f"找到　　　　{len(hits)} 個　→ 找到率 {len(hits) / n:.0%}" if n else "答案沒有錯字")
    if hits:
        print(f"改對　　　　{len(fixed)} 個　→ 改對率 {len(fixed) / len(hits):.0%}（找到的錯字中，建議的字跟答案一樣）")
    print(f"漏掉　　　　{len(missed)} 個")
    print(f"誤判　　　　{len(false_pos)} 個　→ 準確率 {len(hits) / len(found):.0%}（AI 標出的字中，真的是錯字的比例）"
          if found else "誤判　　　　0 個")

    def show(title, keys, fmt, limit=15):
        if not keys:
            return
        print(f"\n{title}（前 {min(limit, len(keys))} 個）")
        for k in sorted(keys)[:limit]:
            print("  " + fmt(k))

    show("漏掉的錯字", missed,
         lambda k: f"{k[0]}　「{truth[k]['typo_context']}」裡的「{truth[k]['typo']}」應為「{truth[k]['correct']}」")
    show("誤判（原文其實沒錯）", false_pos,
         lambda k: f"{k[0]}　「{found[k][2]['wrong']}」→「{found[k][2]['suggestion']}」")
    show("找到但改錯", [k for k in hits if k not in fixed],
         lambda k: f"{k[0]}　「{found[k][0]}」AI 建議「{found[k][1]}」，答案是「{truth[k]['correct']}」")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
