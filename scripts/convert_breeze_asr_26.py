#!/usr/bin/env python3
"""
Convert Breeze-ASR-26 to WhisperKit Core ML format

Requirements:
- Python 3.10+
- whisperkittools (pip install whisperkittools)
- coremltools >= 8.0
- torch >= 2.0
- transformers >= 4.36
- huggingface_hub
- GPU with 24GB+ VRAM recommended (A100/H100)

Usage:
    python convert_breeze_asr_26.py --output-dir ./breeze-asr-26-coreml --quantize 4bit
"""

import os
import sys
import subprocess
import argparse
import shutil
from pathlib import Path


def check_requirements():
    """Check if all required packages are installed"""
    required = [
        "whisperkittools",
        "coremltools",
        "torch",
        "transformers",
        "huggingface_hub",
    ]
    missing = []
    for pkg in required:
        try:
            __import__(pkg.replace("-", "_"))
        except ImportError:
            missing.append(pkg)

    if missing:
        print(f"❌ Missing packages: {missing}")
        print(f"Install with: pip install {' '.join(missing)}")
        return False
    return True


def check_gpu():
    """Check GPU availability"""
    try:
        import torch
        if torch.cuda.is_available():
            gpu_name = torch.cuda.get_device_name(0)
            gpu_mem = torch.cuda.get_device_properties(0).total_memory / 1e9
            print(f"✅ GPU: {gpu_name} ({gpu_mem:.1f} GB)")
            if gpu_mem < 20:
                print("⚠️  Warning: GPU memory < 20GB, conversion may fail or be slow")
            return True
        elif torch.backends.mps.is_available():
            print("✅ Apple Silicon (MPS) available")
            return True
        else:
            print("⚠️  No GPU detected - conversion will be VERY slow on CPU")
            return False
    except Exception as e:
        print(f"⚠️  Could not check GPU: {e}")
        return False


def run_conversion(output_dir: str, quantize: str = "4bit", hf_token: str = None):
    """Run whisperkit-generate-model to convert Breeze-ASR-26"""

    env = os.environ.copy()
    env["MODEL_REPO_ID"] = "MediaTek-Research/Breeze-ASR-26"

    if hf_token:
        env["HF_TOKEN"] = hf_token

    cmd = [
        sys.executable, "-m", "whisperkittools.scripts.generate_model",
        "--model-version", "MediaTek-Research/Breeze-ASR-26",
        "--output-dir", output_dir,
    ]

    if quantize == "4bit":
        cmd.append("--generate-quantized-variants")

    print(f"🚀 Running conversion command:")
    print(f"   {' '.join(cmd)}")
    print(f"   MODEL_REPO_ID=MediaTek-Research/Breeze-ASR-26")
    if hf_token:
        print(f"   HF_TOKEN=***")

    try:
        result = subprocess.run(cmd, env=env, check=True, capture_output=True, text=True, timeout=7200)
        print("✅ Conversion completed successfully!")
        print(result.stdout)
        return True
    except subprocess.TimeoutExpired:
        print("❌ Conversion timed out (2 hours)")
        return False
    except subprocess.CalledProcessError as e:
        print(f"❌ Conversion failed with exit code {e.returncode}")
        print(f"STDOUT:\n{e.stdout}")
        print(f"STDERR:\n{e.stderr}")
        return False


def verify_output(output_dir: str):
    """Verify the converted model has all required files"""
    required_files = [
        "AudioEncoder.mlmodelc",
        "TextDecoder.mlmodelc",
        "MelSpectrogram.mlmodelc",
        "tokenizer.json",
        "config.json",
    ]

    output_path = Path(output_dir)
    print(f"\n🔍 Verifying output in {output_path}")

    all_good = True
    for f in required_files:
        path = output_path / f
        if path.exists():
            size = path.stat().st_size / 1e6
            print(f"  ✅ {f} ({size:.1f} MB)")
        else:
            # Check if it's a directory (mlmodelc is a bundle)
            if path.with_suffix("").is_dir():
                print(f"  ✅ {f} (directory)")
            else:
                print(f"  ❌ {f} - MISSING")
                all_good = False

    # Check for quantized variants
    quantized_dirs = list(output_path.glob("*4bit*")) + list(output_path.glob("*quant*"))
    if quantized_dirs:
        print(f"  ✅ Quantized variants found: {[d.name for d in quantized_dirs]}")

    return all_good


def test_whisperkit_load(output_dir: str):
    """Test loading the model with WhisperKit (requires macOS + Xcode)"""
    print("\n🧪 Testing WhisperKit load (macOS only)...")

    # This would need to be run on macOS with WhisperKit installed
    # For now, just check if the model folder structure is correct
    test_script = f'''
import sys
sys.path.insert(0, "/path/to/whisperkittools")
try:
    from whisperkit import WhisperKit
    import asyncio

    async def test():
        kit = await WhisperKit(modelFolder="{output_dir}")
        print("✅ WhisperKit loaded successfully!")
        print(f"   Model: {{kit.model_name}}")
        print(f"   Languages: {{kit.supported_languages}}")

    asyncio.run(test())
except Exception as e:
    print(f"❌ WhisperKit load test failed: {{e}}")
'''

    print("   Run this on macOS to verify:")
    print(f"   cd {output_dir} && python -c \"{test_script.strip()}\"")
    return True


