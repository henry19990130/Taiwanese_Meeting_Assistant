"""把我寫的摘要（targets/*.json）轉成訓練／評測樣本，格式與 summarizer_service 送給 Qwen 的完全相同。"""
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import sumtool as T  # noqa: E402
from app.services.summary_prompt import build_user_message, system_prompt  # noqa: E402

DEV_N = 3


def main(out: Path):
    out.mkdir(parents=True, exist_ok=True)
    man = json.load(open(HERE / "manifest.json"))
    M = T.meetings()
    rows = {"train": [], "test": []}
    skipped = []
    for e in man:
        p = HERE / "targets" / f"{e['id']}.json"
        if not p.exists() or T.validate(e["id"], p, e["max_segs"]):
            skipped.append(e["id"])
            continue
        tr = T.transcript(M[e["id"]], e["max_segs"])
        target = json.load(open(p, encoding="utf-8"))
        rows[e["split"]].append({
            "id": e["id"], "lang": e["lang"], "split": e["split"],
            "system": system_prompt(e["lang"]),
            "user": build_user_message(tr),
            "target": json.dumps(target, ensure_ascii=False),
            "transcript": tr,
        })
    random.Random(0).shuffle(rows["train"])
    dev, train = rows["train"][:DEV_N], rows["train"][DEV_N:]
    for name, rr in [("train", train), ("dev", dev), ("test", rows["test"])]:
        for r in rr:
            r["kind"] = "real"
        with open(out / f"sft_{name}.jsonl", "w", encoding="utf-8") as f:
            for r in rr:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"train {len(train)} / dev {len(dev)} / test {len(rows['test'])}；略過 {skipped}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
