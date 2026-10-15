import os
import threading
from pathlib import Path

from breeze.models import Recognition


class BreezeRecognizer:
    """只負責載入本地 Breeze-ASR-26 並把 WAV 辨識成文字。"""

    model_name = "Breeze-ASR-26"

    def __init__(self, model_dir: Path):
        self._model_dir = model_dir
        self._pipeline = None
        self._device_name = ""
        self._lock = threading.Lock()

    def available(self) -> bool:
        return (self._model_dir / "config.json").is_file()

    def loaded(self) -> bool:
        return self._pipeline is not None

    def device_name(self) -> str:
        return self._device_name

    def transcribe(self, wav_path: Path) -> Recognition:
        with self._lock:
            pipeline = self._ensure_pipeline()
            result = pipeline(str(wav_path))
            device = self._device_name
        text = str(result.get("text") or "").strip()
        return Recognition(text=text, model=self.model_name, device=device)

    def _ensure_pipeline(self):
        if self._pipeline is not None:
            return self._pipeline
        if not self.available():
            raise RuntimeError(
                f"找不到本地模型：{self._model_dir}\n"
                "請確認資料夾內有 config.json 與模型權重，"
                "或設定 BREEZEASR_MODEL_DIR。"
            )

        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

        import torch
        from transformers import pipeline

        use_gpu = _gpu_can_hold_model(torch)
        self._device_name = "cuda" if use_gpu else "cpu"
        print(f"載入模型：{self._model_dir}")
        print(f"運算裝置：{'CUDA GPU' if use_gpu else 'CPU'}")
        self._pipeline = pipeline(
            "automatic-speech-recognition",
            model=str(self._model_dir),
            tokenizer=str(self._model_dir),
            feature_extractor=str(self._model_dir),
            device=0 if use_gpu else -1,
            torch_dtype=torch.float16 if use_gpu else torch.float32,
            chunk_length_s=30,
        )
        return self._pipeline


def _gpu_can_hold_model(torch_module) -> bool:
    if not torch_module.cuda.is_available():
        return False
    total = torch_module.cuda.get_device_properties(0).total_memory
    if total >= 6 * 1024**3:
        return True
    print(f"顯示卡記憶體 {total / 1024**3:.1f} GB，放不下 Breeze-ASR-26，改用 CPU。")
    return False