def create_ios_copy_script(output_dir: str, ios_models_dir: str):
    """Create a script to copy the model to iOS App Models directory"""
    script = f"""#!/bin/bash
# Copy Breeze-ASR-26 Core ML model to iOS App

SOURCE_DIR="{output_dir}"
DEST_DIR="{ios_models_dir}/breeze-asr-26-coreml"

echo "📦 Copying model to iOS..."
mkdir -p "$DEST_DIR"
cp -r "$SOURCE_DIR"/* "$DEST_DIR"/

echo "✅ Model copied to $DEST_DIR"
ls -la "$DEST_DIR"
"""

    script_path = Path(output_dir) / "copy_to_ios.sh"
    script_path.write_text(script)
    script_path.chmod(0o755)
    print(f"\n📝 Created iOS copy script: {script_path}")
    return script_path


def upload_to_huggingface(output_dir: str, repo_id: str, hf_token: str, private: bool = False):
    """Upload converted model to Hugging Face Hub"""
    try:
        from huggingface_hub import HfApi, create_repo
        import time

        api = HfApi(token=hf_token)

        # Create repo if not exists
        print(f"\n🤗 Creating/updating Hugging Face repo: {repo_id}")
        try:
            create_repo(repo_id, token=hf_token, private=private, exist_ok=True, repo_type="model")
            print(f"✅ Repo ready: https://huggingface.co/{repo_id}")
        except Exception as e:
            print(f"⚠️  Repo creation: {e}")

        # Upload all files
        print(f"📤 Uploading model files to {repo_id}...")
        api.upload_folder(
            folder_path=output_dir,
            repo_id=repo_id,
            token=hf_token,
            repo_type="model",
            commit_message=f"Add Breeze-ASR-26 WhisperKit Core ML model (auto-converted)",
        )
        print(f"✅ Upload complete! Model available at: https://huggingface.co/{repo_id}")
        return True

    except ImportError:
        print("❌ huggingface_hub not installed. Run: pip install huggingface_hub")
        return False
    except Exception as e:
        print(f"❌ Upload failed: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Convert Breeze-ASR-26 to WhisperKit Core ML")
    parser.add_argument("--output-dir", default="./breeze-asr-26-coreml", help="Output directory")
    parser.add_argument("--quantize", choices=["none", "4bit", "8bit"], default="4bit", help="Quantization level")
    parser.add_argument("--hf-token", help="Hugging Face token (for gated models and upload)")
    parser.add_argument("--ios-models-dir", default="../ios/App/Models", help="iOS Models directory")
    parser.add_argument("--skip-checks", action="store_true", help="Skip requirement checks")
    parser.add_argument("--verify-only", action="store_true", help="Only verify existing output")
    parser.add_argument("--hf-repo", help="Hugging Face repo ID to upload to (e.g., username/breeze-asr-26-whisperkit-coreml)")
    parser.add_argument("--hf-private", action="store_true", help="Make HF repo private")

    args = parser.parse_args()

    print("=" * 60)
    print("  Breeze-ASR-26 → WhisperKit Core ML Converter")
    print("=" * 60)

    if args.verify_only:
        if verify_output(args.output_dir):
            print("\n✅ Verification passed!")
            # Allow upload even in verify-only mode
            if args.hf_repo and args.hf_token:
                print("\n" + "=" * 60)
                print("  UPLOADING TO HUGGING FACE")
                print("=" * 60)
                upload_to_huggingface(args.output_dir, args.hf_repo, args.hf_token, args.hf_private)
        else:
            print("\n❌ Verification failed")
            sys.exit(1)
        return

    if not args.skip_checks:
        print("\n🔧 Checking requirements...")
        if not check_requirements():
            sys.exit(1)

        print("\n🖥️  Checking GPU...")
        check_gpu()

    print(f"\n📁 Output directory: {args.output_dir}")
    Path(args.output_dir).mkdir(parents=True, exist_ok=True)

    print("\n" + "=" * 60)
    print("  STARTING CONVERSION (this may take 30-60 minutes)")
    print("=" * 60)

    success = run_conversion(args.output_dir, args.quantize, args.hf_token)

    if success:
        print("\n" + "=" * 60)
        print("  VERIFYING OUTPUT")
        print("=" * 60)
        if verify_output(args.output_dir):
            print("\n🎉 CONVERSION SUCCESSFUL!")
            create_ios_copy_script(args.output_dir, args.ios_models_dir)
            test_whisperkit_load(args.output_dir)

            # Upload to Hugging Face if requested
            if args.hf_repo and args.hf_token:
                print("\n" + "=" * 60)
                print("  UPLOADING TO HUGGING FACE")
                print("=" * 60)
                upload_to_huggingface(args.output_dir, args.hf_repo, args.hf_token, args.hf_private)

            print("\n📋 NEXT STEPS:")
            print(f"   1. Run: bash {args.output_dir}/copy_to_ios.sh")
            print(f"   2. Update MeetsumLocalASRPlugin.swift to use 'breeze-asr-26-coreml'")
            print(f"   3. Add 'breeze-asr-26' to frontend model options")
            print(f"   4. Test on iOS device with Taiwanese audio")
            if args.hf_repo:
                print(f"   5. Model published to: https://huggingface.co/{args.hf_repo}")
        else:
            print("\n❌ Output verification failed")
            sys.exit(1)
    else:
        print("\n❌ CONVERSION FAILED")
        sys.exit(1)


if __name__ == "__main__":
    main()