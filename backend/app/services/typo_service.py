from __future__ import annotations

import logging
import re

import httpx

from app import config
from app.services.language import transcript_language

log = logging.getLogger(__name__)

MAX_WRONG_LEN = 12
MAX_CHANGED = 3

TYPO_SYSTEM_PROMPT = """你是會議逐字稿的校對助手。逐字稿由語音辨識產生，內容是國語或台語混講，常有同音或近音的錯別字。
你的工作是找出「用錯的字」，讓人工確認。你不能修改逐字稿，只列出建議。

【要找的】
同音或近音字用錯，造成意思不通的字。例如：「效律」應為「效率」、「即然」應為「既然」。

【不要列出的】
1. 口語、語助詞、贅字（例如：啦、喔、齁、嘛、就是說）。
2. 台語用字或台語語法（例如：按呢、毋、袂、閣、佇、啥物）。
3. 標點、斷句、句子是否通順、用詞好不好。
4. 人名、公司名、產品名等專有名詞（除非同一個名稱在逐字稿其他地方有不同寫法）。
5. 「的／得／地」「做／作」「部分／部份」這類兩種寫法都常見的字。
6. 不確定的不要列。寧可少列，不要亂列。
7. 開頭標 [context] 的是前文，只用來理解上下文，不要對它們列建議。
（判斷時請參考前後幾段的內容：同一個詞在上下文中怎麼用、這段話在講什麼，再決定是不是錯字。）

【輸出格式】每一處一行，不要輸出其他任何文字：
段落編號|原文片段|改正後片段
- 原文片段：照抄原文中的錯字，加上前後各一個字（共 2～6 個字），必須能在該段原文中找到。
- 改正後片段：把錯字改正後的同一個片段，字數必須和原文片段相同。
- 同一段有好幾處就分成好幾行。
- 這一批都沒有錯字，只輸出：無

範例：
S0003|工作效律很|工作效率很
S0010|即然大家|既然大家"""

TYPO_SYSTEM_PROMPT_EN = """You proofread an English meeting transcript produced by speech recognition (ASR).
ASR often writes a word that SOUNDS similar but is wrong, so the sentence no longer makes sense in context.
Your job: use the surrounding sentences to find those misrecognized words and suggest the intended words, for a human to confirm.
You cannot edit the transcript; only list suggestions.

[What to list]
Words that were misheard, judged from context. Examples:
- the meeting is about universal remotes, but a line says "university remote" → "universal remote"
- "closing grantal of twenty five minutes" → "closing grand total of twenty five minutes"
- "so fortunately we've got about five minutes" when the speaker is clearly complaining about little time → "so unfortunately"

[Do NOT list]
1. Fillers, hesitations, repeated words, unfinished words (um, uh, like, you know, I I think).
2. Informal spoken grammar, contractions, capitalization, punctuation, sentence style.
3. Names of people, companies, products (unless the same name is spelled differently elsewhere in the transcript).
4. British vs American spelling (fulfil / fulfill), tense or plural differences that do not change the meaning.
5. Anything you are not sure about. Listing fewer is better than listing wrong ones.
6. Lines marked [context] — they are only for understanding; do not list suggestions for them.

[Output format] One suggestion per line, no other text:
SEGMENT_ID|original phrase|corrected phrase
- original phrase: copy EXACTLY from that segment: the wrong word(s) plus one word before and after (2–8 words).
- corrected phrase: the same phrase with only the wrong word(s) fixed (at most 3 words changed).
- If nothing in this batch needs fixing, output only: NONE

Example:
S0018|a university remote|a universal remote
S0011|closing grantal of|closing grand total of"""

_LINE_RE = re.compile(r"^\s*\[?(S\d{4})\]?\s*[|｜]\s*(.+?)\s*[|｜]\s*(.+?)\s*$")


def _changed(a: str, b: str) -> int:
    return sum(1 for x, y in zip(a, b) if x != y)


