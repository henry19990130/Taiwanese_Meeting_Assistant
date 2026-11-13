"""把 LoRA 直接加回原始權重檔（逐個 safetensors 分片處理）。

不經過 transformers 的 save_pretrained：輸出的檔名、分片、張量名稱、dtype 和官方 Qwen/Qwen3.8-27B 完全一樣，
只有被 LoRA 改到的 400 個權重數值不同。這樣 Ollama / llama.cpp 讀到的就是「官方格式」，避免轉換器不認得。

W_new = W + (B @ A) * (alpha / r)
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--adapter", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    import torch
    from safetensors import safe_open
    from safetensors.torch import load_file, save_file

    base, out = Path(a.base), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    cfg = json.loads((Path(a.adapter) / "adapter_config.json").read_text())
    scale = cfg["lora_alpha"] / cfg["r"]
    lora = load_file(str(Path(a.adapter) / "adapter_model.safetensors"))
    mods = sorted({k[: k.index(".lora_A")] for k in lora if ".lora_A" in k})
    print(f"LoRA：{len(mods)} 個模組，r={cfg['r']}，alpha={cfg['lora_alpha']}，scale={scale}", flush=True)

    index = json.loads((base / "model.safetensors.index.json").read_text())
    wmap = index["weight_map"]
    keys = list(wmap)

    def find(mod: str) -> str:
        m = mod.removeprefix("base_model.model.")
        if m + ".weight" in wmap:
            return m + ".weight"
        tail = re.search(r"layers\.\d+\..*$", m).group(0) + ".weight"
        hits = [k for k in keys if k.endswith(tail) and "visual" not in k and "vision" not in k and "mtp" not in k]
        if len(hits) != 1:
            raise RuntimeError(f"{mod} 對不到唯一的原始權重：{hits[:5]}")
        return hits[0]

    target = {find(m): m for m in mods}
    print("對應範例：", list(target.items())[:2], flush=True)
    by_shard: dict[str, list[str]] = {}
    for k in target:
        by_shard.setdefault(wmap[k], []).append(k)

    dev = "cuda" if torch.cuda.is_available() else "cpu"
    done = 0
    for shard in sorted(set(wmap.values())):
        src = base / shard
        if shard not in by_shard:
            shutil.copy(src, out / shard)
            continue
        with safe_open(str(src), "pt") as f:
            meta = f.metadata()
        t = load_file(str(src))
        for k in by_shard[shard]:
            m = target[k]
            A = lora[m + ".lora_A.weight"].to(dev, torch.float32)
            B = lora[m + ".lora_B.weight"].to(dev, torch.float32)
            w = t[k]
            delta = (B @ A) * scale
            if delta.shape != w.shape:
                raise RuntimeError(f"{k} 形狀不合：{tuple(w.shape)} vs {tuple(delta.shape)}")
            t[k] = (w.to(dev, torch.float32) + delta).to(w.dtype).cpu()
            done += 1
        save_file(t, str(out / shard), metadata=meta)
        print(f"  {shard}：合併 {len(by_shard[shard])} 個權重", flush=True)
        del t
    for f in base.iterdir():
        if f.is_file() and not f.name.endswith(".safetensors") and not (out / f.name).exists():
            shutil.copy(f, out / f.name)
    if done != len(mods):
        raise RuntimeError(f"只合併了 {done}/{len(mods)} 個")
    print(f"完成：合併 {done} 個權重 → {out}", flush=True)


if __name__ == "__main__":
    main()
