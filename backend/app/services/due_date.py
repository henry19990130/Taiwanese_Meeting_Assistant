from __future__ import annotations

import calendar
import re
from datetime import date, timedelta

_DIGIT = {"零": 0, "〇": 0, "一": 1, "二": 2, "兩": 2, "两": 2, "三": 3, "四": 4,
          "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_NUM = r"[0-9０-９零〇一二兩两三四五六七八九十半]+"
_WEEKDAY = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6, "末": 4}


def _to_int(s: str) -> float | None:
    s = s.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    if s.isdigit():
        return int(s)
    if s == "半":
        return 0.5
    if "十" in s:
        tens, _, ones = s.partition("十")
        t = _DIGIT.get(tens, None) if tens else 1
        o = _DIGIT.get(ones, None) if ones else 0
        return None if t is None or o is None else t * 10 + o
    if len(s) == 1 and s in _DIGIT:
        return _DIGIT[s]
    return None


def _add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    y, m = d.year + y, m + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def _month_end(y: int, m: int) -> date:
    return date(y, m, calendar.monthrange(y, m)[1])


def _safe(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def parse_due(text: str | None, ref: date | None) -> date | None:
    if not text:
        return None
    t = re.sub(r"\s+", "", str(text))

    m = re.search(r"(\d{4})[-/年.](\d{1,2})[-/月.](\d{1,2})", t)
    if m:
        return _safe(int(m[1]), int(m[2]), int(m[3]))

    if ref is None:
        return None

    m = re.search(r"(?<!\d)(" + _NUM + r")月(" + _NUM + r")[日號号]", t) or \
        re.search(r"(?<![\d/])(\d{1,2})/(\d{1,2})(?![\d/])", t)
    if m:
        mo, dd = _to_int(m[1]), _to_int(m[2])
        if isinstance(mo, int) and isinstance(dd, int):
            d = _safe(ref.year, mo, dd)
            if d and d < ref:
                d = _safe(ref.year + 1, mo, dd)
            return d

    for word, n in (("大後天", 3), ("後天", 2), ("后天", 2), ("明天", 1), ("今天", 0)):
        if word in t:
            return ref + timedelta(days=n)

    m = re.search(r"(下下|下|這|这|本)(?:個)?(?:週|周|星期|禮拜|礼拜)([一二三四五六日天末])", t)
    if m:
        weeks = {"下下": 2, "下": 1}.get(m[1], 0)
        monday = ref - timedelta(days=ref.weekday()) + timedelta(weeks=weeks)
        d = monday + timedelta(days=_WEEKDAY[m[2]])
        return d if d >= ref else None

    m = re.search(r"(" + _NUM + r")月(?:底|末)", t)
    if m and isinstance(_to_int(m[1]), int) and 1 <= _to_int(m[1]) <= 12:
        mo = _to_int(m[1])
        y = ref.year if mo >= ref.month else ref.year + 1
        return _month_end(y, mo)
    if re.search(r"下(?:個)?月(?:底|末)", t):
        n = _add_months(ref, 1)
        return _month_end(n.year, n.month)
    if re.search(r"(?:這|这|本)?(?:個)?月(?:底|末)", t):
        return _month_end(ref.year, ref.month)
    if re.search(r"年(?:底|末)", t):
        return date(ref.year, 12, 31)

    m = re.search(r"(" + _NUM + r")(?:個|个)(月)", t) or \
        re.search(r"(" + _NUM + r")(?:個|个)?(週|周|星期|禮拜|礼拜|(?:工作)?天)", t)
    if m:
        n = _to_int(m[1])
        unit = m[2]
        if n is None:
            return None
        if unit == "月":
            if n == 0.5:
                return ref + timedelta(days=15)
            return _add_months(ref, int(n)) if n == int(n) else None
        if unit in ("週", "周", "星期", "禮拜", "礼拜"):
            return ref + timedelta(days=round(7 * n))
        if unit == "工作天":
            d, left = ref, int(n)
            while left > 0:
                d += timedelta(days=1)
                if d.weekday() < 5:
                    left -= 1
            return d
        return ref + timedelta(days=round(n))

    if re.search(r"下(?:個)?月", t):
        n = _add_months(ref, 1)
        return _month_end(n.year, n.month)

    return None
