"""步驟 4（Colab）：把訓練好的 LoRA 變成 Ollama 模型（預設名稱 qwen3.8-27b-typo）。

做法 A（快、省空間）：llama.cpp 把 LoRA 轉成 GGUF adapter → Modelfile「FROM qwen3.8:27b + ADAPTER」
做法 B（備案）：LoRA 合併回原始權重 → 轉 GGUF → 量化成和官方 qwen3.8:27b 相同的格式 → ollama create

兩種做法建好之後都會做「冒煙測試」：同一批逐字稿，Ollama 版的回覆要和 transformers＋adapter 的回覆大致一致，
而且要和原版不同（代表 adapter 真的有生效）。不通過就自動改用做法 B。
產物會複製到 --save（Google Drive），之後每次開新的 Colab 只要 ollama create 就好，不用重訓。
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

LLAMA_CPP = Path("/content/llama.cpp")


def sh(cmd: list[str] | str, **kw) -> str:
    print("$", cmd if isinstance(cmd, str) else " ".join(cmd), flush=True)
    r = subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True, text=True, **kw)
    if r.returncode != 0:
        print(r.stdout[-3000:], r.stderr[-3000:])
        raise RuntimeError(f"指令失敗：{cmd}")
    return r.stdout


def ensure_llama_cpp(build_quantize: bool = False):
    if not LLAMA_CPP.exists():
        sh(["git", "clone", "-q", "--depth", "1", "https://github.com/ggml-org/llama.cpp", str(LLAMA_CPP)])
    sh([sys.executable, "-m", "pip", "install", "-q", str(LLAMA_CPP / "gguf-py")])
    if build_quantize and not (LLAMA_CPP / "build" / "bin" / "llama-quantize").exists():
        sh(f"cd {LLAMA_CPP} && cmake -B build -DGGML_CUDA=OFF -DLLAMA_CURL=OFF > /dev/null && "
           f"cmake --build build --target llama-quantize -j 8 > /dev/null")


def base_quant(base_tag: str) -> str:
    out = sh(["ollama", "show", base_tag])
    m = re.search(r"quantization\s+(\S+)", out)
    return m.group(1) if m else "Q4_K_M"


def base_modelfile(base_tag: str) -> str:
    return sh(["ollama", "show", base_tag, "--modelfile"])


def create(name: str, modelfile: str, workdir: Path):
    mf = workdir / "Modelfile"
    mf.write_text(modelfile, encoding="utf-8")
    sh(["ollama", "create", name, "-f", str(mf)], cwd=str(workdir))


def plan_a(base_hf: str, adapter: str, base_tag: str, name: str, work: Path) -> Path:
    ensure_llama_cpp()
    gguf = work / "typo-lora.gguf"
    sh([sys.executable, str(LLAMA_CPP / "convert_lora_to_gguf.py"), adapter, "--base", base_hf,
        "--outfile", str(gguf), "--outtype", "f16"])
    create(name, f"FROM {base_tag}\nADAPTER {gguf}\n", work)
    return gguf


def plan_b(base_hf: str, adapter: str, base_tag: str, name: str, work: Path) -> Path:
    import torch
    import lm_utils as L
    ensure_llama_cpp(build_quantize=True)
    merged = work / "merged"
    if not (merged / "config.json").exists():
        model = L.load_model(base_hf, adapter)
        model = model.merge_and_unload()
        model.save_pretrained(str(merged), max_shard_size="5GB")
        del model
        torch.cuda.empty_cache()
        for f in Path(base_hf).iterdir():   # tokenizer、chat template、processor 設定
            if f.suffix in (".json", ".jinja", ".txt") and not f.name.startswith("model") and f.name != "config.json":
                shutil.copy(f, merged / f.name)
    q8 = work / "typo-q8_0.gguf"
    if not q8.exists():
        sh([sys.executable, str(LLAMA_CPP / "convert_hf_to_gguf.py"), str(merged), "--outfile", str(q8), "--outtype", "q8_0"])
    shutil.rmtree(merged, ignore_errors=True)
    qtype = base_quant(base_tag)
    final = work / f"typo-{qtype}.gguf"
    if qtype.upper() in ("Q8_0",):
        q8.rename(final)
    else:
        sh([str(LLAMA_CPP / "build" / "bin" / "llama-quantize"), "--allow-requantize", str(q8), str(final), qtype])
        q8.unlink(missing_ok=True)
    mf = base_modelfile(base_tag)
    mf = re.sub(r"^FROM .*$", f"FROM {final}", mf, count=1, flags=re.M)
    mf = re.sub(r"^ADAPTER .*$\n?", "", mf, flags=re.M)
    create(name, mf, work)
    return final


def smoke(data: str, base_tag: str, name: str, base_hf: str, adapter: str, n: int = 4) -> bool:
    """Ollama 版要「跟原版不同」而且「跟 transformers+adapter 的結果夠像」。"""
    import difflib
    import eval_typo as E
    rows = [json.loads(x) for x in Path(data, "sft_dev.jsonl").open(encoding="utf-8")][:n]
    try:   # 先跑 transformers（此時 Ollama 還沒載入模型，顯示卡記憶體夠）
        import gc
        import torch
        b = E.HFBackend(base_hf, adapter)
        hf = b.generate(rows)
        del b
        gc.collect()
        torch.cuda.empty_cache()
    except Exception as exc:
        print("（transformers 比對略過：", exc, "）")
        hf = [r["target"] for r in rows]
    o_base = E.OllamaBackend(base_tag, "http://127.0.0.1:11434").generate(rows)
    o_ft = E.OllamaBackend(name, "http://127.0.0.1:11434").generate(rows)
    diff_base = sum(a.strip() != b.strip() for a, b in zip(o_base, o_ft))
    sim = sum(difflib.SequenceMatcher(None, a, b).ratio() for a, b in zip(o_ft, hf)) / len(rows)
    for r, a, b, c in zip(rows, o_base, o_ft, hf):
        print("--", r["id"], "\n  原版:", a[:160].replace("\n", " / "), "\n  微調:", b[:160].replace("\n", " / "),
              "\n  HF  :", c[:160].replace("\n", " / "))
    print(f"冒煙測試：{diff_base}/{len(rows)} 批和原版不同；和 transformers 版相似度 {sim:.2f}")
    return diff_base > 0 and sim >= 0.6


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-hf", required=True)
    ap.add_argument("--adapter", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--base-tag", default="qwen3.8:27b")
    ap.add_argument("--name", default="qwen3.8-27b-typo")
    ap.add_argument("--work", default="/content/ft_export")
    ap.add_argument("--save", required=True, help="Google Drive 上存放產物的資料夾")
    ap.add_argument("--plan", choices=["auto", "a", "b"], default="auto")
    a = ap.parse_args()
    work = Path(a.work)
    work.mkdir(parents=True, exist_ok=True)
    save = Path(a.save)
    save.mkdir(parents=True, exist_ok=True)

    used, artifact = None, None
    if a.plan in ("auto", "a"):
        try:
            artifact = plan_a(a.base_hf, a.adapter, a.base_tag, a.name, work)
            if smoke(a.data, a.base_tag, a.name, a.base_hf, a.adapter):
                used = "a"
            else:
                print("做法 A 的冒煙測試沒通過")
        except Exception as exc:
            print("做法 A 失敗：", exc)
    if used is None and a.plan in ("auto", "b"):
        artifact = plan_b(a.base_hf, a.adapter, a.base_tag, a.name, work)
        if not smoke(a.data, a.base_tag, a.name, a.base_hf, a.adapter):
            raise SystemExit("做法 B 冒煙測試也沒通過，請檢查訓練結果")
        used = "b"
    if used is None:
        raise SystemExit("匯出失敗")
    shutil.copy(artifact, save / artifact.name)
    info = {"plan": used, "file": artifact.name, "name": a.name, "base_tag": a.base_tag,
            "modelfile": (work / "Modelfile").read_text(encoding="utf-8").replace(str(artifact), artifact.name)}
    (save / "ollama_model.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    print("完成：", info)


if __name__ == "__main__":
    main()
