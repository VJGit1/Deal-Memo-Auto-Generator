"""In-memory job store for async pipeline runs."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

JobStatus = Literal["pending", "running", "complete", "error"]


@dataclass
class Job:
    job_id: str
    raw_dir: Path
    output_dir: Path
    template_path: Path | None
    status: JobStatus = "pending"
    events: list[dict[str, Any]] = field(default_factory=list)
    result: Any | None = None
    error: str | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)

    def push_event(self, step: int, total: int, message: str, status: JobStatus | None = None) -> None:
        evt = {
            "step": step,
            "total": total,
            "message": message,
            "status": status or self.status,
        }
        with self.lock:
            self.events.append(evt)
            if status:
                self.status = status

    def set_running(self) -> None:
        with self.lock:
            self.status = "running"

    def set_complete(self, result: Any) -> None:
        with self.lock:
            self.status = "complete"
            self.result = result
            self.events.append(
                {"step": 8, "total": 8, "message": "Pipeline complete", "status": "complete"}
            )

    def set_error(self, error: str) -> None:
        with self.lock:
            self.status = "error"
            self.error = error
            self.events.append(
                {"step": 0, "total": 8, "message": error, "status": "error"}
            )


_jobs: dict[str, Job] = {}
_jobs_lock = threading.Lock()


def create_job(raw_dir: Path, output_dir: Path, template_path: Path | None) -> Job:
    job = Job(
        job_id=str(uuid.uuid4()),
        raw_dir=raw_dir,
        output_dir=output_dir,
        template_path=template_path,
    )
    with _jobs_lock:
        _jobs[job.job_id] = job
    return job


def get_job(job_id: str) -> Job | None:
    with _jobs_lock:
        return _jobs.get(job_id)
