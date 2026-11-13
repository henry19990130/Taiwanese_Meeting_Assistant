"""錯字校正微調：共用工具（正規化、對齊、標註、組 prompt、評分）。

標準答案一律來自「人工逐字稿 vs 專案 ASR 辨識結果」的差異，或程式規則注入的同音字，
不使用任何大型語言模型產生的答案。
"""
from __future__ import annotations

import difflib
import os
import random
import re
import sys
from functools import lru_cache
from pathlib import Path

# ---------------------------------------------------------------- 專案程式（prompt、解析器都用正式版本）

def project_backend() -> Path:
    env = os.environ.get("PROJECT_BACKEND")
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    for p in [here.parents[2] / "backend", Path("/content/Taiwanese_Meeting_Assistant/backend")]:
        if (p / "app" / "services" / "typo_service.py").exists():
            return p
    raise RuntimeError("找不到專案 backend，請設定環境變數 PROJECT_BACKEND")


def typo_service():
    b = str(project_backend())
    if b not in sys.path:
        sys.path.insert(0, b)
    from app.services import typo_service as ts  # noqa: E402
    return ts


CHUNK = 40          # 與正式設定 TYPO_CHUNK 相同
CONTEXT = 3         # 與 typo_service.CONTEXT_SEGMENTS 相同


def system_prompt(lang: str) -> str:
    ts = typo_service()
    return ts.TYPO_SYSTEM_PROMPT_EN if lang == "en" else ts.TYPO_SYSTEM_PROMPT


def user_message(segs: list[dict], start: int, end: int) -> str:
    """和 TypoChecker.check 組出來的 user 訊息一模一樣。segs 每項要有 segment_id、text。"""
    ctx = segs[max(0, start - CONTEXT):start]
    batch = segs[start:end]
    return "\n".join([f"[context] {s['text']}" for s in ctx] + [f"[{s['segment_id']}] {s['text']}" for s in batch])


def none_word(lang: str) -> str:
    return "NONE" if lang == "en" else "無"


def target_text(edits: list[dict], lang: str) -> str:
    if not edits:
        return none_word(lang)
    edits = sorted(edits, key=lambda e: (e["segment_id"], e["offset"]))
    return "\n".join(f"{e['segment_id']}|{e['wrong']}|{e['suggestion']}" for e in edits)


# ---------------------------------------------------------------- 中文

_OCC = None


def s2tw(text: str) -> str:
    global _OCC
    if _OCC is None:
        from opencc import OpenCC
        try:
            _OCC = OpenCC("s2tw")
        except Exception:
            _OCC = OpenCC("s2tw.json")
    return _OCC.convert(text)


_ZH_MARK = re.compile(r"<[^>]*>|\[[^\]]*\]")
_ZH_SKIP = re.compile(r"[\s　，。、！？；：「」『』（）《》〈〉…—～·,.!?;:'\"()\[\]\-~]")


def clean_zh_ref(text: str) -> str:
    """AISHELL-4 參考答案：拿掉 <%> 之類的標記，簡轉繁（與專案 ASR 後處理相同的 s2tw）。"""
    return s2tw(_ZH_MARK.sub("", text or "")).strip()


def zh_chars(text: str) -> list[tuple[str, int]]:
    """去掉標點空白後的 (字, 在原字串的位置)。"""
    return [(c, i) for i, c in enumerate(text) if not _ZH_SKIP.match(c)]


# 同一個讀音、但從語音無法分辨或兩種寫法都對的字 → 不列為錯字
_ZH_EQUIV = [set(s) for s in ["他她它祂牠", "的得地", "做作", "分份", "那哪", "嗎嘛麼", "啊阿呀哇", "欸誒", "喔哦噢", "吧罷",
                               "裡裏里", "台臺", "著着", "妳你", "週周", "於于", "佔占", "畫劃", "麵面", "髮發", "鐘鍾", "嚐嘗", "甚什", "檯臺台", "坐座", "夥伙", "佈布", "祇只", "姊姐", "羣群", "汙污", "痴癡", "祕秘", "牆墻", "啟啓", "峰峯", "湧涌", "線綫", "叫呌", "吃喫", "睏困", "鬥斗", "麼么", "兒而"]]
