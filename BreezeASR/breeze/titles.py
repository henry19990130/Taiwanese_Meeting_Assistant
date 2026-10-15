MAX_TITLE_LENGTH = 80


class TitleError(ValueError):
    """標題內容不合法。"""


def normalize_title(raw: object) -> str:
    if not isinstance(raw, str):
        raise TitleError("標題必須是文字")
    title = " ".join(raw.split())
    if not title:
        raise TitleError("標題不能是空白")
    if len(title) > MAX_TITLE_LENGTH:
        raise TitleError(f"標題最多 {MAX_TITLE_LENGTH} 字")
    return title
