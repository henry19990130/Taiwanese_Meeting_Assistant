"""把本機逐字稿交給 Ollama，產出會議紀錄 Markdown。"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from breeze.meeting_summary.client import DEFAULT_HOST, DEFAULT_MODEL, OllamaChatClient
from breeze.meeting_summary.errors import SummaryError
from breeze.meeting_summary.service import MeetingSummaryService


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=f"讀取 .txt / .md 逐字稿，用本機 Ollama {DEFAULT_MODEL} 產出會議紀錄。",
    )
    parser.add_argument("transcript", type=Path, help="逐字稿路徑（.txt 或 .md）")
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=None,
        help="輸出資料夾。預設為逐字稿所在資料夾。",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("OLLAMA_HOST", DEFAULT_HOST),
        help="Ollama API 位址，預設 http://127.0.0.1:11434",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("OLLAMA_MODEL", DEFAULT_MODEL),
        help=f"模型名稱，預設 {DEFAULT_MODEL}",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    transcript = args.transcript.expanduser().resolve()
    output_dir = (args.output_dir or transcript.parent).expanduser().resolve()
    service = MeetingSummaryService(
        OllamaChatClient(host=args.host, model=args.model, temperature=0.2),
    )
    print(f"讀取逐字稿：{transcript}", flush=True)
    print(f"模型：{args.model}  temperature：0.2", flush=True)
    print("正在串流生成會議紀錄…\n", flush=True)
    try:
        path = service.summarize_file(
            transcript,
            output_dir,
            on_token=lambda token: print(token, end="", flush=True),
        )
    except SummaryError as exc:
        print(f"\n{exc}", file=sys.stderr)
        return 1
    print(f"\n\n已儲存：{path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
