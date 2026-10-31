from __future__ import annotations

import difflib
import json
import re
import sys
from pathlib import Path

CATEGORIES = [
    ("decisions", "決議", lambda x: x.get("summary") or "", "point"),
    ("action_items", "待辦", lambda x: x.get("task") or "", "point"),
    ("reports", "報告", lambda x: f'{x.get("topic") or ""}：{x.get("summary") or ""}', "span"),
    ("discussions", "討論", lambda x: f'{x.get("topic") or ""}：{x.get("summary") or ""}', "span"),
]
CAT_NAME = {k: n for k, n, _, _ in CATEGORIES}
MATCH = 0.5
TEXT_MATCH = 0.8
SHOW = 46


def norm(s: str | None) -> str:
    return re.sub(r"[\s，。、！？,.!?：:；;「」（）()]", "", s or "")


def text_ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, norm(a), norm(b)).ratio()


def segs(item: dict) -> set[int]:
    out = set()
    for ev in item.get("evidence") or []:
        m = re.search(r"\d+", str(ev.get("segment_id") or ""))
        if m:
            out.add(int(m.group()))
    return out


def covered_frac(a: set[int], b: set[int], mode: str, w: dict[int, float]) -> float:
    if not a or not b:
        return 0.0
    lo, hi = min(b), max(b)
    inside = (lambda x: x in b) if mode == "point" else (lambda x: lo <= x <= hi)
    total = sum(w.get(x, 1.0) for x in a)
    return sum(w.get(x, 1.0) for x in a if inside(x)) / total


def short(s: str) -> str:
    return s if len(s) <= SHOW else s[:SHOW] + "…"


class Item:
    def __init__(self, run: int, cat: str, raw: dict, text_of, mode: str):
        self.run, self.cat, self.raw, self.mode = run, cat, raw, mode
        self.id = raw.get("id") or "?"
        self.text = text_of(raw)
        self.segs = segs(raw)
        self.w: dict[int, float] = {}

    def score(self, other: "Item", mode: str | None = None) -> float:
        md = mode or self.mode
        if self.segs and other.segs:
            return max(covered_frac(self.segs, other.segs, md, self.w),
                       covered_frac(other.segs, self.segs, md, other.w))
        r = text_ratio(self.text, other.text)
        return r if r >= TEXT_MATCH else 0.0

    def label(self) -> str:
        return f"{self.id} {short(self.text)}"


def load(path: str) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if "meeting_content" not in data:
        sys.exit(f"{path} 不是「下載重點」產生的檔案（找不到 meeting_content）")
    return data


def build_items(runs: list[dict]) -> dict[str, list[list[Item]]]:
    out = {}
    for key, _, text_of, mode in CATEGORIES:
        out[key] = [[Item(i, key, x, text_of, mode) for x in r["meeting_content"].get(key) or []]
                    for i, r in enumerate(runs)]
        for per_run in out[key]:
            cnt: dict[int, int] = {}
            for it in per_run:
                for sg in it.segs:
                    cnt[sg] = cnt.get(sg, 0) + 1
            for it in per_run:
                it.w = {sg: 1 / cnt[sg] for sg in it.segs}
    return out


def group(per_run: list[list[Item]]) -> list[dict]:
    groups: list[dict] = []
    for items in per_run:
        for it in items:
            scores = [(g, it.score(g["seed"])) for g in groups if g["seed"].run != it.run]
            best = max((sc for _, sc in scores), default=0)
            hits = [g for g, sc in scores if sc >= MATCH and sc >= best * 0.8]
            if not hits:
                groups.append({"seed": it, "runs": {it.run: [it]}})
                continue
            for g in hits:
                g["runs"].setdefault(it.run, []).append(it)
    return groups


