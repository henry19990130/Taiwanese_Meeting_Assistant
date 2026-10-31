from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "backend"))
sys.path.insert(0, str(HERE))

from demo_meetings_data import MEETINGS

SEED_MODEL = "seed-demo"
SUMMARY_MODEL = "qwen3.8:27b（模擬資料）"
MEETING_SECONDS = 30 * 60
WEEKDAY = "一二三四五六日"


def build_segments(lines: list[str]) -> list[dict]:
    weights = [len(t) + 6 for t in lines]
    scale = (MEETING_SECONDS - 5) / sum(weights)
    segs, t = [], 0.0
    for i, (text, w) in enumerate(zip(lines, weights)):
        dur = w * scale
        segs.append({"segment_index": i, "start_ms": int(t * 1000),
                     "end_ms": int((t + dur - 0.4) * 1000), "text": text})
        t += dur
    return segs


def quote_of(text: str) -> str:
    parts = [p for p in re.split(r"[，。？！、]", text) if p.strip()]
    best = max(parts, key=len) if parts else text
    return best[:30]


def build_raw(m: dict) -> dict:
    def ev(idxs):
        return [{"segment_id": f"S{i + 1:04d}", "quote": quote_of(m["lines"][i])} for i in idxs]

    mc = {
        "reports": [{"id": f"R{i + 1:03d}", "topic": t, "summary": s, "evidence": ev(x)}
                    for i, (t, s, x) in enumerate(m["reports"])],
        "discussions": [{"id": f"D{i + 1:03d}", "topic": t, "summary": s, "key_points": kp, "evidence": ev(x)}
                        for i, (t, s, kp, x) in enumerate(m["discussions"])],
        "decisions": [{"id": f"DEC{i + 1:03d}", "summary": s,
                       "related_ids": [f"D{j + 1:03d}" for j in rel], "evidence": ev(x)}
                      for i, (s, rel, x) in enumerate(m["decisions"])],
        "action_items": [{"id": f"A{i + 1:03d}", "task": t, "assignees": who, "due_date": None, "due_text": due,
                          "related_ids": [f"DEC{j + 1:03d}" for j in rel], "evidence": ev(x)}
                         for i, (t, who, due, rel, x) in enumerate(m["actions"])],
    }
    nm = m.get("next")
    mc["next_meeting"] = (
        {"date": None, "date_text": nm[0], "time": nm[1], "status": nm[2], "evidence": ev(nm[3])}
        if nm else {"date": None, "date_text": None, "time": None, "status": "not_mentioned", "evidence": []}
    )
    return {"headline": m["headline"], "meeting_content": mc,
            "review_notes": [{"field": f, "reason": r} for f, r in m.get("review", [])]}


def build_all() -> list[dict]:
    from app.repositories.transcripts import build_transcript
    from app.services.summarizer_service import normalize

    out = []
    for m in MEETINGS:
        date = dt.date.fromisoformat(m["date"])
        start = dt.time.fromisoformat(m["start"])
        end = (dt.datetime.combine(date, start) + dt.timedelta(seconds=MEETING_SECONDS)).time()
        segs = build_segments(m["lines"])
        transcript = build_transcript("00000000-0000-0000-0000-000000000000", segs, SEED_MODEL)
        meeting = {"date": date, "start_time": start, "end_time": end}
        summary = normalize(build_raw(m), transcript, meeting)
        out.append({"m": m, "date": date, "start": start, "end": end, "segments": segs, "summary": summary})
    return out


SQL_SEEDED = """
SELECT m.id FROM meetings m JOIN meeting_transcripts t ON t.meeting_id = m.id
WHERE m.created_by = %s AND t.model_name = %s
"""


def remove_seeded(conn, user_id) -> int:
    from app.repositories import meetings
    ids = [r["id"] for r in conn.execute(SQL_SEEDED, (user_id, SEED_MODEL)).fetchall()]
    for mid in ids:
        meetings.delete_meeting(conn, mid)
    return len(ids)


