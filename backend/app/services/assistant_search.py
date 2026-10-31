from __future__ import annotations

import calendar
import datetime as dt
import re

_PUNCT = re.compile(r"[\s，。、！？：；「」『』（）()《》〈〉…—\-,.!?:;\"'~～·/]+")


def norm(s: str) -> str:
    return _PUNCT.sub("", str(s or "")).lower()


def bigrams(s: str) -> set[str]:
    s = norm(s)
    if len(s) < 2:
        return {s} if s else set()
    return {s[i:i + 2] for i in range(len(s) - 1)}


def contain(query: str, text: str) -> float:
    q, t = norm(query), norm(text)
    if not q or not t:
        return 0.0
    if q in t:
        return 1.0
    qb = bigrams(q)
    return len(qb & bigrams(t)) / len(qb) if qb else 0.0


def keywords(query: str) -> list[str]:
    parts = re.split(r"[\s,，、；;]+|(?<=\S)(?:和|跟|與|或)(?=\S)", str(query or ""))
    return [p for p in (norm(x) for x in parts) if p]


def text_score(query: str, text: str) -> float:
    kws = keywords(query)
    whole = contain(query, text)
    if len(kws) <= 1:
        return whole
    t = norm(text)
    hit = sum(1 for k in kws if k in t) / len(kws)
    return max(whole, 0.5 * whole + 0.5 * hit)


def parse_period(text: str | None, today: dt.date) -> tuple[dt.date, dt.date] | None:
    if not text:
        return None
    t = re.sub(r"\s+", "", str(text))
    m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})(?:~|～|到|至)(\d{4}-\d{2}-\d{2})", t)
    if m:
        return dt.date.fromisoformat(m.group(1)), dt.date.fromisoformat(m.group(2))
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", t):
        d = dt.date.fromisoformat(t)
        return d, d

    def month_range(y: int, mth: int) -> tuple[dt.date, dt.date]:
        return dt.date(y, mth, 1), dt.date(y, mth, calendar.monthrange(y, mth)[1])

    monday = today - dt.timedelta(days=today.weekday())
    if t in ("今天", "今日"):
        return today, today
    if t in ("昨天",):
        d = today - dt.timedelta(days=1)
        return d, d
    if t in ("這週", "這禮拜", "本週", "這個禮拜", "這星期"):
        return monday, monday + dt.timedelta(days=6)
    if t in ("上週", "上禮拜", "上個禮拜", "上星期"):
        return monday - dt.timedelta(days=7), monday - dt.timedelta(days=1)
    if t in ("下週", "下禮拜", "下個禮拜", "下星期"):
        return monday + dt.timedelta(days=7), monday + dt.timedelta(days=13)
    if t in ("這個月", "本月", "這月"):
        return month_range(today.year, today.month)
    if t in ("上個月", "上月"):
        y, mth = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
        return month_range(y, mth)
    if t in ("下個月", "下月"):
        y, mth = (today.year, today.month + 1) if today.month < 12 else (today.year + 1, 1)
        return month_range(y, mth)
    if t in ("今年", "本年"):
        return dt.date(today.year, 1, 1), dt.date(today.year, 12, 31)
    m = re.fullmatch(r"(?:最近|過去|近)(\d+)(天|週|個月)", t)
    if m:
        n = int(m.group(1))
        days = n * {"天": 1, "週": 7, "個月": 30}[m.group(2)]
        return today - dt.timedelta(days=days), today
    m = re.fullmatch(r"(?:(\d{4})年)?(\d{1,2})月(?:份)?", t)
    if m:
        mth = int(m.group(2))
        if 1 <= mth <= 12:
            y = int(m.group(1)) if m.group(1) else (today.year if mth <= today.month + 1 else today.year - 1)
            return month_range(y, mth)
    m = re.fullmatch(r"(\d{1,2})[/月](\d{1,2})[日號]?", t)
    if m:
        try:
            d = dt.date(today.year, int(m.group(1)), int(m.group(2)))
        except ValueError:
            return None
        return d, d
    return None


def fmt_ms(ms) -> str:
    if ms is None:
        return ""
    s = int(ms) // 1000
    h, m, sec = s // 3600, s % 3600 // 60, s % 60
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"