_ZH_FILLER = set("的了啊呀吧嗎呢喔哦欸嗯呃哎唉噢啦嘛耶呵哈么麼")
_INIT_NEAR = [{"zh", "z"}, {"ch", "c"}, {"sh", "s"}, {"n", "l"}, {"f", "h"}, {"r", "l"}]
_FINAL_NEAR = [{"an", "ang"}, {"en", "eng"}, {"in", "ing"}, {"ian", "iang"}, {"uan", "uang"}, {"on", "ong"}]


@lru_cache(maxsize=100000)
def _py(c: str) -> tuple[str, str, str]:
    from pypinyin import Style, pinyin
    full = pinyin(c, style=Style.NORMAL, heteronym=False)[0][0]
    ini = pinyin(c, style=Style.INITIALS, strict=False)[0][0]
    fin = pinyin(c, style=Style.FINALS, strict=False)[0][0]
    return full, ini, fin


def zh_sound_alike(a: str, b: str) -> bool:
    if a == b or not ("一" <= a <= "鿿" and "一" <= b <= "鿿"):
        return False
    pa, ia, fa = _py(a)
    pb, ib, fb = _py(b)
    if pa == pb:
        return True
    if ia == ib and {fa, fb} in _FINAL_NEAR:
        return True
    if fa == fb and {ia, ib} in _INIT_NEAR:
        return True
    return False


def _zh_equiv(a: str, b: str) -> bool:
    return any(a in s and b in s for s in _ZH_EQUIV)


def _unique_span(text: str, lo: int, hi: int, max_len: int = 12) -> tuple[int, int] | None:
    """從 [lo, hi) 往兩邊各加一個字；如果在段落中不唯一就再往外擴，最多 max_len 字。"""
    lo2, hi2 = max(0, lo - 1), min(len(text), hi + 1)
    while True:
        if hi2 - lo2 > max_len:
            return None
        if text.find(text[lo2:hi2]) == lo2 and text.find(text[lo2:hi2], lo2 + 1) < 0:
            return lo2, hi2
        if lo2 == 0 and hi2 == len(text):
            return None
        lo2, hi2 = max(0, lo2 - 1), min(len(text), hi2 + 1)


def zh_edits(hyp: str, ref: str, segment_id: str) -> list[dict]:
    """找出 hyp 中「同音／近音、等長、1～3 字」的替換錯誤，輸出成正式格式的一行一行建議。"""
    hc, rc = zh_chars(hyp), zh_chars(ref)
    a, b = [c for c, _ in hc], [c for c, _ in rc]
    out = []
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op != "replace" or i2 - i1 != j2 - j1 or not 1 <= i2 - i1 <= 3:
            continue
        pairs = list(zip(a[i1:i2], b[j1:j2]))
        if any(x in _ZH_FILLER or y in _ZH_FILLER or _zh_equiv(x, y) or not zh_sound_alike(x, y) for x, y in pairs):
            continue
        pos = [hc[k][1] for k in range(i1, i2)]
        span = _unique_span(hyp, pos[0], pos[-1] + 1)
        if span is None:
            continue
        lo, hi = span
        fixed = list(hyp[lo:hi])
        for p, (_, y) in zip(pos, pairs):
            fixed[p - lo] = y
        out.append({"segment_id": segment_id, "wrong": hyp[lo:hi], "suggestion": "".join(fixed),
                    "offset": lo, "source": "asr"})
    return out


# ---------------------------------------------------------------- 英文

_EN_FILLER = {"um", "uh", "uhm", "hmm", "mm", "mm-hmm", "mmhmm", "uh-huh", "ah", "oh", "er", "erm", "eh", "huh", "yeah",
              "yep", "yes", "okay", "ok", "alright", "right", "so", "like", "well", "mhm", "hm", "nah", "no", "wow", "ooh"}
_EN_VARIANT = [{"gonna", "going"}, {"wanna", "want"}, {"gotta", "got"}, {"cause", "because"}, {"ok", "okay"},
               {"til", "until"}, {"em", "them"}, {"kinda", "kind"}, {"sorta", "sort"}, {"dunno", "know"}]
_EN_STOP = {"a", "an", "the", "and", "or", "but", "of", "to", "in", "on", "at", "for", "is", "are", "was", "were", "be",
            "it", "its", "it's", "this", "that", "i", "you", "we", "they", "he", "she", "do", "does", "did", "have",
            "has", "had", "with", "as", "if", "then", "than", "there", "their", "they're", "what", "which", "who",
            "not", "can", "will", "would", "could", "should", "just", "um", "uh"}
_EN_TOK = re.compile(r"[^a-z0-9']+")


def en_norm(tok: str) -> str:
    return _EN_TOK.sub("", tok.lower()).strip("'")


