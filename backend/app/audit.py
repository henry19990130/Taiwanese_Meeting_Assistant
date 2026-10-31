"""相容入口。實作在 app.security.audit。"""

from app.security.audit import account_key, log_root, record, record_content

__all__ = ["account_key", "log_root", "record", "record_content"]