class Sources:

    def __init__(self) -> None:
        self.items: list[dict] = []
        self._keys: dict[tuple, int] = {}

    def add(self, meeting: dict, kind: str, text: str, segment_id: str | None = None,
            item_id: str | None = None, extra: dict | None = None) -> int:
        key = (meeting["id"], kind, segment_id, item_id)
        if key in self._keys:
            return self._keys[key]
        seg = next((s for s in meeting["segments"] if s["segment_id"] == segment_id), None) if segment_id else None
        n = len(self.items) + 1
        self.items.append({
            "n": n, "kind": kind, "meeting_id": meeting["id"], "meeting_name": meeting["name"],
            "date": meeting["date"].isoformat() if meeting.get("date") else None,
            "segment_id": segment_id, "time": fmt_ms(seg["start_ms"]) if seg else None,
            "item_id": item_id, "text": text, **(extra or {}),
        })
        self._keys[key] = n
        return n

    def get(self, n: int) -> dict | None:
        return self.items[n - 1] if 1 <= n <= len(self.items) else None


def _first_seg(item: dict) -> str | None:
    ev = item.get("evidence") or []
    return ev[0]["segment_id"] if ev else None


def _in_period(d: dt.date | None, period) -> bool:
    return period is None or (d is not None and period[0] <= d <= period[1])


def _date_label(d: dt.date | None) -> str:
    return f"{d.month}/{d.day}" if d else ""


def search_meetings(lib: list[dict], src: Sources, today: dt.date, query: str | None = None,
                    period: str | None = None, person: str | None = None, limit: int = 8) -> dict:
    rng = parse_period(period, today)
    found = []
    for m in lib:
        if not _in_period(m["date"], rng):
            continue
        sm = m["summary"] or {}
        if person:
            p = norm(person)
            names = {norm(a) for x in sm.get("action_items", []) for a in x.get("assignees", [])}
            if p not in names and not any(p in norm(s["text"]) for s in m["segments"]):
                continue
        score = 1.0
        if query:
            fields = [m["name"], sm.get("headline") or ""]
            fields += [d.get("topic") or "" for d in sm.get("discussions", [])]
            fields += [d.get("summary") or "" for d in sm.get("decisions", [])]
            fields += [a.get("task") or "" for a in sm.get("action_items", [])]
            score = max([text_score(query, f) for f in fields if f] or [0])
            if score < 0.5:
                if any(k in norm(s["text"]) for s in m["segments"] for k in keywords(query)):
                    score = 0.5
                else:
                    continue
        found.append((score, m))
    found.sort(key=lambda x: (-x[0], -(x[1]["date"] or dt.date.min).toordinal()))
    out = []
    for score, m in found[:limit]:
        sm = m["summary"] or {}
        n = src.add(m, "meeting", sm.get("headline") or m["name"])
        out.append({"ref": n, "meeting_id": m["id"], "name": m["name"], "date": m["date"].isoformat(),
                    "headline": sm.get("headline"),
                    "decisions": len(sm.get("decisions", [])), "action_items": len(sm.get("action_items", []))})
    return {"count": len(found), "period": [d.isoformat() for d in rng] if rng else None, "meetings": out}


def search_content(lib: list[dict], src: Sources, today: dt.date, query: str,
                   period: str | None = None, limit: int = 8) -> dict:
    rng = parse_period(period, today)
    hits = []
    for m in lib:
        if not _in_period(m["date"], rng):
            continue
        for s in m["segments"]:
            sc = text_score(query, s["text"])
            if sc >= 0.34:
                hits.append((sc, "segment", m, s["text"], s["segment_id"], None))
        sm = m["summary"] or {}
        for kind, field, key in (("decision", "decisions", "summary"), ("action", "action_items", "task"),
                                 ("discussion", "discussions", "summary"), ("report", "reports", "summary")):
            for it in sm.get(field, []):
                text = it.get(key) or ""
                if kind in ("discussion", "report") and it.get("topic"):
                    text = f"{it['topic']}：{text}"
                sc = text_score(query, text)
                if sc >= 0.34:
                    hits.append((sc + 0.05, kind, m, text, _first_seg(it), it.get("id")))
    hits.sort(key=lambda h: -h[0])
    out, seen = [], set()
    for sc, kind, m, text, sid, iid in hits:
        key = (m["id"], sid if kind == "segment" else iid)
        if key in seen:
            continue
        seen.add(key)
        n = src.add(m, kind, text, segment_id=sid, item_id=iid)
        out.append({"ref": n, "type": kind, "meeting": m["name"], "date": m["date"].isoformat(),
                    "text": text, "score": round(sc, 2)})
        if len(out) >= limit:
            break
    return {"count": len(out), "results": out}