def glossary_prompt(glossary: list[str], language: str = "zh") -> str:
    if language == "en":
        if not glossary:
            return TYPO_SYSTEM_PROMPT_EN
        return TYPO_SYSTEM_PROMPT_EN + f"""

[User's glossary] Correct spellings of terms this user often uses:
{", ".join(glossary)}
1. If a word in the transcript sounds like one of these terms but is written differently, suggest the glossary spelling.
2. Do not change words that are already written as in the glossary."""
    if not glossary:
        return TYPO_SYSTEM_PROMPT
    return TYPO_SYSTEM_PROMPT + f"""

【使用者的專有名詞詞彙庫】以下是這位使用者常用詞彙的正確寫法：
{"、".join(glossary)}
1. 逐字稿中發音相近、但寫錯的詞，請建議改成詞彙庫的寫法（這種情況改正後片段的字數可以和原文不同）。
2. 已經是詞彙庫寫法的詞，不要修改。"""


def _hits_glossary(sugg: str, wrong: str, glossary: list[str]) -> bool:
    return any(g in sugg and g not in wrong for g in glossary)


def parse_reply(text: str, seg_text: dict[str, str], glossary: list[str] | None = None) -> list[dict]:
    glossary = glossary or []
    out = []
    for line in (text or "").splitlines():
        m = _LINE_RE.match(line)
        if not m:
            continue
        sid, wrong, sugg = m.group(1), m.group(2), m.group(3)
        src = seg_text.get(sid)
        if src is None or not wrong or wrong == sugg:
            continue
        to_term = _hits_glossary(sugg, wrong, glossary)
        if to_term:
            if len(wrong) > MAX_WRONG_LEN + 10 or len(sugg) > MAX_WRONG_LEN + 30:
                continue
        else:
            if len(wrong) > MAX_WRONG_LEN or len(wrong) != len(sugg):
                continue
            n = _changed(wrong, sugg)
            if not 1 <= n <= MAX_CHANGED:
                continue
        offset = src.find(wrong)
        if offset < 0:
            continue
        out.append({"segment_id": sid, "wrong": wrong, "suggestion": sugg, "offset": offset})
    return out


MAX_WRONG_WORDS = 10
MAX_CHANGED_WORDS = 3
_WORD = re.compile(r"\S+")


def _words_changed(a: str, b: str) -> int:
    import difflib

    wa, wb = a.lower().split(), b.lower().split()
    n = 0
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, wa, wb, autojunk=False).get_opcodes():
        if op != "equal":
            n += max(i2 - i1, j2 - j1)
    return n


def _find_ci(src: str, phrase: str) -> int:
    i = src.find(phrase)
    if i >= 0:
        return i
    pat = r"\s+".join(re.escape(w) for w in phrase.split())
    m = re.search(pat, src, flags=re.I) if pat else None
    return m.start() if m else -1


def parse_reply_en(text: str, seg_text: dict[str, str], glossary: list[str] | None = None,
                   context_ids: set[str] | None = None) -> list[dict]:
    glossary = glossary or []
    context_ids = context_ids or set()
    out = []
    for line in (text or "").splitlines():
        m = _LINE_RE.match(line)
        if not m:
            continue
        sid, wrong, sugg = m.group(1), m.group(2).strip(), m.group(3).strip()
        src = seg_text.get(sid)
        if src is None or sid in context_ids or not wrong or wrong.lower() == sugg.lower():
            continue
        if len(wrong.split()) > MAX_WRONG_WORDS or len(sugg.split()) > MAX_WRONG_WORDS + MAX_CHANGED_WORDS:
            continue
        if not _hits_glossary(sugg, wrong, glossary):
            n = _words_changed(wrong, sugg)
            if not 1 <= n <= MAX_CHANGED_WORDS:
                continue
        offset = _find_ci(src, wrong)
        if offset < 0:
            continue
        end = offset + len(re.match(r"\s*".join(re.escape(w) for w in wrong.split()), src[offset:], flags=re.I).group(0))
        out.append({"segment_id": sid, "wrong": src[offset:end], "suggestion": sugg, "offset": offset})
    return out


def _core(w: str, s: str) -> tuple[int, int, int]:
    head = 0
    while head < min(len(w), len(s)) and w[head] == s[head]:
        head += 1
    tail = 0
    while tail < min(len(w), len(s)) - head and w[-1 - tail] == s[-1 - tail]:
        tail += 1
    return head, len(w) - tail, len(s) - tail


