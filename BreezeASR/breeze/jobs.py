import threading
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Job:
    id: str
    owner_id: str
    status: str
    percent: int
    stage: str
    message: str
    filename: str
    error: str | None = None
    transcript_id: str | None = None


class MemoryJobStore:
    """辨識進度只活在記憶體。逐字稿仍由 JSON store 負責持久化。"""

    def __init__(self):
        self._items: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self, job: Job) -> Job:
        with self._lock:
            self._items[job.id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._items.get(job_id)

    def update(self, job_id: str, **changes) -> Job | None:
        with self._lock:
            current = self._items.get(job_id)
            if current is None:
                return None
            updated = replace(current, **changes)
            self._items[job_id] = updated
            return updated