def _en_sound_alike(a: str, b: str) -> bool:
    import jellyfish
    if a == b:
        return False
    ma, mb = jellyfish.metaphone(a), jellyfish.metaphone(b)
    if not ma or not mb:
        return False
    return jellyfish.jaro_winkler_similarity(ma, mb) >= 0.75 and jellyfish.levenshtein_distance(a, b) <= max(len(a), len(b)) * 0.6


def _match_case(src: str, word: str) -> str:
    if src.isupper() and len(src) > 1:
        return word.upper()
    if src[:1].isupper():
        return word[:1].upper() + word[1:]
    return word


_BRIT = [("isation", "ization"), ("ise", "ize"), ("ised", "ized"), ("ising", "izing"), ("yse", "yze"), ("our", "or"),
         ("programme", "program"), ("synch", "sync"), ("tre", "ter"), ("ogue", "og"), ("ll", "l"), ("ss", "s")]


def _us(w: str) -> str:
    for a, b in _BRIT:
        w = w.replace(a, b)
    return w


def _stem(w: str) -> str:
    for suf in ("ing", "ed", "es", "s", "d"):
        if len(w) > 4 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def _en_not_a_typo(wa: list[str], wb: list[str], raw_changed: list[str]) -> bool:
    """這類差異從聲音分不出來、或兩種都對 → 不算錯字（和 prompt 的「不要列出」一致）。"""
    ja, jb = "".join(wa), "".join(wb)
    if ja.replace("'", "") == jb.replace("'", ""):                 # altogether / all together、online / on line
        return True
    if _us(ja) == _us(jb):                                          # 英式／美式拼法
        return True
    if any("'" in w for w in wa + wb):                              # 縮寫（nobody's / nobody is、there's / that's）
        return True
    if len(wa) == len(wb) and all(_stem(x) == _stem(y) or _us(_stem(x)) == _us(_stem(y)) for x, y in zip(wa, wb)):
        return True                                                 # 單複數、時態
    if any(len(w) == 1 for w in wa + wb):                           # 逐字母念的縮寫（p m、S P TWO）
        return True
    if any(t[:1].isupper() for t in raw_changed) and not raw_changed[0] == raw_changed[0].upper():
        return True                                                 # 句中大寫開頭 = 人名、專有名詞
    return False


@lru_cache(maxsize=50000)
def _in_dict(w: str) -> bool:
    try:
        import pronouncing
    except ImportError:          # Colab 上沒裝就自動裝（CMU 發音字典）
        import subprocess
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "pronouncing"], check=True)
        import pronouncing
    return bool(pronouncing.phones_for_word(w))


def _en_clean_single(wa: list[str], wb: list[str]) -> bool:
    """英文的人工逐字稿有截斷字、口誤，多詞差異也常常兩種都說得通。
    只收最乾淨的一種：一個字換一個字、兩個都是字典裡的真實單字、不是同一個字的變化形。"""
    if len(wa) != 1 or len(wb) != 1:
        return False
    a, b = wa[0], wb[0]
    if len(a) < 4 or len(b) < 4 or not (_in_dict(a) and _in_dict(b)):
        return False
    if a.startswith(b[:-1]) or b.startswith(a[:-1]) or (a.startswith(b) or b.startswith(a)):
        return False
    return True


def en_edits(hyp: str, ref: str, segment_id: str) -> list[dict]:
    raw = hyp.split()
    keep = [(en_norm(t), k) for k, t in enumerate(raw) if en_norm(t)]
    a = [w for w, _ in keep]
    b = [en_norm(t) for t in ref.split() if en_norm(t)]
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op != "replace" or not (1 <= i2 - i1 <= 3 and 1 <= j2 - j1 <= 3):
            continue
        wa, wb = a[i1:i2], b[j1:j2]
        allw = wa + wb
        if any(w in _EN_FILLER or w.endswith("-") or any(ch.isdigit() for ch in w) for w in allw):
            continue
        if any({x, y} in _EN_VARIANT for x in wa for y in wb):
            continue
        if all(w in _EN_STOP for w in allw):
            continue
        if not _en_sound_alike("".join(wa), "".join(wb)):
            continue
        rk = [keep[k][1] for k in range(i1, i2)]
        if _en_not_a_typo(wa, wb, raw[rk[0]:rk[-1] + 1]) or not _en_clean_single(wa, wb):
            continue
        lo_k, hi_k = max(0, rk[0] - 1), min(len(raw), rk[-1] + 2)
        if hi_k - lo_k > 8:
            continue
        before, after = raw[lo_k:rk[0]], raw[rk[-1] + 1:hi_k]
        changed = raw[rk[0]:rk[-1] + 1]
        lead = re.match(r"^\W*", changed[0]).group(0)
        trail = re.search(r"\W*$", changed[-1]).group(0)
        new = [_match_case(changed[min(n, len(changed) - 1)].strip(".,!?;:\"'"), w) for n, w in enumerate(wb)]
        new[0] = lead + new[0]
        new[-1] = new[-1] + trail
        wrong = " ".join(before + changed + after)
        sugg = " ".join(before + new + after)
        # 原文片段在段落中要能唯一找到
        offset = hyp.find(wrong)
        if offset < 0 or hyp.find(wrong, offset + 1) >= 0 or wrong.lower() == sugg.lower():
            continue
        out.append({"segment_id": segment_id, "wrong": wrong, "suggestion": sugg, "offset": offset, "source": "asr"})
    return out


