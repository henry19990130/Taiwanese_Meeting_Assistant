"""步驟 3（Colab GPU）：LoRA 微調 Qwen3.8-27B 的錯字校正能力。

- 只訓練語言模型的注意力與 MLP 投影層（LoRA），原始權重不動；視覺部分完全不碰。
- loss 只算「模型的回答」那段，prompt（系統指令＋逐字稿）不算。
- checkpoint 存到 --out（請放在 Google Drive），斷線後重跑會自動接續。
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lm_utils as L  # noqa: E402

# 全注意力層：q/k/v/o；線性注意力層（Gated DeltaNet）：in_proj_qkv / in_proj_z / out_proj；每層的 MLP。
_MODS = (r"(self_attn\.(q_proj|k_proj|v_proj|o_proj)|linear_attn\.(in_proj_qkv|in_proj_z|out_proj)"
         r"|mlp\.(gate_proj|up_proj|down_proj))$")
TARGET = r"^(base_model\.model\.)?model\.(language_model\.)?layers\.\d+\." + _MODS


def encode(tok, ex: dict, max_len: int):
    prompt = L.chat_prompt(tok, ex["system"], ex["user"])
    answer = ex["target"] + L.end_text(tok) + "\n"
    p_ids = tok(prompt, add_special_tokens=False)["input_ids"]
    a_ids = tok(answer, add_special_tokens=False)["input_ids"]
    if len(p_ids) + len(a_ids) > max_len:
        return None
    return {"input_ids": p_ids + a_ids, "labels": [-100] * len(p_ids) + a_ids}


class Collator:
    def __init__(self, pad_id: int):
        self.pad_id = pad_id

    def __call__(self, feats):
        import torch
        n = max(len(f["input_ids"]) for f in feats)
        ids = torch.full((len(feats), n), self.pad_id, dtype=torch.long)
        lab = torch.full((len(feats), n), -100, dtype=torch.long)
        att = torch.zeros((len(feats), n), dtype=torch.long)
        for i, f in enumerate(feats):
            k = len(f["input_ids"])
            ids[i, :k] = torch.tensor(f["input_ids"])
            lab[i, :k] = torch.tensor(f["labels"])
            att[i, :k] = 1
        return {"input_ids": ids, "labels": lab, "attention_mask": att}


def make_trainer_cls(Trainer, TrainerCallback):
    """長輸入省記憶體：不產生整段的 logits，只對「回答」那段分塊算 lm_head + loss（每塊用 checkpoint 重算）。"""
    import torch
    import torch.nn.functional as F
    from torch.utils.checkpoint import checkpoint

    def _ce(h, lab, head):
        return F.cross_entropy(head(h).float().reshape(-1, head.out_features), lab.reshape(-1),
                               ignore_index=-100, reduction="sum")

    class AnswerOnlyTrainer(Trainer):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self.model_accepts_loss_kwargs = False  # 每筆取平均，Trainer 再除以 grad_accum

        def compute_loss(self, model, inputs, return_outputs=False, num_items_in_batch=None):
            labels = inputs["labels"]
            n = labels.shape[1]
            valid = labels != -100
            first = int(valid.float().argmax(dim=1).min().item()) if valid.any() else n - 1
            first = max(1, first)
            base = model.get_base_model() if hasattr(model, "get_base_model") else model
            hid = base.model(input_ids=inputs["input_ids"], attention_mask=inputs["attention_mask"],
                             use_cache=False).last_hidden_state
            h = hid[:, first - 1:n - 1]
            lab = labels[:, first:n]
            head = base.lm_head
            tot = torch.zeros((), device=h.device, dtype=torch.float32)
            for i in range(0, h.shape[1], 1024):
                tot = tot + checkpoint(_ce, h[:, i:i + 1024], lab[:, i:i + 1024], head, use_reentrant=False)
            loss = tot / (lab != -100).sum().clamp(min=1)
            return (loss, None) if return_outputs else loss

        def prediction_step(self, model, inputs, prediction_loss_only, ignore_keys=None):
            with torch.no_grad():
                loss = self.compute_loss(model, inputs)
            return (loss.detach(), None, None)

    class MemCallback(TrainerCallback):
        def on_step_end(self, args, state, control, **kw):
            if state.global_step <= 2 or state.global_step % 5 == 0:
                print(f"[step {state.global_step}] 顯示卡記憶體峰值 {torch.cuda.max_memory_allocated() / 2**30:.1f} GB", flush=True)

    return AnswerOnlyTrainer, MemCallback

def load(path: Path, kinds: set[str] | None = None) -> list[dict]:
    rows = [json.loads(x) for x in path.open(encoding="utf-8") if x.strip()]
    return [r for r in rows if kinds is None or r["kind"] in kinds]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--epochs", type=float, default=2.0)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--alpha", type=int, default=32)
    ap.add_argument("--max-len", type=int, default=6144)
    ap.add_argument("--grad-accum", type=int, default=16)
    ap.add_argument("--save-steps", type=int, default=20)
    ap.add_argument("--dev-limit", type=int, default=48)
    ap.add_argument("--load-4bit", action="store_true", help="顯示卡記憶體不夠時改用 QLoRA")
    ap.add_argument("--max-steps", type=int, default=-1, help="測試用")
    ap.add_argument("--max-train", type=int, default=1200, help="訓練樣本上限（控制 Colab 時數）；0 = 全部")
    a = ap.parse_args()

    # Colab 內建的舊版 torchao（0.10）會讓新版 peft 直接報錯；本專案用不到它，有舊版就移除
    try:
        import importlib.metadata as md
        from packaging.version import Version
        if Version(md.version("torchao")) < Version("0.16.0"):
            import subprocess
            print("移除不相容的舊版 torchao", md.version("torchao"), flush=True)
            subprocess.run([sys.executable, "-m", "pip", "uninstall", "-y", "-q", "torchao"], check=False)
    except Exception:
        pass

    import os
    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
    import torch
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import Trainer, TrainerCallback, TrainingArguments, trainer_utils

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    tok = L.load_tokenizer(a.base)

    train_rows = load(Path(a.data) / "sft_train.jsonl")
    dev_rows = load(Path(a.data) / "sft_dev.jsonl")
    random.Random(0).shuffle(dev_rows)
    random.Random(1).shuffle(train_rows)
    if a.max_train:
        train_rows = train_rows[:a.max_train]
    train = [e for e in (encode(tok, r, a.max_len) for r in train_rows) if e]
    dev = [e for e in (encode(tok, r, a.max_len) for r in dev_rows) if e][:a.dev_limit]
    lens = sorted(len(e["input_ids"]) for e in train)
    print(f"訓練 {len(train)} 筆（超過 {a.max_len} token 丟掉 {len(train_rows) - len(train)} 筆）；"
          f"dev {len(dev)} 筆；長度中位數 {lens[len(lens) // 2]}、最大 {lens[-1]}", flush=True)

    model = L.load_model(a.base, load_4bit=a.load_4bit)
    model.config.use_cache = False
    if a.load_4bit:
        model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    else:
        model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
        model.enable_input_require_grads()
    lcfg = LoraConfig(r=a.rank, lora_alpha=a.alpha, lora_dropout=0.05, bias="none", task_type="CAUSAL_LM",
                      target_modules=TARGET)
    model = get_peft_model(model, lcfg)
    model.print_trainable_parameters()
    gb = model.get_base_model()
    gb.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    gb.enable_input_require_grads()
    n_ckpt = sum(1 for m in gb.modules() if getattr(m, "gradient_checkpointing", False))
    print("gradient checkpointing 開啟的模組數：", n_ckpt, flush=True)
    names = [n for n, _ in model.named_modules() if n.endswith("lora_A")]
    print("LoRA 掛在", len(names), "個模組，例如", names[:3], flush=True)
    if not names:
        raise RuntimeError("LoRA 沒有掛上任何模組，請檢查 TARGET 正規表示式")

    steps_per_epoch = math.ceil(len(train) / a.grad_accum)
    total_steps = a.max_steps if a.max_steps > 0 else math.ceil(steps_per_epoch * a.epochs)
    args = TrainingArguments(
        output_dir=str(out / "checkpoints"),
        per_device_train_batch_size=1, per_device_eval_batch_size=1,
        gradient_accumulation_steps=a.grad_accum,
        num_train_epochs=a.epochs, max_steps=a.max_steps,
        learning_rate=a.lr, lr_scheduler_type="cosine", warmup_steps=max(1, int(total_steps * 0.03)), weight_decay=0.0,
        bf16=torch.cuda.is_available(), logging_steps=2,
        eval_strategy="steps" if dev else "no", eval_steps=a.save_steps, save_strategy="steps", save_steps=a.save_steps,
        save_total_limit=3, load_best_model_at_end=bool(dev), metric_for_best_model="eval_loss", greater_is_better=False,
        report_to="none", remove_unused_columns=False, dataloader_num_workers=0, label_names=["labels"],
        gradient_checkpointing=False,  # 上面已經自己開好
        seed=42,
    )
    print(f"每個 epoch {steps_per_epoch} 步，共 {a.epochs} 個 epoch", flush=True)
    TCls, MemCb = make_trainer_cls(Trainer, TrainerCallback)
    trainer = TCls(model=model, args=args, train_dataset=train, eval_dataset=dev or None,
                   data_collator=Collator(tok.pad_token_id), callbacks=[MemCb()])
    last = trainer_utils.get_last_checkpoint(str(out / "checkpoints")) if (out / "checkpoints").exists() else None
    if last:
        print("接續上次的 checkpoint：", last, flush=True)
    trainer.train(resume_from_checkpoint=last)
    final = out / "final"
    trainer.model.save_pretrained(str(final))
    tok.save_pretrained(str(final))
    hist = [h for h in trainer.state.log_history]
    (out / "train_log.json").write_text(json.dumps(hist, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "train_args.json").write_text(json.dumps(vars(a), ensure_ascii=False, indent=1), encoding="utf-8")
    print("完成，adapter 存在", final, "（最佳 checkpoint：", trainer.state.best_model_checkpoint, "）")


if __name__ == "__main__":
    main()
