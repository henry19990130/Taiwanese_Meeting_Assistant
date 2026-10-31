from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app import config

results: list[tuple[str, bool, str]] = []


def check(name: str):
    def deco(fn):
        try:
            detail = fn() or ""
            results.append((name, True, detail))
        except Exception as exc:
            results.append((name, False, f"{type(exc).__name__}: {exc}"))
        return fn
    return deco


@check("GPU")
def _gpu():
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("沒有偵測到 CUDA，請到「執行階段 → 變更執行階段類型」選 GPU")
    p = torch.cuda.get_device_properties(0)
    return f"{p.name}, {p.total_memory / 1024**3:.1f} GB"


@check("ffmpeg")
def _ffmpeg():
    path = shutil.which("ffmpeg")
    if not path:
        raise RuntimeError("找不到 ffmpeg")
    return path


@check("PostgreSQL")
def _pg():
    import psycopg

    with psycopg.connect(config.DATABASE_URL, connect_timeout=5) as conn:
        rows = conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='public' ORDER BY table_name"
        ).fetchall()
    tables = [r[0] for r in rows]
    expected = {"users", "sessions", "meetings", "meeting_transcripts", "meeting_summaries"}
    missing = expected - set(tables)
    if missing:
        raise RuntimeError(f"缺少資料表：{sorted(missing)}")
    return f"{config.DB_NAME}：{', '.join(tables)}"


@check("Ollama / LLM")
def _ollama():
    import httpx

    version = httpx.get(f"{config.OLLAMA_HOST}/api/version", timeout=5).json()["version"]
    models = [m["name"] for m in httpx.get(f"{config.OLLAMA_HOST}/api/tags", timeout=5).json()["models"]]
    if config.LLM_MODEL not in models:
        raise RuntimeError(f"Ollama {version} 已啟動，但沒有 {config.LLM_MODEL}；目前有：{models}")
    return f"Ollama {version}，模型 {config.LLM_MODEL} 已就緒"


@check("簡轉繁 (OpenCC)")
def _opencc():
    from app.services.asr_service import to_traditional

    out = to_traditional("语音识别会议记录")
    if out != "語音識別會議記錄":
        raise RuntimeError(f"轉換結果不對：{out}（pip install opencc-python-reimplemented）")
    return f"语音识别 → {out[:4]}"


if "--no-asr" not in sys.argv:

    @check("ASR 實測")
    def _asr():
        from app.services.asr_service import ASRService

        sample = BACKEND_DIR / "storage" / "samples" / "test.m4a"
        svc = ASRService()
        t0 = time.time()
        segs = svc.transcribe(str(sample), "zh")
        dt = time.time() - t0
        if svc.is_loaded:
            raise RuntimeError("辨識完模型沒有卸載")
        if not segs:
            raise RuntimeError("辨識結果是空的")
        text = "".join(s["text"] for s in segs)
        return f"{svc.model_name}，{dt:.1f}s（含載入、卸載）→「{text[:40]}」"


lines = ["========== 環境檢查結果 =========="]
for name, ok, detail in results:
    lines.append(f"{'✅' if ok else '❌'} {name:<18} {detail}")
all_ok = all(ok for _, ok, _ in results)
lines.append("==================================")
lines.append("全部通過，可以開始開發！" if all_ok else "有項目失敗，請把上面的訊息貼給我。")
print("\n" + "\n".join(lines))
try:
    log_dir = BACKEND_DIR.parent / "logs"
    log_dir.mkdir(exist_ok=True)
    (log_dir / "env_check.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
except OSError:
    pass
sys.exit(0 if all_ok else 1)
