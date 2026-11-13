"""訓練與評測共用：組出和推論時完全相同的 prompt 文字（關閉 thinking）。"""
from __future__ import annotations


def chat_prompt(tok, system: str, user: str) -> str:
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    try:
        return tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True, enable_thinking=False)
    except TypeError:
        return tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)


def end_text(tok) -> str:
    """回答結尾：Qwen 系列是 <|im_end|>。"""
    eos = tok.eos_token or "<|im_end|>"
    return "<|im_end|>" if "<|im_end|>" in tok.get_vocab() else eos


def load_tokenizer(path: str):
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(path, trust_remote_code=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    return tok


def load_model(path: str, adapter: str | None = None, dtype: str = "bfloat16", load_4bit: bool = False):
    import torch
    from transformers import AutoConfig
    cfg = AutoConfig.from_pretrained(path, trust_remote_code=True)
    kw = {"dtype": getattr(torch, dtype), "device_map": "auto", "trust_remote_code": True, "low_cpu_mem_usage": True}
    if load_4bit:
        from transformers import BitsAndBytesConfig
        kw["quantization_config"] = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                                       bnb_4bit_compute_dtype=getattr(torch, dtype),
                                                       bnb_4bit_use_double_quant=True)
    if getattr(cfg, "vision_config", None) is not None:
        from transformers import AutoModelForImageTextToText as Auto
    else:
        from transformers import AutoModelForCausalLM as Auto
    model = Auto.from_pretrained(path, **kw)
    if adapter:
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, adapter)
    model.eval()
    return model
