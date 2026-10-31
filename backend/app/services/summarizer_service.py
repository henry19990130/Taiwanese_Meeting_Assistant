from __future__ import annotations

import json
import logging
import re
from datetime import date

import httpx

from app import config
from app.services.due_date import parse_due
from app.services.summary_prompt import build_user_message, system_prompt

log = logging.getLogger(__name__)

LIST_FIELDS = ("reports", "discussions", "decisions", "action_items")
ID_PREFIX = {"reports": "R", "discussions": "D", "decisions": "DEC", "action_items": "A"}
NEXT_MEETING_STATUSES = ("confirmed", "tentative", "not_mentioned")
HEADLINE_MAX = 80
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^\d{2}:\d{2}(:\d{2})?$")


class SummaryError(Exception):
    pass


class SummarizerService:
    def __init__(self) -> None:
        self.backend = config.LLM_BACKEND
        self.model_name = "fake-summarizer" if self.backend == "fake" else config.LLM_MODEL

    def summarize(self, transcript: dict, meeting: dict | None = None, language: str = "zh") -> dict:
        meeting = meeting or {}
        if not transcript.get("segments"):
            raise SummaryError("逐字稿沒有內容")

        if self.backend == "fake":
            raw = _fake_summary(transcript, language)
        else:
            raw = self._call_ollama_with_retry(transcript, meeting, language)
        return normalize(raw, transcript, meeting)

    def _call_ollama_with_retry(self, transcript: dict, meeting: dict, language: str = "zh") -> dict:
        user_msg = build_user_message(transcript, meeting)
        prompt = system_prompt(language)
        last_error: Exception | None = None
        for attempt in (1, 2):
            seed = config.LLM_SEED + attempt - 1
            try:
                return self._call_ollama(user_msg, seed, prompt)
            except SummaryError as exc:
                last_error = exc
                log.warning("LLM 第 %d 次（seed=%d）回傳無法使用：%s", attempt, seed, exc)
        raise SummaryError(f"LLM 回傳格式錯誤：{last_error}")

    def _call_ollama(self, user_msg: str, seed: int, prompt: str | None = None) -> dict:
        payload: dict = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": prompt or system_prompt("zh")},
                {"role": "user", "content": user_msg},
            ],
            "format": "json",
            "stream": False,
            "options": {
                "temperature": config.LLM_TEMPERATURE,
                "seed": seed,
                "num_ctx": config.LLM_NUM_CTX,
            },
        }
        if config.LLM_THINK is not None:
            payload["think"] = config.LLM_THINK

        try:
            resp = httpx.post(
                f"{config.OLLAMA_HOST}/api/chat", json=payload, timeout=config.LLM_TIMEOUT_SECONDS
            )
        except httpx.HTTPError as exc:
            raise RuntimeError(f"無法連線到 Ollama（{config.OLLAMA_HOST}）：{exc}") from exc
        if resp.status_code != 200:
            raise RuntimeError(f"Ollama 回應 {resp.status_code}：{resp.text[:300]}")

        body = resp.json()
        msg = body.get("message") or {}
        content = msg.get("content") or ""
        thinking = msg.get("thinking") or ""
        m = re.search(r"<think>(.*?)</think>", content, flags=re.S)
        if m:
            thinking = thinking or m.group(1)
            content = content[: m.start()] + content[m.end():]
        _log_stats(body, thinking, seed)

        if body.get("done_reason") == "length":
            raise SummaryError(
                f"輸出超過長度上限被截斷（上下文 {config.LLM_NUM_CTX}），可調大 .env 的 LLM_NUM_CTX"
            )
        try:
            data = json.loads(_strip_fences(content))
        except ValueError as exc:
            raise SummaryError(f"不是合法 JSON（前 200 字：{content[:200]!r}）") from exc
        if not isinstance(data, dict):
            raise SummaryError("回傳的 JSON 不是物件")
        return data


def _log_stats(body: dict, thinking: str, seed: int) -> None:
    prompt_tok = body.get("prompt_eval_count") or 0
    out_tok = body.get("eval_count") or 0
    secs = (body.get("total_duration") or 0) / 1e9
    log.info(
        "LLM 完成：seed=%d 溫度=%s 思考=%s（草稿 %d 字）輸入 %d tokens＋輸出 %d tokens"
        "（上限 %d）耗時 %.0f 秒 結束原因=%s",
        seed, config.LLM_TEMPERATURE, "有" if thinking else "無", len(thinking),
        prompt_tok, out_tok, config.LLM_NUM_CTX, secs, body.get("done_reason"),
    )
    if prompt_tok + out_tok > config.LLM_NUM_CTX * 0.9:
        log.warning("LLM 用量已接近上下文上限（%d / %d），長會議可能被截斷，建議調大 LLM_NUM_CTX",
                    prompt_tok + out_tok, config.LLM_NUM_CTX)


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    return text


def _as_list(v) -> list:
    return v if isinstance(v, list) else []