def merge(items: list[dict], seg_order: dict[str, int]) -> list[dict]:
    seen, out = set(), []
    for it in sorted(items, key=lambda x: (seg_order.get(x["segment_id"], 1 << 30), x["offset"])):
        head, wend, _ = _core(it["wrong"], it["suggestion"])
        span = range(it["offset"] + head, it["offset"] + max(wend, head + 1))
        positions = {(it["segment_id"], p) for p in span}
        if positions & seen:
            continue
        seen |= positions
        out.append(it)
    return out


FAKE_PAIRS = [("效律", "效率"), ("即然", "既然"), ("負則", "負責"), ("因該", "應該"),
              ("以經", "已經"), ("在確認", "再確認")]
FAKE_PAIRS_EN = [("university remote", "universal remote"), ("grantal", "grand total"),
                 ("so fortunately", "so unfortunately")]


def fake_check(segs: list[dict], glossary: list[str] | None = None, language: str = "zh") -> list[dict]:
    pairs = list(FAKE_PAIRS_EN if language == "en" else FAKE_PAIRS)
    for g in glossary or []:
        if len(g) >= 3:
            pairs.append((g[:-1] + "的", g))
    out = []
    for s in segs:
        for wrong, sugg in pairs:
            start = 0
            while (i := s["text"].find(wrong, start)) >= 0:
                out.append({"segment_id": s["segment_id"], "wrong": wrong, "suggestion": sugg, "offset": i})
                start = i + len(wrong)
    return out


def _is_latin(text: str) -> bool:
    return bool(re.search(r"[A-Za-z]", text)) and not re.search(r"[\u3400-\u9fff]", text)


def _trim(it: dict) -> dict:
    w, s = it["wrong"], it["suggestion"]
    if _is_latin(w):
        return _trim_words(it)
    head, wend, send = _core(w, s)
    if wend <= head:
        head = max(0, head - 1)
    return {**it, "wrong": w[head:wend], "suggestion": s[head:send], "offset": it["offset"] + head}


def _trim_words(it: dict) -> dict:
    w, s = it["wrong"], it["suggestion"]
    ww = [(m.start(), m.end(), m.group(0).lower()) for m in _WORD.finditer(w)]
    sw = [(m.start(), m.end(), m.group(0).lower()) for m in _WORD.finditer(s)]
    if not ww:
        return it
    head = 0
    while head < min(len(ww), len(sw)) and ww[head][2] == sw[head][2]:
        head += 1
    tail = 0
    while tail < min(len(ww), len(sw)) - head and ww[-1 - tail][2] == sw[-1 - tail][2]:
        tail += 1
    w_end, s_end = len(ww) - tail, len(sw) - tail
    if w_end <= head or s_end <= head:
        if head > 0:
            head -= 1
        else:
            w_end, s_end = w_end + 1, s_end + 1
    w_end, s_end = min(w_end, len(ww)), min(s_end, len(sw))
    wrong = w[ww[head][0]:ww[w_end - 1][1]]
    sugg = s[sw[head][0]:sw[s_end - 1][1]] if s_end > head else ""
    return {**it, "wrong": wrong, "suggestion": sugg, "offset": it["offset"] + ww[head][0]}


def protect_glossary(items: list[dict], seg_text: dict[str, str], glossary: list[str]) -> list[dict]:
    if not glossary:
        return items
    out = []
    for it in items:
        text = seg_text.get(it["segment_id"], "")
        head, wend, _ = _core(it["wrong"], it["suggestion"])
        a, b = it["offset"] + head, it["offset"] + max(wend, head + 1)
        hit = False
        for g in glossary:
            start = 0
            while (i := text.find(g, start)) >= 0:
                if i < b and a < i + len(g):
                    hit = True
                    break
                start = i + 1
            if hit:
                break
        if not hit:
            out.append(it)
    return out


def finalize(items: list[dict]) -> list[dict]:
    return [{"id": f"T{i + 1:03d}", **_trim(it), "status": "pending"} for i, it in enumerate(items)]


CONTEXT_SEGMENTS = 3


