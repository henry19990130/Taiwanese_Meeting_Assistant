"""顯示卡記憶體管家：語音辨識前確認放得下，放不下就請 Ollama 讓語言模型暫時退場。

語言模型平常常駐（會議小幫手要用）。下一場會議開始辨識時，如果剩餘記憶體不夠語音模型用，
先卸載 Ollama 裡的模型；之後摘要或小幫手再呼叫時，Ollama 會自動重新載入（多等 10–30 秒），不會當掉。
"""
from __future__ import annotations

import logging

import httpx

from app import config

log = logging.getLogger(__name__)

# 語音模型辨識時需要的顯示卡記憶體（MB）。分批 4 段的保守值，可用 ASR_VRAM_NEED_MB 覆蓋。
_NEED_MB = {"zh": 10500, "nan": 10500, "hak": 10500, "en": 8000}
_MARGIN_MB = 512


def need_mb(language: str) -> int:
    return config.ASR_VRAM_NEED_MB or _NEED_MB.get(language, 10500)


def free_mb() -> int | None:
    try:
        import torch

        if not torch.cuda.is_available():
            return None
        free, _total = torch.cuda.mem_get_info()
        return int(free / 2**20)
    except Exception:  # 沒有 torch 或沒有顯示卡：不檢查
        return None


def unload_llm() -> list[str]:
    """請 Ollama 卸載所有已載入的模型，回傳卸載了哪些。"""
    names: list[str] = []
    try:
        ps = httpx.get(f"{config.OLLAMA_HOST}/api/ps", timeout=10).json().get("models", [])
        for m in ps:
            name = m.get("name") or m.get("model")
            httpx.post(f"{config.OLLAMA_HOST}/api/generate", json={"model": name, "keep_alive": 0}, timeout=60)
            names.append(name)
    except httpx.HTTPError as exc:
        log.warning("卸載語言模型失敗：%s", exc)
    return names


def make_room_for_asr(language: str) -> bool:
    """回傳 True 表示有讓語言模型退場。"""
    if not config.ASR_GPU_GUARD:
        return False
    free = free_mb()
    if free is None:
        return False
    need = need_mb(language) + _MARGIN_MB
    if free >= need:
        log.info("顯示卡剩 %d MB，語音辨識需要約 %d MB，語言模型繼續常駐", free, need)
        return False
    names = unload_llm()
    log.info("顯示卡剩 %d MB，不夠語音辨識（約 %d MB），先讓語言模型退場：%s；之後呼叫會自動載回",
             free, need, names or "無")
    return bool(names)