def _str_or_none(v):
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _ref_date(meeting: dict | None) -> date | None:
    d = (meeting or {}).get("date")
    if isinstance(d, date):
        return d
    try:
        return date.fromisoformat(str(d)) if d else None
    except ValueError:
        return None


def _clean_assignee(name) -> str:
    s = re.sub(r"[（(][^）)]*[）)]", "", str(name)).strip()
    return s or str(name).strip()


def normalize(raw: dict, transcript: dict, meeting: dict | None = None) -> dict:
    mc = raw.get("meeting_content") if isinstance(raw.get("meeting_content"), dict) else raw
    review_notes = [
        {"field": _str_or_none(n.get("field")), "reason": _str_or_none(n.get("reason"))}
        for n in _as_list(raw.get("review_notes"))
        if isinstance(n, dict)
    ]
    n_llm_notes = len(review_notes)
    seg_text = {s["segment_id"]: s["text"] for s in transcript.get("segments", [])}
    seg_order = {sid: i for i, sid in enumerate(seg_text)}
    ref = _ref_date(meeting)

    def locate(e) -> str | None:
        if not isinstance(e, dict):
            return None
        sid, quote = _str_or_none(e.get("segment_id")), _str_or_none(e.get("quote"))
        if not quote:
            return None
        if sid in seg_text and _squash(quote) in _squash(seg_text[sid]):
            return sid
        return next((k for k, t in seg_text.items() if _squash(quote) in _squash(t)), None)

    def first_pos(item: dict) -> tuple[int, int]:
        pos = [seg_order[s] for s in map(locate, _as_list(item.get("evidence"))) if s in seg_order]
        end = len(seg_order)
        return (pos[0], min(pos)) if pos else (end, end)

    def clean_evidence(items, owner_id: str) -> list:
        out = []
        for e in _as_list(items):
            if not isinstance(e, dict):
                continue
            sid, quote = _str_or_none(e.get("segment_id")), _str_or_none(e.get("quote"))
            if not quote:
                continue
            if sid not in seg_text or _squash(quote) not in _squash(seg_text[sid]):
                found = next((k for k, t in seg_text.items() if _squash(quote) in _squash(t)), None)
                if found is None:
                    review_notes.append(
                        {"field": owner_id, "reason": f"引文無法在逐字稿中找到，已移除：「{quote[:40]}」"}
                    )
                    continue
                sid = found
            out.append({"segment_id": sid, "quote": quote})
        return out

    result: dict = {}
    id_maps: dict[str, str] = {}
    for field in LIST_FIELDS:
        items = []
        raw_items = [x for x in _as_list(mc.get(field)) if isinstance(x, dict)]
        raw_items.sort(key=first_pos)
        for i, item in enumerate(raw_items, 1):
            new_id = f"{ID_PREFIX[field]}{i:03d}"
            if item.get("id"):
                id_maps[str(item["id"])] = new_id
            items.append((new_id, item))
        result[field] = items

    def remap(ids) -> list:
        return [id_maps[str(x)] for x in _as_list(ids) if str(x) in id_maps]

    out_mc: dict = {field: [] for field in LIST_FIELDS}
    for new_id, item in result["reports"]:
        out_mc["reports"].append({
            "id": new_id,
            "topic": _str_or_none(item.get("topic")),
            "summary": _str_or_none(item.get("summary")),
            "evidence": clean_evidence(item.get("evidence"), new_id),
        })
    for new_id, item in result["discussions"]:
        out_mc["discussions"].append({
            "id": new_id,
            "topic": _str_or_none(item.get("topic")),
            "summary": _str_or_none(item.get("summary")),
            "key_points": [str(k) for k in _as_list(item.get("key_points")) if str(k).strip()],
            "evidence": clean_evidence(item.get("evidence"), new_id),
        })
    for new_id, item in result["decisions"]:
        out_mc["decisions"].append({
            "id": new_id,
            "summary": _str_or_none(item.get("summary")),
            "related_ids": remap(item.get("related_ids")),
            "evidence": clean_evidence(item.get("evidence"), new_id),
        })
    for new_id, item in result["action_items"]:
        due_text = _str_or_none(item.get("due_text"))
        llm_due = _str_or_none(item.get("due_date"))
        code_due = parse_due(due_text, ref)
        if code_due:
            due = code_due.isoformat()
        elif llm_due and _DATE_RE.match(llm_due):
            due = llm_due
            review_notes.append({"field": new_id,
                                 "reason": f"期限 {llm_due} 由模型推算（原文：{due_text or '未提供'}），請確認"})
        else:
            due = None
            if llm_due:
                review_notes.append({"field": new_id, "reason": f"期限格式無法辨識：{llm_due}"})
        assignees = []
        for a in _as_list(item.get("assignees")):
            name = _clean_assignee(a) if str(a).strip() else ""
            if name and name not in assignees:
                assignees.append(name)
        out_mc["action_items"].append({
            "id": new_id,
            "task": _str_or_none(item.get("task")),
            "assignees": assignees,
            "due_date": due,
            "due_text": due_text,
            "related_ids": remap(item.get("related_ids")),
            "evidence": clean_evidence(item.get("evidence"), new_id),
        })
    for field in LIST_FIELDS:
        for item in out_mc[field]:
            if not item["evidence"]:
                review_notes.append({"field": item["id"], "reason": "沒有可核對的原文依據，請人工確認"})

    nm = mc.get("next_meeting") if isinstance(mc.get("next_meeting"), dict) else {}
    nm_date_text = _str_or_none(nm.get("date_text"))
    nm_time = _str_or_none(nm.get("time"))
    code_nm = parse_due(nm_date_text, ref)
    llm_nm = _str_or_none(nm.get("date"))
    if code_nm:
        nm_date = code_nm.isoformat()
    elif llm_nm and _DATE_RE.match(llm_nm):
        nm_date = llm_nm
        review_notes.append({"field": "next_meeting.date",
                             "reason": f"下次會議日期 {llm_nm} 由模型推算（原文：{nm_date_text or '未提供'}），請確認"})
    else:
        nm_date = None
        if nm_date_text:
            review_notes.append({"field": "next_meeting.date",
                                 "reason": f"下次會議時間「{nm_date_text}」無法換算成確切日期，請確認"})
    if nm_time and not _TIME_RE.match(nm_time):
        review_notes.append({"field": "next_meeting.time", "reason": f"時間格式無法辨識：{nm_time}"})
        nm_time = None
    status = nm.get("status")
    if status not in NEXT_MEETING_STATUSES:
        status = "tentative" if (nm_date or nm_time or nm_date_text) else "not_mentioned"
    out_mc["next_meeting"] = {
        "date": nm_date,
        "date_text": nm_date_text,
        "time": nm_time,
        "status": status,
        "evidence": clean_evidence(nm.get("evidence"), "next_meeting"),
    }

    headline = _str_or_none(raw.get("headline")) or _str_or_none(mc.get("headline"))
    if headline and len(headline) > HEADLINE_MAX:
        headline = headline[: HEADLINE_MAX - 1] + "…"
    if not headline:
        review_notes.append({"field": "headline", "reason": "LLM 沒有產生一句話總結"})

    id_re = re.compile(r"\b(?:DEC|R|D|A)\d{3}\b")

    def renumber(text):
        if not text:
            return text
        return id_re.sub(lambda m: id_maps.get(m.group(0), m.group(0)), text)

    for note in review_notes[:n_llm_notes]:
        note["field"] = renumber(note["field"])
        note["reason"] = renumber(note["reason"])

    return {"headline": headline, "meeting_content": out_mc, "review_notes": review_notes}