class TypoChecker:
    def __init__(self) -> None:
        self.backend = config.LLM_BACKEND
        self.last_language = "zh"

    def check(self, transcript: dict, glossary: list[str] | None = None) -> tuple[list[dict], list[str]]:
        glossary = [g for g in (glossary or []) if g]
        segs = [s for s in transcript.get("segments", []) if (s.get("text") or "").strip()]
        seg_text = {s["segment_id"]: s["text"] for s in segs}
        seg_order = {s["segment_id"]: i for i, s in enumerate(segs)}
        lang = transcript_language(transcript)
        self.last_language = lang
        if not segs:
            return [], []
        if self.backend == "fake":
            items = protect_glossary(fake_check(segs, glossary, lang), seg_text, glossary)
            return finalize(merge(items, seg_order)), []

        found, problems = [], []
        size = max(1, config.TYPO_CHUNK)
        prompt = glossary_prompt(glossary, lang)
        for start in range(0, len(segs), size):
            batch = segs[start:start + size]
            context = segs[max(0, start - CONTEXT_SEGMENTS):start]
            user_msg = "\n".join(
                [f"[context] {s['text']}" for s in context]
                + [f"[{s['segment_id']}] {s['text']}" for s in batch]
            )
            try:
                reply = self._call(user_msg, prompt)
            except Exception as exc:
                rng = f"{batch[0]['segment_id']}–{batch[-1]['segment_id']}"
                log.warning("錯字檢查 %s 失敗：%s", rng, exc)
                problems.append(f"{rng} 的錯字檢查失敗，這一段沒有檢查到")
                continue
            if lang == "en":
                batch_text = {s["segment_id"]: s["text"] for s in batch}
                found += parse_reply_en(reply, batch_text, glossary)
            else:
                found += parse_reply(reply, seg_text, glossary)
        found = protect_glossary(found, seg_text, glossary)
        result = finalize(merge(found, seg_order))
        log.info("錯字檢查完成（%s）：%d 段，找到 %d 處疑似錯字", "英文" if lang == "en" else "中文",
                 len(segs), len(result))
        return result, problems

    def _call(self, user_msg: str, system_prompt: str = TYPO_SYSTEM_PROMPT) -> str:
        payload: dict = {
            "model": config.LLM_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ],
            "stream": False,
            "think": config.TYPO_THINK,
            "options": {
                "temperature": config.LLM_TEMPERATURE,
                "seed": config.LLM_SEED,
                "num_ctx": config.LLM_NUM_CTX,
            },
        }
        resp = httpx.post(f"{config.OLLAMA_HOST}/api/chat", json=payload, timeout=config.LLM_TIMEOUT_SECONDS)
        if resp.status_code != 200:
            raise RuntimeError(f"Ollama 回應 {resp.status_code}：{resp.text[:200]}")
        content = (resp.json().get("message") or {}).get("content") or ""
        return re.sub(r"<think>.*?</think>", "", content, flags=re.S)


def _seg_map(transcript: dict) -> dict[str, dict]:
    return {s["segment_id"]: s for s in transcript.get("segments", [])}


def _shift(suggestions: list[dict], seg_id: str, after: int, delta: int, skip: dict) -> None:
    if not delta:
        return
    for t in suggestions:
        if t is not skip and t["segment_id"] == seg_id and t["offset"] > after:
            t["offset"] += delta


def _replace(seg: dict, offset: int, old: str, new: str) -> bool:
    text = seg["text"]
    if text[offset:offset + len(old)] != old:
        return False
    seg.setdefault("original_text", text)
    seg["text"] = text[:offset] + new + text[offset + len(old):]
    if seg["text"] == seg["original_text"]:
        seg.pop("original_text")
    return True


