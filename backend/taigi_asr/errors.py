from __future__ import annotations


class TaigiASRError(Exception):
    pass


class InsufficientVRAMError(TaigiASRError):
    pass


class ModelLoadError(TaigiASRError):
    pass


class TranscriptionError(TaigiASRError):
    pass
