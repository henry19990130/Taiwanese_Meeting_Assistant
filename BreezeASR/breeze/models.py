from dataclasses import dataclass


@dataclass(frozen=True)
class Recognition:
    text: str
    model: str
    device: str


@dataclass(frozen=True)
class Transcript:
    id: str
    source_filename: str
    text: str
    model: str
    device: str
    created_at: str
    title: str = ""
    tags: tuple[str, ...] = ()
    summary_filename: str = ""