def main(paths: list[str]) -> int:
    if len(paths) < 2:
        print("用法：python compare_summaries.py 重點_A.json 重點_B.json [重點_C.json ...]")
        return 1
    runs = [load(p) for p in paths]
    n = len(runs)
    labels = [f"第{i + 1}次" for i in range(n)]
    items = build_items(runs)

    if len({r.get("meeting", {}).get("id") for r in runs}) > 1:
        print("⚠️ 這些檔案來自不同的會議，比對結果可能沒有意義\n")

    print("=" * 64, "\n① 產出條件")
    for lab, p, r in zip(labels, paths, runs):
        s = r.get("llm_settings_at_export") or {}
        print(f"  {lab}  {Path(p).name}")
        print(f"        產生時間 {r.get('generated_at')}　模型 {r.get('model_name')}　"
              f"溫度 {s.get('temperature')}　seed {s.get('seed', '未記錄')}　上下文 {s.get('num_ctx')}　思考 {s.get('think')}")

    print("=" * 64, "\n② 一句話總結")
    heads = [r.get("headline") or "（無）" for r in runs]
    for lab, h in zip(labels, heads):
        print(f"  {lab}：{h}")
    head_sims = [text_ratio(heads[0], h) for h in heads[1:]]
    print("  與第1次的字面相似度：" + "　".join(f"{lab} {s:.0%}" for lab, s in zip(labels[1:], head_sims)))

    print("=" * 64, "\n③ 項目數")
    print("  類別　　" + "　".join(f"{lab:>4}" for lab in labels))
    for key, name, _, _ in CATEGORIES:
        counts = [len(x) for x in items[key]]
        print(f"  {name:<4}　" + "　".join(f"{c:>4}" for c in counts)
              + ("" if len(set(counts)) == 1 else "　← 不同"))
    counts = [len(r.get("review_notes") or []) for r in runs]
    print("  需確認　" + "　".join(f"{c:>4}" for c in counts) + ("" if len(set(counts)) == 1 else "　← 不同"))
    nm = [r["meeting_content"].get("next_meeting") or {} for r in runs]
    nm_txt = [f'{x.get("status")} {x.get("date") or ""} {x.get("time") or ""}'.strip() for x in nm]
    print("  下次會議　" + "　".join(nm_txt) + ("" if len(set(nm_txt)) == 1 else "　← 不同"))

    print("=" * 64)
    print("④ 各類項目")
    print("   ✓ = 該次有這一項　◆ = 該次有，但放在別的類別　· = 該次沒有")
    print("   （依「引用的逐字稿段落」判斷是不是同一項，用詞不同也算同一項）")

    present_any, present_same = [], []
    field_diffs: list[str] = []
    n_merge = n_split = n_moved = n_missing = 0

    for key, name, _, _ in CATEGORIES:
        per_run = items[key]
        if not any(per_run):
            continue
        groups = group(per_run)
        belong: dict[int, int] = {}
        for g in groups:
            for ms in g["runs"].values():
                for m in ms:
                    belong[id(m)] = belong.get(id(m), 0) + 1

        merged: set[int] = set()
        print(f"\n  【{name}】")
        for g in groups:
            marks, notes = [], []
            same = anyp = 0
            ref = g["seed"]
            for i in range(n):
                if i in g["runs"]:
                    marks.append("✓")
                    same += 1
                    anyp += 1
                    ms = g["runs"][i]
                    if len(ms) > 1:
                        notes.append(f"{labels[i]}拆成 {len(ms)} 項（{'、'.join(m.id for m in ms)}）")
                        n_split += 1
                    for m in ms:
                        if belong[id(m)] > 1:
                            notes.append(f"{labels[i]}的 {m.id} 把好幾件事合併成一項")
                            merged.add(id(m))
                    continue
                other = None
                for k2, _, _, _ in CATEGORIES:
                    if k2 == key:
                        continue
                    for cand in items[k2][i]:
                        if cand.score(g["seed"], mode="point") >= MATCH:
                            other = cand
                            break
                    if other:
                        break
                if other:
                    marks.append("◆")
                    anyp += 1
                    n_moved += 1
                    notes.append(f"{labels[i]}放在【{CAT_NAME[other.cat]}】{other.id}")
                else:
                    marks.append("·")
                    n_missing += 1
            present_any.append(anyp / n)
            present_same.append(same / n)
            print(f"   {''.join(marks)}  {ref.label()}")
            for note in dict.fromkeys(notes):
                print(f"          ↳ {note}")

            if key == "action_items" and len(g["runs"]) > 1:
                firsts = {i: ms[0].raw for i, ms in g["runs"].items()}
                for field, fname in (("due_date", "期限"), ("assignees", "負責人")):
                    vals = {i: json.dumps(v.get(field), ensure_ascii=False) for i, v in firsts.items()}
                    if len(set(vals.values())) > 1:
                        detail = "　".join(f"{labels[i]} {v}" for i, v in sorted(vals.items()))
                        print(f"          ↳ ⚠️ {fname}不同：{detail}")
                        field_diffs.append(f"{ref.id} {fname}：{detail}")

        n_merge += len(merged)

    print("\n" + "=" * 64, "\n⑤ 總結")
    keys = ("headline", "meeting_content", "review_notes")
    dump = lambda r: json.dumps({k: r.get(k) for k in keys}, sort_keys=True, ensure_ascii=False)
    identical = all(dump(r) == dump(runs[0]) for r in runs[1:])
    avg = lambda xs: sum(xs) / len(xs) if xs else 1.0
    print("  內容完全相同 ✅" if identical else "  內容有差異 ❗")
    print(f"  內容穩定度：{avg(present_any):.0%}　（每件事每次都有寫到的比例，不管放在哪一類）")
    print(f"  分類一致度：{avg(present_same):.0%}　（每件事每次都放在同一類的比例）")
    print(f"  差異來源：合併/拆開不同 {n_merge + n_split} 處　歸到不同類別 {n_moved} 處　某次漏掉 {n_missing} 處"
          f"　待辦欄位不同 {len(field_diffs)} 處")
    print(f"  一句話總結字面相似度：{avg(head_sims):.0%}")
    if field_diffs:
        print("  待辦欄位不同：")
        for d in field_diffs:
            print(f"    - {d}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