def seed(username: str, only_remove: bool) -> int:
    from app.db import get_conn
    from app.repositories import meetings, summaries, transcripts, users

    built = [] if only_remove else build_all()
    with get_conn() as conn:
        user = users.get_by_username(conn, username)
        if user is None:
            print(f"找不到帳號 {username}（先用 create_user.py 建立）")
            return 1
        removed = remove_seeded(conn, user["id"])
        if removed:
            print(f"已刪除之前放進去的 {removed} 場模擬會議")
        for b in built:
            mtg = meetings.create_meeting(
                conn, meeting_name=b["m"]["name"], date=b["date"], start_time=b["start"], end_time=b["end"],
                audio_path=None, source_type="transcript", created_by=user["id"])
            transcripts.save_transcript(conn, mtg["id"], b["segments"], SEED_MODEL)
            transcripts.confirm(conn, mtg["id"], {"enabled": True, "suggestions": [], "problems": [],
                                                  "glossary_count": 0, "manual": []})
            summaries.upsert_summary(conn, mtg["id"], b["summary"], SUMMARY_MODEL)
            meetings.update_status(conn, mtg["id"], "completed")
            mc = b["summary"]["meeting_content"]
            print(f"✅ {b['date']:%m/%d} {b['m']['name']}：{len(b['segments'])} 段、"
                  f"決議 {len(mc['decisions'])}、待辦 {len(mc['action_items'])}")
    if not only_remove:
        print(f"\n完成：{len(built)} 場模擬會議已放進帳號 {username}")
    return 0


def fmt_md(d) -> str:
    if not d:
        return ""
    d = dt.date.fromisoformat(d) if isinstance(d, str) else d
    return f"{d.month}/{d.day}（{WEEKDAY[d.weekday()]}）"


