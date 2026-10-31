"""相容入口。實作在 app.security.access。"""

from app.security.access import Missing, NotOwner, classify

__all__ = ["Missing", "NotOwner", "classify"]
