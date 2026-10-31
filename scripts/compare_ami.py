from __future__ import annotations

import html
import json
import re
import sys
import xml.etree.ElementTree as ET

TOL = 6.0
NORM = {"ok": "okay", "alright": "all right", "kay": "okay", "gonna": "going to", "wanna": "want to",
        "kinda": "kind of", "sorta": "sort of", "tv": "t v", "yep": "yeah", "mm-hmm": "mmhmm", "uh-huh": "uhhuh"}
FILLERS = {"um", "uh", "hmm", "mm", "mmhmm", "uhhuh", "ah", "oh", "er", "erm"}


def words_of(text: str) -> list[str]:
    text = html.unescape(text).lower().replace("-", " ")
    text = re.sub(r"[^a-z0-9' ]+", " ", text)
    out = []
    for w in text.split():
        w = w.strip("'")
        if w:
            out.extend(NORM.get(w, w).split())
    return out


def load_ref(paths):
    ref = []
    for p in paths:
        spk = re.search(r"\.([A-Z])\.words\.xml$", p)
        spk = spk.group(1) if spk else "?"
        for el in ET.parse(p).getroot():
            if el.tag != "w" or el.get("punc") == "true":
                continue
            t = (float(el.get("starttime")) + float(el.get("endtime"))) / 2
            ref += [(t, w, spk) for w in words_of(el.text or "")]
    return sorted(ref, key=lambda r: r[0])


def load_hyp(path, vocab):
    def split(w):
        if w in vocab or len(w) < 6:
            return [w]
        for k in range(2, len(w) - 1):
            if w[:k] in vocab and w[k:] in vocab:
                return [w[:k], w[k:]]
        return [w]

    d = json.load(open(path, encoding="utf-8"))
    hyp = []
    for s in d["segments"]:
        ws = [x for w in words_of(s["text"]) for x in split(w)]
        a, b = s["start_ms"] / 1000, s["end_ms"] / 1000
        hyp += [(a + (b - a) * (i + 0.5) / max(1, len(ws)), w) for i, w in enumerate(ws)]
    return d, hyp


def align(R, H, count_ins: bool):
    n, m = len(R), len(H)
    INF = 10**9
    ins = 1 if count_ins else 0
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for j in range(1, m + 1):
        dp[0][j] = j * ins
    for i in range(1, n + 1):
        dp[i][0] = i
        rt, rw = R[i - 1][0], R[i - 1][1]
        for j in range(1, m + 1):
            ht, hw = H[j - 1]
            near = abs(rt - ht) <= TOL
            sub = dp[i - 1][j - 1] + (0 if (rw == hw and near) else (1 if near else INF))
            dp[i][j] = min(sub, dp[i - 1][j] + 1, dp[i][j - 1] + ins)
    S = D = I = 0
    ok = [False] * n
    status = ["del"] * n
    inserted = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0:
            rt, rw = R[i - 1][0], R[i - 1][1]
            ht, hw = H[j - 1]
            near = abs(rt - ht) <= TOL
            cost = 0 if (rw == hw and near) else (1 if near else INF)
            if dp[i][j] == dp[i - 1][j - 1] + cost:
                if cost == 0:
                    ok[i - 1] = True
                    status[i - 1] = "ok"
                else:
                    S += 1
                    status[i - 1] = "sub"
                i, j = i - 1, j - 1
                continue
        if i > 0 and dp[i][j] == dp[i - 1][j] + 1:
            D += 1
            i -= 1
        else:
            if count_ins:
                I += 1
                inserted.append(H[j - 1])
            j -= 1
    align.status, align.inserted = status, inserted[::-1]
    return S, D, I, ok