def get_meeting_summary(lib: list[dict], src: Sources, meeting_id: str) -> dict:
    m = next((x for x in lib if x["id"] == str(meeting_id)), None)
    if m is None:
        return {"error": "找不到這場會議（或不屬於你的帳號）"}
    sm = m["summary"] or {}
    head = src.add(m, "meeting", sm.get("headline") or m["name"])
    return {
        "ref": head, "meeting_id": m["id"], "name": m["name"], "date": m["date"].isoformat(),
        "headline": sm.get("headline"),
        "decisions": [{"ref": src.add(m, "decision", d.get("summary") or "", _first_seg(d), d.get("id")),
                       "text": d.get("summary")} for d in sm.get("decisions", [])],
        "action_items": [{"ref": src.add(m, "action", a.get("task") or "", _first_seg(a), a.get("id"),
                                         {"assignees": a.get("assignees", []), "due_date": a.get("due_date"),
                                          "due_text": a.get("due_text")}),
                          "task": a.get("task"), "assignees": a.get("assignees", []),
                          "due": a.get("due_date") or a.get("due_text")} for a in sm.get("action_items", [])],
        "discussions": [{"topic": d.get("topic"), "summary": d.get("summary")} for d in sm.get("discussions", [])],
        "next_meeting": sm.get("next_meeting"),
        "review_notes": [n.get("reason") for n in sm.get("review_notes", [])],
    }


def list_action_items(lib: list[dict], src: Sources, today: dt.date, assignee: str | None = None,
                      due_period: str | None = None, unassigned: bool = False,
                      meeting_period: str | None = None, limit: int = 30) -> dict:
    drng = parse_period(due_period, today)
    mrng = parse_period(meeting_period, today)
    rows = []
    for m in lib:
        if not _in_period(m["date"], mrng):
            continue
        for a in (m["summary"] or {}).get("action_items", []):
            who = a.get("assignees", [])
            if unassigned and who:
                continue
            if assignee and not any(norm(assignee) in norm(w) for w in who):
                continue
            due = dt.date.fromisoformat(a["due_date"]) if a.get("due_date") else None
            if drng and not _in_period(due, drng):
                continue
            rows.append((due, m, a))
    rows.sort(key=lambda r: (r[0] is None, r[0] or dt.date.max, r[1]["date"]))
    out = []
    for due, m, a in rows[:limit]:
        n = src.add(m, "action", a.get("task") or "", _first_seg(a), a.get("id"),
                    {"assignees": a.get("assignees", []), "due_date": a.get("due_date"), "due_text": a.get("due_text")})
        out.append({"ref": n, "task": a.get("task"), "assignees": a.get("assignees", []) or ["未指定"],
                    "due": a.get("due_date") or a.get("due_text") or "未定",
                    "meeting": m["name"], "meeting_date": m["date"].isoformat()})
    return {"count": len(rows), "items": out,
            "due_period": [d.isoformat() for d in drng] if drng else None}


def find_quote(lib: list[dict], src: Sources, text: str, limit: int = 3) -> dict:
    best_per = []
    for m in lib:
        segs = m["segments"]
        best = None
        for i in range(len(segs)):
            for w in (1, 2, 3):
                if i + w > len(segs):
                    break
                window = "".join(s["text"] for s in segs[i:i + w])
                sc = contain(text, window)
                adj = sc - 0.06 * (w - 1)
                if best is None or adj > best[0] + 1e-9:
                    best = (adj, i, w, sc)
        if best and best[3] > 0:
            best_per.append((best[3], m, best[1], best[2]))
    best_per.sort(key=lambda x: -x[0])
    out = []
    for sc, m, i, w in best_per[:limit]:
        if sc < 0.35:
            break
        segs = m["segments"]
        main = max(range(i, i + w), key=lambda k: contain(text, segs[k]["text"]))
        n = src.add(m, "segment", segs[main]["text"], segs[main]["segment_id"])
        ctx = [{"segment_id": s["segment_id"], "time": fmt_ms(s["start_ms"]), "text": s["text"],
                "match": i <= k < i + w}
               for k, s in enumerate(segs) if i - 1 <= k <= i + w]
        out.append({"ref": n, "meeting": m["name"], "meeting_id": m["id"], "date": m["date"].isoformat(),
                    "segment_id": segs[main]["segment_id"], "time": fmt_ms(segs[main]["start_ms"]),
                    "score": round(sc, 2), "confidence": "high" if sc >= 0.75 else "maybe", "context": ctx})
    return {"count": len(out), "results": out}


def people(lib: list[dict]) -> list[str]:
    cnt: dict[str, int] = {}
    for m in lib:
        for a in (m["summary"] or {}).get("action_items", []):
            for w in a.get("assignees", []):
                cnt[w] = cnt.get(w, 0) + 1
    return [k for k, _ in sorted(cnt.items(), key=lambda kv: (-kv[1], kv[0]))]
