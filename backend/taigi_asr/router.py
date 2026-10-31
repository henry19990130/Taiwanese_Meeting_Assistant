from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from taigi_asr.errors import InsufficientVRAMError


def _bitsandbytes_available() -> bool:
    try:
        import bitsandbytes
    except Exception:
        return False
    return True


class EngineKind(str, Enum):
    FASTER_WHISPER = "faster_whisper"
    HUGGINGFACE = "huggingface"


@dataclass(frozen=True, slots=True)
class GPUInfo:
    name: str
    vram_gb: float
    cuda_available: bool
    bf16_supported: bool


@dataclass(frozen=True, slots=True)
class EngineSpec:

    kind: EngineKind
    device: str
    compute_type: str
    batch_size: int


class GPUProfiler:

    @staticmethod
    def detect() -> GPUInfo:
        try:
            import torch
        except ImportError:
            return GPUInfo(name="CPU", vram_gb=0.0, cuda_available=False, bf16_supported=False)

        if not torch.cuda.is_available():
            return GPUInfo(name="CPU", vram_gb=0.0, cuda_available=False, bf16_supported=False)

        name = torch.cuda.get_device_name(0)
        props = torch.cuda.get_device_properties(0)
        vram_gb = props.total_memory / (1024**3)
        try:
            bf16 = bool(torch.cuda.is_bf16_supported())
        except Exception:
            bf16 = False
        return GPUInfo(
            name=name,
            vram_gb=round(vram_gb, 2),
            cuda_available=True,
            bf16_supported=bf16,
        )


class EngineRouter:

    @staticmethod
    def select(
        info: GPUInfo,
        prefer: EngineKind | None = None,
        strict: bool = False,
    ) -> EngineSpec:
        if not info.cuda_available:
            return EngineSpec(
                kind=EngineKind.FASTER_WHISPER,
                device="cpu",
                compute_type="int8",
                batch_size=1,
            )

        vram = info.vram_gb

        if prefer is EngineKind.HUGGINGFACE:
            if vram < 3.5:
                if strict:
                    raise InsufficientVRAMError(
                        f"HuggingFace engine needs >= 3.5 GB VRAM even in aggressive "
                        f"low-memory mode; detected {vram:.1f} GB."
                    )
                return EngineRouter._fw_spec(vram)
            return EngineRouter._hf_spec(vram)

        if prefer is EngineKind.FASTER_WHISPER:
            return EngineRouter._fw_spec(vram)

        if vram >= 6.0:
            return EngineRouter._hf_spec(vram)
        return EngineRouter._fw_spec(vram)

    @staticmethod
    def _fw_spec(vram: float) -> EngineSpec:
        if vram >= 14.0:
            batch, ct = 8, "float16"
        elif vram >= 3.5:
            batch, ct = 4, "int8_float16"
        else:
            batch, ct = 2, "int8_float16"
        return EngineSpec(
            kind=EngineKind.FASTER_WHISPER,
            device="cuda",
            compute_type=ct,
            batch_size=batch,
        )

    @staticmethod
    def _hf_spec(vram: float) -> EngineSpec:
        if vram >= 22.0:
            batch, ct = 16, "float16"
        elif vram >= 14.0:
            batch, ct = 8, "float16"
        elif vram >= 10.0:
            batch, ct = 4, "float16"
        elif vram >= 6.0:
            if _bitsandbytes_available():
                batch, ct = 2, "int8"
            else:
                batch, ct = 1, "float16"
        else:
            batch, ct = 1, "float16"
        return EngineSpec(
            kind=EngineKind.HUGGINGFACE,
            device="cuda",
            compute_type=ct,
            batch_size=batch,
        )