def write_list(path: Path) -> None:
    built = build_all()
    L = ["# 模擬會議資料清單（demo 帳號）", "",
         "給「會議小幫手」搜尋功能測試用。虛構公司「禾豐生活」（居家用品電商），10 場會議，每場約 30 分鐘。",
         "放入方式：在 Colab 執行 `!cd /content/test2/backend && python ../scripts/seed_demo_meetings.py`",
         "",
         "**人物**：志豪（專案統籌）、怡君（工程）、阿明（設計）、佩珊（行銷）、小陳／小黃（業務）、"
         "建宏（財務）、美玲（人資）、雅婷（客服主管）", "",
         "## 總覽", "", "| # | 日期 | 時間 | 會議 | 一句話總結 |", "|---|---|---|---|---|"]
    for i, b in enumerate(built, 1):
        L.append(f"| {i} | {fmt_md(b['date'])} | {b['start']:%H:%M}–{b['end']:%H:%M} | {b['m']['name']} | {b['summary']['headline']} |")
    for i, b in enumerate(built, 1):
        mc = b["summary"]["meeting_content"]
        L += ["", f"## {i}. {b['m']['name']}　{fmt_md(b['date'])} {b['start']:%H:%M}", "",
              f"> {b['summary']['headline']}", "", "**決議**", ""]
        L += [f"- {d['id']} {d['summary']}" for d in mc["decisions"]] or ["- 無"]
        L += ["", "**待辦**", "", "| ID | 事項 | 負責 | 期限 |", "|---|---|---|---|"]
        for a in mc["action_items"]:
            due = fmt_md(a["due_date"]) if a["due_date"] else (a["due_text"] or "未定")
            if a["due_date"] and a["due_text"]:
                due += f"（原文：{a['due_text']}）"
            L.append(f"| {a['id']} | {a['task']} | {'、'.join(a['assignees']) or '**未指定**'} | {due} |")
        nm = mc["next_meeting"]
        nm_text = ("未提及" if nm["status"] == "not_mentioned"
                   else " ".join(x for x in [fmt_md(nm["date"]) if nm["date"] else nm["date_text"], nm["time"]] if x))
        L += ["", f"**下次會議**：{nm_text}"]
        if b["summary"]["review_notes"]:
            L += ["", "**需要確認**", ""] + [f"- {n['field']}：{n['reason']}" for n in b["summary"]["review_notes"]]
    L += ["", "## 測試問題與預期答案", "",
          "### 查待辦（list_action_items）", "",
          "| 問題 | 預期答案 |", "|---|---|",
          "| 怡君負責哪些事？ | 網址對照表（9/21）、會員資料轉移程式（10 月底）、Line 登入申請、壓力測試（原 10 月底，10/19 改最晚下週二）、資料欄位清單給佩珊 |",
          "| 還沒有負責人的待辦有哪些？ | 問法務會員同意條款（9/7）、指定到貨日帶到客服會議（9/28）、隱私權條款草稿（10/5，10/12 改由佩珊）、通知美玲課程改期（10/19）、與新物流簽約（10/22） |",
          "| 佩珊 10 月要交什麼？ | 雙十一方案試算（10/10 前，和建宏）、個資條款草稿交法務（10/20 前）；11/5 前常見問題頁、11/12 停機公告 |",
          "| 小陳有哪些待辦？ | 倉庫出貨量能、企業客戶名單、企業下單需求、備援供應商聯絡方式、倉庫退貨流程 |",
          "",
          "### 跨會議追蹤（search_content／get_meeting_summary）", "",
          "| 問題 | 預期答案 |", "|---|---|",
          "| 官網什麼時候上線？ | 原訂 11/15（9/7 定、10/5 維持），10/19 改成 11/22，因為金流審核延到 11/10、壓力測試要重跑 |",
          "| 壓力測試為什麼不找外包？ | 外包報價八萬，怡君有經驗自己用工具測（10/5） |",
          "| 會員等級的門檻是多少？ | 銀卡年消費五千、金卡兩萬（9/21 原則通過；10/15 預算會議確認維持） |",
          "| 個資條款後來誰寫？ | 9/7 未指定 → 9/21 指定佩珊問法務 → 10/5 法務要我們先寫草稿、未指定 → 10/12 決定佩珊寫、10/20 前交 → 10/19 法務已改好 |",
          "| 指定到貨日後來怎麼處理？ | 9/28 先記下來 → 10/22 決定改付費選項，每件加 15 元，新物流簽約人未定 |",
          "| 明年行銷預算多少？ | 提報九百萬，10/15 砍到七百五十萬 |",
          "",
          "### 找某場會議（search_meetings）", "",
          "- 「9 月有哪些會議？」→ 9/7、9/10、9/21、9/28 四場",
          "- 「建宏有參加的會議」→ 9/10 業績檢討、10/15 預算初審（9/21、9/28 有提到他）",
          "- 「討論過預算的會議」→ 10/15 年度預算初審（9/7 攝影預算、10/8 訓練預算也有提到）",
          "",
          "### 這句話出自哪場會議（出處搜尋）", "",
          "| 輸入 | 類型 | 預期出處 |", "|---|---|---|",
          "| 八月小陳業績五十萬，是全組最高 | 原文 | 9/10 第三季業績檢討 |",
          "| 客服系統就是五個人共用一個帳號 | 原文 | 10/12 資安與個資盤點會議 |",
          "| 好啊，按呢較穩，毋過設計定稿一定要準時 | 原文（台語） | 9/7 官網改版啟動會議 |",
          "| 有人說五千筆訂單同時下單結帳會很慢 | 用字不同 | 10/19 官網改版上線前確認會議 |",
          "| 休眠的會員不要寄電子報 | 用字不同 | 9/21 會員系統規劃會議 |",
          "| 那次說要把廣告錢從臉書挪去 Line | 只記得意思 | 9/28 中秋檔期行銷復盤（10/15 預算會議也有提到） |",
          "| 新人一開始不要讓他們看到全部客人的資料 | 只記得意思 | 10/8 新進人員訓練規劃（10/12 資安會議也有） |",
          "| 年終獎金要發多少 | 不存在 | 應回答「沒有找到」（只有業績獎金，不是年終獎金） |",
          "",
          "### 應該婉拒的問題", "",
          "- 「幫我寫一封請假的 email」「今天天氣如何」「推薦一家午餐」→ 婉拒，並給出選單"]
    path.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"已輸出資料清單：{path}")


def main() -> int:
    ap = argparse.ArgumentParser(description="放入 10 場模擬會議")
    ap.add_argument("--user", default="demo")
    ap.add_argument("--remove", action="store_true", help="只刪除之前放進去的模擬會議")
    ap.add_argument("--list", metavar="檔名.md", help="輸出資料清單，不碰資料庫")
    args = ap.parse_args()
    if args.list:
        write_list(Path(args.list))
        return 0
    return seed(args.user, args.remove)


if __name__ == "__main__":
    sys.exit(main())
