"""（覆蓋版 export_ollama.py）Ollama 無法載入轉出的 GGUF（HTTP 500）時的備案：

1. 收集 Ollama 的錯誤紀錄，存到 export/ollama_diagnose.txt，之後修部署用
2. 用 transformers 載入同一份 Qwen3.8-27B 權重（bf16），在同一份測試資料上跑兩次：
   - 不掛 LoRA = 原版（results/base_hf.json）
   - 掛上 LoRA = 微調版（results/ft_hf.json）
   兩者只差在 LoRA，其餘（權重精度、prompt、解析程式、測試資料）完全相同 → 公平比較微調的效果
3. 寫 export/ollama_model.json（標記為 hf-only）、results/ft_ollama.json（指向 HF 結果），讓 notebook 下一格可以接著跑報告
"""
from __future__ import annotations

import argparse
import contextlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import eval_typo as E  # noqa: E402
import ft_common as F  # noqa: E402


def diagnose(save: Path, name: str):
    out = []
    for cmd in (["ollama", "list"], ["ollama", "ps"], ["ollama", "show", name]):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True)
            out.append("$ " + " ".join(cmd) + "\n" + r.stdout + r.stderr)
        except FileNotFoundError:
            out.append("$ " + " ".join(cmd) + "\n（沒有 ollama）")
    for p in ["/content/Taiwanese_Meeting_Assistant/logs/ollama.log"]:
        if Path(p).exists():
            out.append(f"--- {p}（最後 120 行）---\n" + "".join(Path(p).read_text(errors="replace").splitlines(True)[-120:]))
    r = subprocess.run("ls -la /content/ft_export", shell=True, capture_output=True, text=True)
    out.append("$ ls -la /content/ft_export\n" + r.stdout)
    (save / "ollama_diagnose.txt").write_text("\n".join(out), encoding="utf-8")
    print("Ollama 診斷資料已存：", save / "ollama_diagnose.txt")


class Shared:
    """同一個模型，切換有沒有套用 LoRA。"""

    def __init__(self, base: str, adapter: str):
        import lm_utils as L
        self.L = L
        self.tok = L.load_tokenizer(base)
        self.tok.padding_side = "left"
        self.model = L.load_model(base, adapter)
        self.use_adapter = True

    def generate(self, batch):
        import re
        import torch
        texts = [self.L.chat_prompt(self.tok, ex["system"], ex["user"]) for ex in batch]
        enc = self.tok(texts, return_tensors="pt", padding=True, add_special_tokens=False).to(self.model.device)
        ctx = contextlib.nullcontext() if self.use_adapter else self.model.disable_adapter()
        with torch.no_grad(), ctx:
            gen = self.model.generate(**enc, max_new_tokens=640, do_sample=False, pad_token_id=self.tok.pad_token_id)
        outs = self.tok.batch_decode(gen[:, enc["input_ids"].shape[1]:], skip_special_tokens=True)
        return [re.sub(r"<think>.*?</think>", "", o, flags=re.S).strip() for o in outs]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-hf", required=True)
    ap.add_argument("--adapter", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--base-tag", default="qwen3.8:27b")
    ap.add_argument("--name", default="qwen3.8-27b-typo")
    ap.add_argument("--work", default="/content/ft_export")
    ap.add_argument("--save", required=True)
    ap.add_argument("--plan", default="auto")
    ap.add_argument("--batch-size", type=int, default=4)
    a = ap.parse_args()
    save = Path(a.save)
    save.mkdir(parents=True, exist_ok=True)
    results = save.parent / "results"
    results.mkdir(parents=True, exist_ok=True)

    diagnose(save, a.name)
    # 釋放 Ollama 占用的顯示卡記憶體
    subprocess.run("ollama ps | tail -n +2 | awk '{print $1}' | xargs -r -n1 ollama stop", shell=True)

    examples = sorted([json.loads(x) for x in Path(a.data, "sft_test.jsonl").open(encoding="utf-8")
                       if json.loads(x)["kind"] == "real"], key=lambda e: e["id"])
    print(f"transformers A/B 評測：{len(examples)} 批 × 2（原版／微調版）", flush=True)
    m = Shared(a.base_hf, a.adapter)
    for tag, use in [("base_hf", False), ("ft_hf", True)]:
        if (results / f"{tag}.json").exists():
            print("已完成，略過", tag)
            continue
        m.use_adapter = use
        print(f"== {tag}（{'掛 LoRA' if use else '不掛 LoRA'}）", flush=True)
        res = E.evaluate(examples, m, a.batch_size, results / f"{tag}.predictions.jsonl")
        res["_meta"] = {"name": tag, "backend": "hf-bf16", "model": f"Qwen3.8-27B bf16{' + LoRA' if use else ''}",
                        "adapter": a.adapter if use else None, "split": "test", "kinds": ["real"]}
        (results / f"{tag}.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({k: res[k] for k in ("zh", "en") if k in res}, ensure_ascii=False, indent=1), flush=True)

    shutil.copy(results / "ft_hf.json", results / "ft_ollama.json")
    info = {"plan": "hf-only", "name": a.name, "base_tag": a.base_tag,
            "note": "Ollama 無法載入轉出的 GGUF（/api/chat 回 500），微調效果改用 transformers A/B 評測；部署待修",
            "modelfile": f"FROM {a.base_tag}\n"}
    (save / "ollama_model.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    print("完成")


if __name__ == "__main__":
    main()