def _squash(s: str) -> str:
    return re.sub(r"[\s，。、！？,.!?「」『』：:；;…]", "", s)


def _fake_summary(transcript: dict, language: str = "zh") -> dict:
    segs = transcript["segments"]
    first, last = segs[0], segs[-1]
    if language == "en":
        return {
            "headline": "(Fake data) Decided to finish the upload feature first; meet again next Wednesday.",
            "meeting_content": {
                "reports": [{
                    "id": "R001", "topic": "(Fake) Opening",
                    "summary": f"Test summary produced by LLM_BACKEND=fake from {len(segs)} transcript segments.",
                    "evidence": [{"segment_id": first["segment_id"], "quote": first["text"][:30]}],
                }],
                "discussions": [],
                "decisions": [{
                    "id": "DEC001", "summary": "(Fake) The last segment shown as a decision.", "related_ids": [],
                    "evidence": [{"segment_id": last["segment_id"], "quote": last["text"][:30]}],
                }],
                "action_items": [],
                "next_meeting": {"date": None, "time": None, "status": "not_mentioned", "evidence": []},
            },
            "review_notes": [],
        }
    return {
        "headline": "（假資料）決定先完成上傳功能，下週三再開會確認進度。",
        "meeting_content": {
            "reports": [{
                "id": "R001", "topic": "（假資料）會議開頭",
                "summary": f"這是 LLM_BACKEND=fake 產生的測試摘要，共 {len(segs)} 段逐字稿。",
                "evidence": [{"segment_id": first["segment_id"], "quote": first["text"][:30]}],
            }],
            "discussions": [],
            "decisions": [{
                "id": "DEC001", "summary": "（假資料）以最後一段作為決議示意。", "related_ids": [],
                "evidence": [{"segment_id": last["segment_id"], "quote": last["text"][:30]}],
            }],
            "action_items": [],
            "next_meeting": {"date": None, "time": None, "status": "not_mentioned", "evidence": []},
        },
        "review_notes": [],
    }


_service: SummarizerService | None = None


def get_summarizer_service() -> SummarizerService:
    global _service
    if _service is None:
        _service = SummarizerService()
    return _service