def main():
    hyp_path, xmls = sys.argv[1], sys.argv[2:]
    ref_all = load_ref(xmls)
    vocab = {w for _, w, _ in ref_all}
    d, hyp_all = load_hyp(hyp_path, vocab)
    speakers = sorted({s for *_, s in ref_all})
    full = len(speakers) >= 4
    info = d.get("asr_info", {})
    print(f"模型：{d.get('asr_model')}　語言：{info.get('language')}　判斷：{info.get('detect')}")
    print(f"講者：{', '.join(speakers)}　{'（齊全 → 標準 WER）' if full else '（不齊全 → 只算這幾位說的字的正確率）'}")
    segs = [(s["start_ms"] / 1000, s["end_ms"] / 1000) for s in d["segments"]]

    def covered(t):
        return any(a - 0.5 <= t <= b + 0.5 for a, b in segs)

    for skip in (False, True):
        R = [r for r in ref_all if not (skip and r[1] in FILLERS)]
        H = [h for h in hyp_all if not (skip and h[1] in FILLERS)]
        S, D, I, ok = align(R, H, count_ins=full)
        n = len(R)
        nocov = sum(1 for (t, *_), o in zip(R, ok) if not o and not covered(t))
        title = "去掉語助詞（um/uh/oh…）" if skip else "全部的字"
        print(f"\n=== {title} ===")
        if full:
            print(f"參考 {n} 字；替換 {S}、刪除 {D}、插入 {I} → WER {(S + D + I) / n:.1%}")
        else:
            print(f"參考 {n} 字；正確 {sum(ok)}（{sum(ok) / n:.1%}）；錯／漏 {n - sum(ok)}（{(n - sum(ok)) / n:.1%}）")
        print(f"  錯／漏的字中，落在「系統沒有任何段落」的時間：{nocov} 字")
        if skip:
            analyze(R, align.status, segs, align.inserted)
            print("\n錯／漏的字（前 40 個，[ ] 為該字，附前後文）：")
            shown = 0
            for k, ((t, w, spk), o) in enumerate(zip(R, ok)):
                if o:
                    continue
                ctx = " ".join(("[" + x[1] + "]") if kk == k else x[1]
                               for kk, x in enumerate(R[max(0, k - 4):k + 5], start=max(0, k - 4)))
                print(f"  {int(t // 60):02d}:{t % 60:04.1f} {spk}  {ctx}{'' if covered(t) else '　← 沒有段落'}")
                shown += 1
                if shown >= 40:
                    break


def analyze(R, status, segs, inserted):
    def covered(t):
        return any(a - 0.5 <= t <= b + 0.5 for a, b in segs)

    by_spk = {}
    for t, w, spk in R:
        by_spk.setdefault(spk, []).append(t)

    def overlapped(t, spk):
        return any(abs(t - u) <= 1.0 for o, ts in by_spk.items() if o != spk for u in ts)

    cats = {"沒有段落": 0, "口吃／重複": 0, "說一半的字": 0, "和別人同時說話": 0, "其他": 0}
    per = {}
    for k, ((t, w, spk), st) in enumerate(zip(R, status)):
        n_, e_ = per.get(spk, (0, 0))
        per[spk] = (n_ + 1, e_ + (st != "ok"))
        if st == "ok":
            continue
        prv = R[k - 1][1] if k > 0 and R[k - 1][2] == spk else None
        nxt = R[k + 1][1] if k + 1 < len(R) and R[k + 1][2] == spk else None
        if not covered(t):
            cats["沒有段落"] += 1
        elif len(w) == 1 and w not in ("a", "i"):
            cats["說一半的字"] += 1
        elif w in (prv, nxt):
            cats["口吃／重複"] += 1
        elif overlapped(t, spk):
            cats["和別人同時說話"] += 1
        else:
            cats["其他"] += 1
    print("\n錯誤分類（去掉語助詞後的替換＋刪除）：" + "、".join(f"{k} {v}" for k, v in cats.items()))
    print("各講者：" + "、".join(f"{s} {e}/{n}（{e / n:.0%}）" for s, (n, e) in sorted(per.items())))
    if inserted:
        print("多出來的字（插入）：" + " ".join(w for _, w in inserted[:40]))


if __name__ == "__main__":
    main()