def edits_for(lang: str, hyp: str, ref: str, segment_id: str) -> list[dict]:
    return en_edits(hyp, ref, segment_id) if lang == "en" else zh_edits(hyp, ref, segment_id)


# ---------------------------------------------------------------- 規則式同音字注入（擴充正例）

class ZhInjector:
    """用 jieba 詞典建立「同音詞」表，把句子中的詞換成另一個同音詞（例如 效率→校率 這類不存在就跳過）。"""

    def __init__(self, min_freq: int = 200):
        import jieba
        from pypinyin import Style, lazy_pinyin
        groups: dict[str, list[tuple[str, int]]] = {}
        dict_path = Path(jieba.__file__).parent / "dict.txt"
        for line in dict_path.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) < 2:
                continue
            w, f = parts[0], int(parts[1])
            if not 2 <= len(w) <= 3 or f < min_freq or not all("一" <= c <= "鿿" for c in w):
                continue
            w = s2tw(w)
            key = " ".join(lazy_pinyin(w, style=Style.TONE3))
            groups.setdefault(key, []).append((w, f))
        self.alt: dict[str, list[str]] = {}
        for items in groups.values():
            words = sorted({w for w, _ in items})
            if len(words) < 2:
                continue
            for w in words:
                self.alt[w] = [x for x in words if x != w and sum(c1 != c2 for c1, c2 in zip(w, x)) <= 2
                               and not any(_zh_equiv(c1, c2) for c1, c2 in zip(w, x) if c1 != c2)]
        import jieba as _j
        self._cut = _j.lcut

    def inject(self, text: str, segment_id: str, rng: random.Random) -> tuple[str, dict] | None:
        words = self._cut(text)
        cands = [k for k, w in enumerate(words) if self.alt.get(w)]
        rng.shuffle(cands)
        for k in cands:
            new_w = rng.choice(self.alt[words[k]])
            lo = sum(len(w) for w in words[:k])
            new_text = text[:lo] + new_w + text[lo + len(words[k]):]
            pos = [lo + i for i, (c1, c2) in enumerate(zip(words[k], new_w)) if c1 != c2]
            span = _unique_span(new_text, pos[0], pos[-1] + 1)
            if span is None:
                continue
            s, e = span
            fixed = list(new_text[s:e])
            for p in pos:
                fixed[p - s] = text[p]
            return new_text, {"segment_id": segment_id, "wrong": new_text[s:e], "suggestion": "".join(fixed),
                              "offset": s, "source": "synthetic"}
        return None


