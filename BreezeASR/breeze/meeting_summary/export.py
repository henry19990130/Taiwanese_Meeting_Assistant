from datetime import datetime
from pathlib import Path


def export_markdown(content: str, output_dir: Path, when: datetime) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    date_stamp = when.strftime("%Y%m%d")
    path = output_dir / f"會議紀錄_{date_stamp}.md"
    if path.exists():
        path = output_dir / f"會議紀錄_{when.strftime('%Y%m%d_%H%M%S')}.md"
    path.write_text(content.strip() + "\n", encoding="utf-8")
    return path