def apply_decision(transcript: dict, suggestions: list[dict], ids: list[str] | None,
                   action: str, replacement: str | None = None) -> list[str]:
    if action not in ("accept", "ignore", "undo"):
        raise ValueError(f"不支援的動作：{action}")
    segs = _seg_map(transcript)
    if ids is None:
        targets = [t for t in suggestions if t["status"] == "pending"]
    else:
        wanted = set(ids)
        targets = [t for t in suggestions if t["id"] in wanted]
    if replacement is not None and (action != "accept" or len(targets) != 1):
        raise ValueError("自己輸入改法時，一次只能處理一處")

    done = []
    for t in targets:
        seg = segs.get(t["segment_id"])
        if seg is None:
            continue
        if action == "accept" and t["status"] == "pending":
            new = t["suggestion"] if replacement is None else replacement
            if not _replace(seg, t["offset"], t["wrong"], new):
                t["status"] = "outdated"
                continue
            _shift(suggestions, t["segment_id"], t["offset"], len(new) - len(t["wrong"]), t)
            t["applied"] = new
            t["status"] = "accepted" if new == t["suggestion"] else "edited"
        elif action == "ignore" and t["status"] == "pending":
            t["status"] = "ignored"
        elif action == "undo" and t["status"] in ("accepted", "edited"):
            applied = t.get("applied", t["suggestion"])
            if not _replace(seg, t["offset"], applied, t["wrong"]):
                continue
            _shift(suggestions, t["segment_id"], t["offset"], len(t["wrong"]) - len(applied), t)
            t.pop("applied", None)
            t["status"] = "pending"
        elif action == "undo" and t["status"] == "ignored":
            t["status"] = "pending"
        else:
            continue
        done.append(t["id"])
    return done


def edit_segment(transcript: dict, suggestions: list[dict], segment_id: str, new_text: str) -> None:
    seg = _seg_map(transcript).get(segment_id)
    if seg is None:
        raise KeyError(segment_id)
    new_text = new_text.strip()
    if not new_text:
        raise ValueError("段落內容不能是空的")
    seg.setdefault("original_text", seg["text"])
    seg["text"] = new_text
    if seg["text"] == seg["original_text"]:
        seg.pop("original_text")
    for t in suggestions:
        if t["segment_id"] != segment_id:
            continue
        look = t["wrong"] if t["status"] == "pending" else t.get("applied", t["suggestion"])
        if t["status"] in ("pending", "accepted", "edited"):
            i = new_text.find(look)
            if i >= 0:
                t["offset"] = i
            elif t["status"] == "pending":
                t["status"] = "outdated"


def replace_text(transcript: dict, suggestions: list[dict], find: str, replace: str,
                 segment_id: str | None = None, offset: int | None = None) -> int:
    if not find or find == replace:
        raise ValueError("要修改的文字不能是空的，也不能和改後一樣")
    if len(replace) > 200:
        raise ValueError("改後的文字太長")
    segs = _seg_map(transcript)
    if segment_id is not None:
        seg = segs.get(segment_id)
        if seg is None:
            raise KeyError(segment_id)
        if offset is None or seg["text"][offset:offset + len(find)] != find:
            raise ValueError("找不到要修改的文字，請重新選取")
        _replace_one(seg, suggestions, offset, find, replace)
        return 1
    n = 0
    for seg in transcript.get("segments", []):
        start = 0
        while (i := seg["text"].find(find, start)) >= 0:
            _replace_one(seg, suggestions, i, find, replace)
            n += 1
            start = i + len(replace)
    return n


def _replace_one(seg: dict, suggestions: list[dict], offset: int, find: str, replace: str) -> None:
    _replace(seg, offset, find, replace)
    end = offset + len(find)
    for t in suggestions:
        if t["segment_id"] != seg["segment_id"]:
            continue
        shown = t["wrong"] if t["status"] == "pending" else t.get("applied", t["suggestion"])
        t_end = t["offset"] + len(shown)
        if t["offset"] >= end:
            t["offset"] += len(replace) - len(find)
        elif t_end > offset and t["status"] == "pending":
            t["status"] = "outdated"


def record_manual(proofread: dict, find: str, replace: str, n: int) -> None:
    manual = proofread.setdefault("manual", [])
    for m in manual:
        if m["find"] == find and m["replace"] == replace:
            m["count"] += n
            return
    manual.append({"find": find, "replace": replace, "count": n})


def counts(suggestions: list[dict]) -> dict:
    out = {k: 0 for k in ("pending", "accepted", "edited", "ignored", "outdated")}
    for t in suggestions:
        out[t["status"]] = out.get(t["status"], 0) + 1
    out["total"] = len(suggestions)
    return out


_checker: TypoChecker | None = None


def get_typo_checker() -> TypoChecker:
    global _checker
    if _checker is None:
        _checker = TypoChecker()
    return _checker
