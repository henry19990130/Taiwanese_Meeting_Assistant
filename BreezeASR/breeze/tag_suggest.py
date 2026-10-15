import json
import re

from breeze.tags import TagError, normalize_tags

TAG_SYSTEM = """你依照給你的會議內容推薦標籤。
每個標籤都要是這份內容裡才看得到的短語，2 到 12 個字，台灣繁體中文。
給 4 到 6 個。不要用每份紀錄都適用的空泛詞。
只回傳一層 JSON 字串陣列，例如 ["供應商延期","南門市場"]。
不要物件、不要巢狀陣列、不要說明、不要 markdown。不可回傳空陣列。"""

_RETRY_USER = """上一則回覆沒有可用標籤。
請只輸出一層 JSON 字串陣列，至少 4 個字串，不可是物件、巢狀陣列或空陣列。
標籤必須取自下面內容。

會議內容：
{source}"""

_SUGGEST_LIMIT = 6
_SOURCE_LIMIT = 3000
_BULLET = re.compile(r"^(?:[-*•]+|\d+[.、)])\s*")
_SPLIT = re.compile(r"[\n,，、;；|]+")


def _flatten(value: object, into: list[str]) -> None:
    if isinstance(value, str):
        into.append(value)
        return
    if isinstance(value, list):
        for item in value:
            _flatten(item, into)
        return
    if isinstance(value, dict):
        for key in ("tag", "label", "name", "text", "value"):
            picked = value.get(key)
            if isinstance(picked, str):
                into.append(picked)
                return
        for item in value.values():
            _flatten(item, into)


def _polish(item: str) -> str:
    tag = item.strip().strip("\"'`「」『』【】[]（）()＊*")
    tag = _BULLET.sub("", tag)
    tag = tag.strip("\"'`「」『』【】[]（）()、，,。；;：: ")
    return " ".join(tag.split())


def parse_suggested_tags(raw: str, *, limit: int = _SUGGEST_LIMIT) -> list[str]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    items: list[str] = []
    start = text.find("[")
    end = text.rfind("]")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            _flatten(parsed, items)
    if not items:
        items = _SPLIT.split(text)
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in items:
        tag = _polish(item)
        if not tag:
            continue
        try:
            tag = normalize_tags([tag])[0]
        except TagError:
            continue
        key = tag.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(tag)
        if len(cleaned) >= limit:
            break
    return cleaned


def clip_source(text: str) -> str:
    compact = text.strip()
    if len(compact) <= _SOURCE_LIMIT:
        return compact
    return compact[:_SOURCE_LIMIT]


class LlmTagSuggester:
    """把會議文字交給聊天模型，再把回覆收成合法標籤。"""

    def __init__(self, client):
        self._client = client

    def suggest(self, text: str) -> list[str]:
        source = clip_source(text)
        raw = self._client.complete(
            system=TAG_SYSTEM,
            user=f"會議內容：\n{source}",
            temperature=0.2,
        )
        tags = parse_suggested_tags(raw)
        if tags:
            return tags
        retry = self._client.complete(
            system=TAG_SYSTEM,
            user=_RETRY_USER.format(source=source),
            temperature=0.1,
        )
        return parse_suggested_tags(retry)
