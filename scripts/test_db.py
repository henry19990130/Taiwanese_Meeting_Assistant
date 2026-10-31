from __future__ import annotations

import datetime as dt
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import psycopg
from psycopg.rows import dict_row

from app import config, security
from app.repositories import meetings, sessions, summaries, transcripts, users

passed = 0


def ok(label: str, cond: bool) -> None:
    global passed
    if not cond:
        raise AssertionError(label)
    passed += 1
    print(f"  ✅ {label}")


def run(conn) -> None:
    print("[security]")
    h = security.hash_password("secret123")
    ok("正確密碼驗證通過", security.verify_password("secret123", h))
    ok("錯誤密碼驗證失敗", not security.verify_password("wrong", h))
    tok = security.new_session_token()
    ok("token 雜湊為 64 字元", len(security.hash_token(tok)) == 64)

    print("[users]")
    name = f"test_{uuid.uuid4().hex[:8]}"
    u = users.create_user(conn, name, h)
    ok("建立使用者", u["username"] == name)
    ok("用帳號查詢（含雜湊）", users.get_by_username(conn, name)["password_hash"] == h)
    ok("用 id 查詢", users.get_by_id(conn, u["id"])["username"] == name)
    ok("用字串 id 查詢", users.get_by_id(conn, str(u["id"]))["username"] == name)
    ok("重設密碼", users.set_password(conn, name, "x")["username"] == name)

    print("[sessions]")
    th = security.hash_token(tok)
    s = sessions.create_session(conn, th, u["id"], 3600)
    ok("建立 session，到期時間在未來", s["expires_at"] > s["created_at"])
    v = sessions.get_valid_session(conn, th)
    ok("有效 token 查得到使用者", v and v["username"] == name)
    ok("錯的 token 查不到", sessions.get_valid_session(conn, "0" * 64) is None)
    th2 = security.hash_token(security.new_session_token())
    sessions.create_session(conn, th2, u["id"], -1)
    ok("過期 token 查不到", sessions.get_valid_session(conn, th2) is None)
    ok("清除過期 session", sessions.delete_expired(conn) >= 1)
    ok("登出刪除 session", sessions.delete_session(conn, th))
    ok("登出後查不到", sessions.get_valid_session(conn, th) is None)

    print("[meetings]")
    m = meetings.create_meeting(
        conn, meeting_name="測試會議", date=dt.date(2026, 10, 14),
        start_time=dt.time(14, 0), audio_path="/tmp/test.m4a",
    )
    mid = m["id"]
    ok("建立會議，狀態 uploaded", m["status"] == "uploaded" and m["error"] is None)
    ok("查詢會議", meetings.get_meeting(conn, mid)["meeting_name"] == "測試會議")
    ok("查不存在的會議回傳 None", meetings.get_meeting(conn, uuid.uuid4()) is None)
    ok("改狀態 transcribing", meetings.update_status(conn, mid, "transcribing")["status"] == "transcribing")
    try:
        meetings.update_status(conn, mid, "failed")
        ok("update_status 拒絕 failed", False)
    except ValueError:
        ok("update_status 拒絕 failed", True)
    f = meetings.mark_failed(conn, mid, stage="transcribing", code="ASR_FAILED", message="辨識失敗。")
    ok("標記失敗並保存錯誤", f["status"] == "failed" and f["error"]["code"] == "ASR_FAILED")
    ok("恢復正常狀態清掉錯誤", meetings.update_status(conn, mid, "transcribing")["error"] is None)

    print("[transcripts]")
    ok("辨識前查不到逐字稿", transcripts.get_transcript(conn, mid) is None)
    segs = [
        {"segment_index": 1, "start_ms": 5200, "end_ms": 9000, "text": "先完成上傳功能 "},
        {"segment_index": 0, "start_ms": 0, "end_ms": 5200, "text": "咱今仔日欲討論新的系統"},
    ]
    saved = transcripts.save_transcript(conn, mid, segs, "adi-gov-tw/Taiwan-Tongues-ASR-CE-pretrained-v1.0")
    ok("存入 JSON 逐字稿", saved["segment_count"] == 2)
    ok("依順序排好並給 segment_id", [s["segment_id"] for s in saved["segments"]] == ["S0001", "S0002"])
    ok("文字去除前後空白", saved["segments"][1]["text"] == "先完成上傳功能")
    ok("記錄 ASR 模型", saved["asr_model"] == "adi-gov-tw/Taiwan-Tongues-ASR-CE-pretrained-v1.0")
    ok("ASR 完成 → transcribed", meetings.update_status(conn, mid, "transcribed")["status"] == "transcribed")
    t = transcripts.get_transcript(conn, mid)
    ok("從資料庫撈回整份 JSON", t == saved)
    ok("JSON 內的 meeting_id 正確", t["meeting_id"] == str(mid))
    saved2 = transcripts.save_transcript(conn, mid, segs[:1], "adi-gov-tw/Taiwan-Tongues-ASR-CE-pretrained-v1.0")
    ok("重跑 ASR 整份覆蓋、不重複", transcripts.get_transcript(conn, mid)["segment_count"] == 1 == saved2["segment_count"])

    print("[summaries]")
    ok("使用者按產生重點 → summarizing", meetings.update_status(conn, mid, "summarizing")["status"] == "summarizing")
    summary = {
        "headline": "決定先完成上傳功能。",
        "meeting_content": {
            "reports": [{"id": "R001", "topic": "進度", "summary": "ASR 完成"}],
            "discussions": [],
            "decisions": [{"id": "DEC001", "summary": "先完成上傳功能。"}],
            "action_items": [],
            "next_meeting": {"date": None, "time": None, "status": "not_mentioned"},
        },
        "review_notes": [],
    }
    up = summaries.upsert_summary(conn, mid, summary, "qwen3.8:27b")
    ok("寫入摘要", up["meeting_content"]["decisions"][0]["id"] == "DEC001")
    ok("一句話總結保存", up["headline"] == "決定先完成上傳功能。")
    ok("model_name 保存", up["model_name"] == "qwen3.8:27b")
    up2 = summaries.upsert_summary(conn, mid, summary, "qwen3.8:27b")
    ok("重複寫入只保留一份", up2["meeting_id"] == mid)
    edited = {**summary, "review_notes": [{"field": "decisions", "reason": "人工確認"}]}
    edited["meeting_content"] = {**summary["meeting_content"], "decisions": []}
    pe = summaries.update_content(conn, mid, edited)
    ok("人工修正：陣列整批替換", pe["meeting_content"]["decisions"] == [])
    ok("人工修正：model_name 不變", pe["model_name"] == "qwen3.8:27b")
    ok("人工修正：review_notes 保存", pe["review_notes"][0]["reason"] == "人工確認")
    ok("讀取摘要", summaries.get_summary(conn, mid)["review_notes"] == pe["review_notes"])
    ok("修正不存在的摘要回傳 None", summaries.update_content(conn, uuid.uuid4(), summary) is None)
    ok("摘要完成 → completed", meetings.update_status(conn, mid, "completed")["status"] == "completed")

    print("[delete]")
    d = meetings.delete_meeting(conn, mid)
    ok("刪除會議並回傳音檔路徑", d["audio_path"] == "/tmp/test.m4a")
    ok("逐字稿一起刪除", transcripts.get_transcript(conn, mid) is None)
    ok("摘要一起刪除", summaries.get_summary(conn, mid) is None)
    ok("刪不存在的會議回傳 None", meetings.delete_meeting(conn, mid) is None)


def main() -> int:
    conn = psycopg.connect(config.DATABASE_URL, row_factory=dict_row)
    try:
        run(conn)
    except Exception as exc:
        print(f"\n❌ 失敗：{type(exc).__name__}: {exc}")
        return 1
    finally:
        conn.rollback()
        conn.close()
    print(f"\n全部 {passed} 項通過（測試資料已回滾）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
