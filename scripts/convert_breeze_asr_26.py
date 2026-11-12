#!/usr/bin/env python3
"""
Convert Breeze-ASR-26 to WhisperKit Core ML format.

Breeze-ASR-26（MediaTek）是以 Whisper large-v2 架構微調的台語語音模型
（tokenizer 為 51865 vocab 的多語版本）。
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

注意：whisperkit-generate-model 不會複製 config.json，也不會產生 tokenizer.json；
本腳本會在轉換後自動補齊（WhisperKit 載入模型時需要）。
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

MODEL_VERSION = "MediaTek-Research/Breeze-ASR-26"
# Core ML 模型本體（whisperkit-generate-model 會產生這些）
CORE_MODEL_FILES = [
    "AudioEncoder.mlmodelc",
    "TextDecoder.mlmodelc",
    "MelSpectrogram.mlmodelc",
]
# WhisperKit 載入模型時另外需要的 metadata（原工具不會複製，由本腳本補上）
METADATA_FILES = ["config.json", "tokenizer.json"]
REQUIRED_FILES = CORE_MODEL_FILES + METADATA_FILES
# 從原模型 repo 複製的設定檔
CONFIG_FILES = ["config.json", "generation_config.json"]
# 由 AutoTokenizer 產生、WhisperKit 會用到的 tokenizer 相關檔案
TOKENIZER_FILES = [
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "added_tokens.json",
    "vocab.json",
    "merges.txt",
    "normalizer.json",
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
        # WhisperKitTools 要求 --generate-quantized-variants 必須搭配 --allowed-nbits。
        # --force-recipe-nbits 是關鍵：沒有它，WhisperKitTools 會跑「混合位元搜尋」
        # （對 1/2/3/4/6/8-bit 各做一次全模型 palettize profiling），
        # large-v3 規模要 3 小時以上；指定後只做我們要的那一種位元。
        cmd += [
            "--generate-quantized-variants",
            "--allowed-nbits", "4" if quantize == "4bit" else "8",
            "--force-recipe-nbits",
        ]

    env = os.environ.copy()
    if hf_token:
        env["HF_TOKEN"] = hf_token

    print("🚀 轉換指令：", flush=True)
    print("   " + " ".join(cmd), flush=True)
    try:
        result = subprocess.run(cmd, env=env, check=True, text=True, timeout=20400)
        print(result.stdout[-4000:] if result.stdout else "")
        print("✅ 轉換完成")
        return True
    except FileNotFoundError:
        print("❌ 找不到 whisperkit-generate-model，請先安裝 WhisperKitTools")
        return False
    except subprocess.TimeoutExpired:
        print("❌ 轉換逾時（5 小時 40 分）")
        return False
    except subprocess.CalledProcessError as e:
        print(f"❌ 轉換失敗（exit {e.returncode}）")
        if e.stdout:
            print("STDOUT:\n" + e.stdout[-4000:])
        if e.stderr:
            print("STDERR:\n" + e.stderr[-4000:])
        return False


def _dir_bytes(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def find_core_dirs(output_dir: str) -> list[Path]:
    """找出含有 Core ML 模型本體的資料夾（不論 metadata 是否齊全）。"""
    root = Path(output_dir)
    if not root.exists():
        return []
    candidates = [root] + [p for p in root.iterdir() if p.is_dir()]
    return [
        path for path in candidates
        if all((path / name).exists() for name in CORE_MODEL_FILES)
    ]


def find_model_dirs(output_dir: str) -> list[Path]:
    """找出 output_dir 下所有「完整」的 WhisperKit 模型資料夾。"""
    return [
        path for path in find_core_dirs(output_dir)
        if all((path / name).exists() for name in REQUIRED_FILES)
    ]


def ensure_quantized_dirs(output_dir: str, model_version: str, quantize: str) -> list[Path]:
    """確保量化 variant 資料夾存在。

    whisperkit-generate-model 的 "Rearranging variants" 通常會建立
    `<model>_<N>MB/`，但它只搬 encoder/decoder/melspectrogram，而且某些版本
    會因為找不到元件而靜默跳過。這裡直接從 `compression_artifacts/` 重建。
    """
    if quantize == "none":
        return []

    root = Path(output_dir)
    base_name = model_version.replace("/", "_")
    existing = [
        p for p in root.iterdir()
        if p.is_dir() and p.name.startswith(base_name + "_") and p.name.endswith("MB")
    ]
    if existing:
        return existing

    nbits = 4 if quantize == "4bit" else 8
    artifacts = root / base_name / "compression_artifacts"
    if not artifacts.exists():
        return []

    encoders = sorted(artifacts.glob(f"AudioEncoder/**/AudioEncoder_*{nbits}-bit.mlmodelc"))
    decoders = sorted(artifacts.glob(f"TextDecoder/**/TextDecoder_*{nbits}-bit.mlmodelc"))
    mel = root / base_name / "MelSpectrogram.mlmodelc"
    if not (encoders and decoders and mel.exists()):
        print("  ⚠️  找不到可組裝的量化元件"
              f"（encoder={len(encoders)}, decoder={len(decoders)}, mel={mel.exists()}）")
        return []

    size_mb = int((_dir_bytes(encoders[0]) + _dir_bytes(decoders[0])) / 1e6)
    dest = root / f"{base_name}_{size_mb}MB"
    print(f"  🔧 從 compression_artifacts 組裝 {dest.name}")
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copytree(encoders[0], dest / "AudioEncoder.mlmodelc", dirs_exist_ok=True)
    shutil.copytree(decoders[0], dest / "TextDecoder.mlmodelc", dirs_exist_ok=True)
    shutil.copytree(mel, dest / "MelSpectrogram.mlmodelc", dirs_exist_ok=True)
    return [dest]


def _copy_if_missing(src: Path, dst_dir: Path) -> bool:
    target = dst_dir / src.name
    if target.exists():
        return False
    shutil.copy2(src, target)
    return True


def _fetch_config_files(model_version: str, hf_token: str | None) -> list[Path]:
    """從原模型 repo 取得 config.json / generation_config.json。"""
    from huggingface_hub import hf_hub_download

    found = []
    for name in CONFIG_FILES:
        try:
            found.append(Path(hf_hub_download(
                repo_id=model_version, filename=name, token=hf_token
            )))
        except Exception as exc:  # noqa: BLE001
            print(f"  ⚠️  無法取得 {name}：{exc}")
    return found


def _build_tokenizer_files(model_version: str, hf_token: str | None) -> Path | None:
    """把原模型的 slow tokenizer 轉成 WhisperKit 需要的 tokenizer.json。"""
    from transformers import AutoTokenizer

    tmp = Path(tempfile.mkdtemp(prefix="meetsum-tokenizer-"))
    try:
        tokenizer = AutoTokenizer.from_pretrained(model_version, token=hf_token)
        tokenizer.save_pretrained(tmp)
    except Exception as exc:  # noqa: BLE001
        print(f"  ⚠️  無法從 {model_version} 建立 tokenizer：{exc}")
        # 後備：Breeze 與 large-v2 同一個 tokenizer（vocab 51865）
        try:
            tokenizer = AutoTokenizer.from_pretrained("openai/whisper-large-v2")
            tokenizer.save_pretrained(tmp)
        except Exception as fallback_exc:  # noqa: BLE001
            print(f"  ❌ 後備 tokenizer 也失敗：{fallback_exc}")
            shutil.rmtree(tmp, ignore_errors=True)
            return None

    if not (tmp / "tokenizer.json").exists():
        print(f"  ❌ {model_version} 的 tokenizer 沒有產生 tokenizer.json")
        shutil.rmtree(tmp, ignore_errors=True)
        return None
    return tmp


def ensure_metadata(output_dir: str, model_version: str, hf_token: str | None) -> None:
    """補上 config.json 與 tokenizer 檔案到每個模型資料夾。

    WhisperKitTools 只在 `--upload-results` 上傳官方 repo 時才複製 config.json，
    tokenizer.json 更是完全沒有產生。App 端若缺少這些檔案，WhisperKit 會嘗試
    連網下載 tokenizer，離線／本機模式就會失敗。
    """
    dirs = find_core_dirs(output_dir)
    if not dirs:
        return

    config_files = _fetch_config_files(model_version, hf_token)
    for path in dirs:
        copied = [src.name for src in config_files if _copy_if_missing(src, path)]
        if copied:
            print(f"  📄 {path.name}：補上 {', '.join(copied)}")

    needs_tokenizer = [p for p in dirs if not (p / "tokenizer.json").exists()]
    if not needs_tokenizer:
        return

    print(f"  🔤 產生 tokenizer.json（{len(needs_tokenizer)} 個資料夾）")
    tmp = _build_tokenizer_files(model_version, hf_token)
    if tmp is None:
        return
    try:
        for path in needs_tokenizer:
            copied = [
                name for name in TOKENIZER_FILES
                if (tmp / name).exists() and _copy_if_missing(tmp / name, path)
            ]
            if copied:
                print(f"  📄 {path.name}：補上 {', '.join(copied)}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def prepare_output(
    output_dir: str, model_version: str, quantize: str, hf_token: str | None
) -> None:
    """轉換後處理：組出量化 variant、補齊 WhisperKit metadata。"""
    ensure_quantized_dirs(output_dir, model_version, quantize)
    ensure_metadata(output_dir, model_version, hf_token)


def verify_output(output_dir: str) -> list[Path]:
    dirs = sorted(find_model_dirs(output_dir), key=_dir_bytes)
    print(f"\n🔍 檢查 {output_dir}")
    if not dirs:
        print("  ❌ 找不到完整的 WhisperKit 模型資料夾")
        print(f"     需要這些檔案：{', '.join(REQUIRED_FILES)}")
        return []
    for path in dirs:
        print(f"  ✅ {path.name}（{_dir_bytes(path) / 1e6:.0f} MB）")
    return dirs



QUANTIZED_DIR_RE = re.compile(r".+_\d+MB$")


def select_quantized(dirs: list[Path]) -> list[Path]:
    """只留下量化 variant 資料夾（名稱結尾為 _<N>MB）。"""
    return [p for p in dirs if QUANTIZED_DIR_RE.match(p.name)]


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
    parser.add_argument(
        "--quantized-only",
        action="store_true",
        help="只上傳量化 variant（跳過全精度資料夾，省下數 GB 上傳）",
    )
    args = parser.parse_args()

    if not args.verify_only:
        if not check_requirements():
            sys.exit(1)
        Path(args.output_dir).mkdir(parents=True, exist_ok=True)
        if not run_conversion(args.output_dir, args.quantize, args.hf_token, args.model_version):
            sys.exit(1)

    prepare_output(args.output_dir, args.model_version, args.quantize, args.hf_token)
    dirs = verify_output(args.output_dir)
    if not dirs:
        sys.exit(1)

    if args.quantized_only:
        dirs = select_quantized(dirs)
        if not dirs:
            print("❌ 找不到量化 variant（資料夾名稱需以 _<N>MB 結尾）")
            sys.exit(1)
        print("   只處理量化 variant：" + ", ".join(p.name for p in dirs))

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
