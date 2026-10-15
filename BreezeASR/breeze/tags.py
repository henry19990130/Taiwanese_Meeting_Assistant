import re

MAX_TAG_LENGTH = 20
MAX_TAGS = 8
_TAG_RE = re.compile(r"^[\w](?:[\w\- ]{0,18}[\w\-])?$", re.UNICODE)


class TagError(ValueError):
    """標籤內容不合法。"""


def normalize_tags(raw: object) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise TagError("標籤必須是字串清單")
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, str):
            raise TagError("標籤必須是文字")
        tag = " ".join(item.split())
        if not tag:
            raise TagError("標籤不能是空白")
        if len(tag) > MAX_TAG_LENGTH:
            raise TagError(f"標籤最多 {MAX_TAG_LENGTH} 字")
        if _TAG_RE.fullmatch(tag) is None:
            raise TagError("標籤只能用中英數、空白、連字號或底線")
        key = tag.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(tag)
        if len(cleaned) > MAX_TAGS:
            raise TagError(f"一筆逐字稿最多 {MAX_TAGS} 個標籤")
    return cleaned