class EnInjector:
    """用會議語料自己的詞彙，把一個實詞換成發音相近的另一個實詞（university ↔ universal 這一類）。"""

    def __init__(self, vocab_counts: dict[str, int], min_count: int = 5):
        import jellyfish
        words = [w for w, c in vocab_counts.items() if c >= min_count and len(w) >= 4 and w.isalpha()
                 and w not in _EN_STOP and w not in _EN_FILLER]
        by_code: dict[str, list[str]] = {}
        for w in words:
            by_code.setdefault(jellyfish.metaphone(w)[:4], []).append(w)
        self.alt: dict[str, list[str]] = {}
        for ws in by_code.values():
            for w in ws:
                alts = [x for x in ws if x != w and not x.startswith(w[:-1]) and not w.startswith(x[:-1])
                        and jellyfish.levenshtein_distance(w, x) <= 3 and _en_sound_alike(w, x)]
                if alts:
                    self.alt[w] = alts

    def inject(self, text: str, segment_id: str, rng: random.Random) -> tuple[str, dict] | None:
        raw = text.split()
        cands = [k for k, t in enumerate(raw) if self.alt.get(en_norm(t))]
        rng.shuffle(cands)
        for k in cands:
            old = raw[k]
            core = en_norm(old)
            new_core = _match_case(old.strip(".,!?;:\"'"), rng.choice(self.alt[core]))
            m = re.match(r"^(\W*)(.*?)(\W*)$", old)
            new_tok = m.group(1) + new_core + m.group(3)
            new_raw = raw[:k] + [new_tok] + raw[k + 1:]
            lo_k, hi_k = max(0, k - 1), min(len(raw), k + 2)
            wrong = " ".join(new_raw[lo_k:hi_k])
            sugg = " ".join(raw[lo_k:hi_k])
            new_text = " ".join(new_raw)
            off = new_text.find(wrong)
            if off < 0 or new_text.find(wrong, off + 1) >= 0:
                continue
            return new_text, {"segment_id": segment_id, "wrong": wrong, "suggestion": sugg, "offset": off,
                              "source": "synthetic"}
        return None


# ---------------------------------------------------------------- 評分

def _apply(text: str, offset: int, wrong: str, sugg: str) -> str:
    return text[:offset] + sugg + text[offset + len(wrong):]


def _norm_for_match(lang: str, text: str) -> str:
    if lang == "en":
        return " ".join(en_norm(t) for t in text.split() if en_norm(t))
    return "".join(c for c, _ in zh_chars(text))


def score_chunk(lang: str, seg_text: dict[str, str], gold: list[dict], pred: list[dict]) -> dict:
    """pred 用正式解析器（parse_reply / parse_reply_en）的輸出。
    一筆建議算「對」：套用後的段落，和「只套用某一個標準答案」後的段落完全相同（忽略標點／大小寫）。"""
    gold_res = {}
    for gi, g in enumerate(gold):
        t = seg_text[g["segment_id"]]
        gold_res[gi] = (g["segment_id"], _norm_for_match(lang, _apply(t, g["offset"], g["wrong"], g["suggestion"])))
    matched, tp = set(), 0
    for p in pred:
        t = seg_text.get(p["segment_id"])
        if t is None:
            continue
        res = _norm_for_match(lang, _apply(t, p["offset"], p["wrong"], p["suggestion"]))
        hit = next((gi for gi, (sid, r) in gold_res.items() if gi not in matched and sid == p["segment_id"] and r == res), None)
        if hit is not None:
            matched.add(hit)
            tp += 1
    return {"tp": tp, "pred": len(pred), "gold": len(gold)}


def summarize(rows: list[dict]) -> dict:
    tp = sum(r["tp"] for r in rows)
    pred = sum(r["pred"] for r in rows)
    gold = sum(r["gold"] for r in rows)
    p = tp / pred if pred else 0.0
    r = tp / gold if gold else 0.0
    f05 = (1.25 * p * r / (0.25 * p + r)) if (p + r) else 0.0
    clean = [x for x in rows if x["gold"] == 0]
    false_alarm = sum(1 for x in clean if x["pred"] > 0) / len(clean) if clean else 0.0
    helpful = sum(r.get("helpful", 0) for r in rows)
    harmful = sum(r.get("harmful", 0) for r in rows)
    return {"helpful_rate": round(helpful / pred, 4) if pred else 0.0, "harmful_rate": round(harmful / pred, 4) if pred else 0.0,
            "helpful": helpful, "harmful": harmful,
            "chunks": len(rows), "gold": gold, "pred": pred, "tp": tp, "precision": round(p, 4),
            "recall": round(r, 4), "f0.5": round(f05, 4), "clean_chunks": len(clean),
            "false_alarm_rate_on_clean_chunks": round(false_alarm, 4)}


def error_rate(lang: str, hyp: str, ref: str) -> tuple[int, int]:
    """回傳 (編輯距離, 參考長度)：中文用字元（CER），英文用詞（WER）。"""
    if lang == "en":
        a = [en_norm(t) for t in hyp.split() if en_norm(t)]
        b = [en_norm(t) for t in ref.split() if en_norm(t)]
    else:
        a = [c for c, _ in zh_chars(hyp)]
        b = [c for c, _ in zh_chars(ref)]
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, y in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y))
        prev = cur
    return prev[-1], len(b)
