#!/usr/bin/env python3
"""
Convert Breeze-ASR-26 to WhisperKit Core ML format.

Breeze-ASR-26（MediaTek）是 Whisper large-v3 以台語語音微調的模型。
社群釋出的是 whisper.cpp 格式（GGML + CoreML encoder），WhisperKit 需要
自己的 CoreML 目錄結構，因此需要先轉換。

需求：
- macOS（CoreML 轉換需要）
- Python 3.10+
- pip install "torch==2.5.0" "transformers==4.53" "numpy<2.4.0" coremltools huggingface_hub
- pip install git+https://github.com/argmaxinc/WhisperKitTools.git

用法：
    # 轉換（4-bit，適合 iPhone）
    python scripts/convert_breeze_asr_26.py --output-dir ./breeze-asr-coreml --quantize 4bit

    # 只驗證既有輸出
    python scripts/convert_breeze_asr_26.py --verify-only --output-dir ./breeze-asr-coreml

    # 驗證並上傳到 Hugging Face（每個 variant 一個資料夾，WhisperKit 才找得到）
    python scripts/convert_breeze_asr_26.py --verify-only --output-dir ./breeze-asr-coreml \
        --hf-repo your-name/breeze-asr-26-whisperkit --hf-token "$HF_TOKEN"

輸出結構（whisperkit-generate-model 的格式）：
    breeze-asr-coreml/
      MediaTek-Research_Breeze-ASR-26/          # 全精度
      MediaTek-Research_Breeze-ASR-26_<N>MB/    # 量化 variant（4-bit 通常是 MB 最小的）
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

MODEL_VERSION = "MediaTek-Research/Breeze-ASR-26"
REQUIRED_FILES = [
    "AudioEncoder.mlmodelc",
    "TextDecoder.mlmodelc",
    "MelSpectrogram.mlmodelc",
    "tokenizer.json",
    "config.json",
]
REQUIRED_PACKAGES = ["coremltools", "torch", "transformers", "huggingface_hub"]


def check_requirements() -> bool:
    missing = []
    for pkg in REQUIRED_PACKAGES:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        print(f"❌ 缺少套件：{missing}")
        print(f"   請執行：pip install {' '.join(missing)}")
        return False
    return True


def find_generate_command() -> list[str]:
    exe = shutil.which("whisperkit-generate-model")
    if exe:
        return [exe]
    # 從 source 安裝但 entry point 不在 PATH 時的後備
    return [sys.executable, "-m", "scripts.generate_model"]


def run_conversion(
    output_dir: str,
    quantize: str = "4bit",
    hf_token: str | None = None,
    model_version: str = MODEL_VERSION,
) -> bool:
    """呼叫 whisperkittools 的 whisperkit-generate-model。"""
    cmd = find_generate_command() + [
        "--model-version", model_version,
        "--output-dir", output_dir,
    ]
    if quantize != "none":
        # WhisperKitTools 要求 --generate-quantized-variants 必須搭配 --allowed-nbits
        cmd += ["--generate-quantized-variants", "--allowed-nbits", "4" if quantize == "4bit" else "8"]

    env = os.environ.copy()
    if hf_token:
        env["HF_TOKEN"] = hf_token

    print("🚀 轉換指令：")
    print("   " + " ".join(cmd))
    try:
        result = subprocess.run(cmd, env=env, check=True, text=True, timeout=7200)
        print(result.stdout[-4000:] if result.stdout else "")
        print("✅ 轉換完成")
        return True
    except FileNotFoundError:
        print("❌ 找不到 whisperkit-generate-model，請先安裝 WhisperKitTools")
        return False
    except subprocess.TimeoutExpired:
        print("❌ 轉換逾時（2 小時）")
        return False
    except subprocess.CalledProcessError as e:
        print(f"❌ 轉換失敗（exit {e.returncode}）")
        if e.stdout:
            print("STDOUT:\n" + e.stdout[-4000:])
        if e.stderr:
            print("STDERR:\n" + e.stderr[-4000:])
        return False


def find_model_dirs(output_dir: str) -> list[Path]:
    """找出 output_dir 下所有「完整」的 WhisperKit 模型資料夾。"""
    root = Path(output_dir)
    if not root.exists():
        return []
    found = []
    candidates = [root] + [p for p in root.iterdir() if p.is_dir()]
    for path in candidates:
        if all((path / name).exists() for name in REQUIRED_FILES):
            found.append(path)
    # 依大小排序：小的（量化）在前
    def size(p: Path) -> int:
        return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
    return sorted(found, key=size)


def verify_output(output_dir: str) -> list[Path]:
    dirs = find_model_dirs(output_dir)
    print(f"\n🔍 檢查 {output_dir}")
    if not dirs:
        print("  ❌ 找不到完整的 WhisperKit 模型資料夾")
        print(f"     需要這些檔案：{', '.join(REQUIRED_FILES)}")
        return []
    for path in dirs:
        mb = sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) / 1e6
        print(f"  ✅ {path.name}（{mb:.0f} MB）")
    return dirs


def upload_to_huggingface(dirs: list[Path], repo_id: str, hf_token: str, private: bool = False) -> bool:
    """把每個 variant 資料夾上傳到 repo 的同名子資料夾。

    WhisperKit.download(variant:from:) 會用 `*<variant>/*` 搜尋 repo，
    因此資料夾名稱就是 variant 名稱。
    """
    try:
        from huggingface_hub import HfApi, create_repo
    except ImportError:
        print("❌ 需要 huggingface_hub")
        return False

    api = HfApi(token=hf_token)
    print(f"\n🤗 建立／更新 repo：{repo_id}")
    try:
        create_repo(repo_id, token=hf_token, private=private, exist_ok=True, repo_type="model")
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️  建立 repo 失敗（可能已存在）：{exc}")

    ok = True
    for path in dirs:
        print(f"📤 上傳 {path.name} …")
        try:
            api.upload_folder(
                folder_path=str(path),
                repo_id=repo_id,
                path_in_repo=path.name,
                repo_type="model",
                commit_message="Add Breeze-ASR-26 WhisperKit Core ML model",
            )
        except Exception as exc:  # noqa: BLE001
            print(f"❌ 上傳 {path.name} 失敗：{exc}")
            ok = False

    if ok:
        print(f"\n✅ 完成：https://huggingface.co/{repo_id}")
        print("   在 ios/App/App/Info.plist 設定：")
        for path in dirs:
            print(f"     BreezeModelRepo    = {repo_id}")
            print(f"     BreezeModelVariant = {path.name}")
        print("   （多個 variant 時，挑 MB 最小的那個給 iPhone）")
    return ok


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert Breeze-ASR-26 to WhisperKit Core ML")
    parser.add_argument("--output-dir", default="./breeze-asr-26-coreml")
    parser.add_argument("--quantize", choices=["none", "4bit", "8bit"], default="4bit")
    parser.add_argument("--model-version", default=MODEL_VERSION)
    parser.add_argument("--hf-token", help="Hugging Face token（下載 gated 模型或上傳用）")
    parser.add_argument("--hf-repo", help="上傳目標 repo，例如 your-name/breeze-asr-26-whisperkit")
    parser.add_argument("--hf-private", action="store_true", help="把 repo 設為 private")
    parser.add_argument("--verify-only", action="store_true", help="只驗證既有輸出（可搭配 --hf-repo 上傳）")
    args = parser.parse_args()

    if not args.verify_only:
        if not check_requirements():
            sys.exit(1)
        Path(args.output_dir).mkdir(parents=True, exist_ok=True)
        if not run_conversion(args.output_dir, args.quantize, args.hf_token, args.model_version):
            sys.exit(1)

    dirs = verify_output(args.output_dir)
    if not dirs:
        sys.exit(1)

    if args.hf_repo:
        if not args.hf_token:
            print("❌ 上傳需要 --hf-token 或環境變數 HF_TOKEN")
            sys.exit(1)
        if not upload_to_huggingface(dirs, args.hf_repo, args.hf_token, args.hf_private):
            sys.exit(1)
    else:
        print("\n📋 下一步：")
        print("   1. 把 variant 資料夾複製到 App 的 Documents/WhisperKitModels/<name>_4bit/")
        print("      或上傳到 Hugging Face，並在 Info.plist 設定 BreezeModelRepo / BreezeModelVariant")
        print("   2. 用台語音檔在實機測試")


if __name__ == "__main__":
    main()
