"""
Redis + RQ job store for async pipeline runs.

Shared helpers live here so Phase 6 HITL routes can reuse job metadata,
events, results, and cleanup without duplicating Redis key logic.
"""

from __future__ import annotations

import json
import os
import shutil
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Literal

import redis
import structlog
from rq import Queue
from rq.job import Job as RQJob

from dmag.config import (
    JOB_TIMEOUT_SEC,
    JOB_TTL_SEC,
    REDIS_URL,
    RQ_QUEUE_NAME,
)
from dmag.gemini_client import configure_logging

configure_logging()
logger = structlog.get_logger(__name__)

JobStatus = Literal["pending", "running", "complete", "error"]


class ErrorCode(str, Enum):
    """Typed error codes surfaced on SSE ``failed`` events and job meta."""

    JOB_NOT_FOUND = "job_not_found"
    MISSING_API_KEY = "missing_api_key"
    PIPELINE_ERROR = "pipeline_error"
    EMBEDDING_ERROR = "embedding_error"
    RATE_LIMITED = "rate_limited"
    INVALID_UPLOAD = "invalid_upload"
    REDIS_UNAVAILABLE = "redis_unavailable"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Redis helpers
# ---------------------------------------------------------------------------

_redis: redis.Redis | None = None


def get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.from_url(REDIS_URL, decode_responses=True)
    return _redis


def get_queue() -> Queue:
    # RQ needs a binary-safe connection for job payloads
    conn = redis.from_url(REDIS_URL)
    return Queue(RQ_QUEUE_NAME, connection=conn)


def _meta_key(job_id: str) -> str:
    return f"dmag:job:{job_id}:meta"


def _events_key(job_id: str) -> str:
    return f"dmag:job:{job_id}:events"


def _result_key(job_id: str) -> str:
    return f"dmag:job:{job_id}:result"


def _touch_ttl(r: redis.Redis, job_id: str) -> None:
    ttl = JOB_TTL_SEC
    r.expire(_meta_key(job_id), ttl)
    r.expire(_events_key(job_id), ttl)
    r.expire(_result_key(job_id), ttl)


# ---------------------------------------------------------------------------
# Job record (API-facing view; backed by Redis)
# ---------------------------------------------------------------------------


@dataclass
class JobRecord:
    """Snapshot of job state for API handlers."""

    job_id: str
    raw_dir: Path
    output_dir: Path
    template_path: Path | None
    status: JobStatus = "pending"
    error: str | None = None
    error_code: str | None = None
    result: dict[str, Any] | None = None

    @property
    def events(self) -> list[dict[str, Any]]:
        return list_events(self.job_id)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def create_job(
    raw_dir: Path,
    output_dir: Path,
    template_path: Path | None = None,
) -> JobRecord:
    """Persist job metadata in Redis and return a JobRecord (not yet enqueued)."""
    job_id = str(uuid.uuid4())
    meta = {
        "job_id": job_id,
        "raw_dir": str(raw_dir),
        "output_dir": str(output_dir),
        "template_path": str(template_path) if template_path else "",
        "status": "pending",
        "error": "",
        "error_code": "",
    }
    r = get_redis()
    r.hset(_meta_key(job_id), mapping=meta)
    _touch_ttl(r, job_id)
    logger.info("job_created", job_id=job_id, step="create")
    return JobRecord(
        job_id=job_id,
        raw_dir=raw_dir,
        output_dir=output_dir,
        template_path=template_path,
        status="pending",
    )


def enqueue_pipeline(job_id: str) -> str:
    """Enqueue RQ worker task. Returns RQ job id (same as our job_id)."""
    q = get_queue()
    rq_job = q.enqueue(
        execute_pipeline,
        job_id,
        job_id=job_id,
        job_timeout=JOB_TIMEOUT_SEC,
        result_ttl=JOB_TTL_SEC,
        failure_ttl=JOB_TTL_SEC,
    )
    logger.info("job_enqueued", job_id=job_id, rq_job_id=rq_job.id, step="enqueue")
    return rq_job.id


def get_job(job_id: str) -> JobRecord | None:
    """Load job metadata (+ result if present) from Redis."""
    r = get_redis()
    meta = r.hgetall(_meta_key(job_id))
    if not meta:
        return None
    template_raw = meta.get("template_path") or ""
    result_raw = r.get(_result_key(job_id))
    result = json.loads(result_raw) if result_raw else None
    return JobRecord(
        job_id=job_id,
        raw_dir=Path(meta["raw_dir"]),
        output_dir=Path(meta["output_dir"]),
        template_path=Path(template_raw) if template_raw else None,
        status=meta.get("status", "pending"),  # type: ignore[arg-type]
        error=meta.get("error") or None,
        error_code=meta.get("error_code") or None,
        result=result,
    )


def list_events(job_id: str) -> list[dict[str, Any]]:
    r = get_redis()
    raw = r.lrange(_events_key(job_id), 0, -1)
    return [json.loads(item) for item in raw]


def push_event(
    job_id: str,
    step: int,
    total: int,
    message: str,
    status: JobStatus | None = None,
) -> None:
    r = get_redis()
    if status:
        r.hset(_meta_key(job_id), "status", status)
    evt = {
        "step": step,
        "total": total,
        "message": message,
        "status": status or (r.hget(_meta_key(job_id), "status") or "running"),
    }
    r.rpush(_events_key(job_id), json.dumps(evt))
    _touch_ttl(r, job_id)
    logger.info(
        "job_event",
        job_id=job_id,
        step=step,
        total=total,
        message=message,
        status=evt["status"],
    )


def set_status(job_id: str, status: JobStatus) -> None:
    r = get_redis()
    r.hset(_meta_key(job_id), "status", status)
    _touch_ttl(r, job_id)


def set_error(job_id: str, error: str, error_code: ErrorCode | str = ErrorCode.PIPELINE_ERROR) -> None:
    code = error_code.value if isinstance(error_code, ErrorCode) else error_code
    r = get_redis()
    r.hset(
        _meta_key(job_id),
        mapping={"status": "error", "error": error, "error_code": code},
    )
    push_event(job_id, 0, 8, error, status="error")
    _touch_ttl(r, job_id)
    logger.error("job_failed", job_id=job_id, step="error", error=error, error_code=code)


def set_complete(job_id: str, result_payload: dict[str, Any]) -> None:
    r = get_redis()
    r.set(_result_key(job_id), json.dumps(result_payload))
    r.hset(_meta_key(job_id), mapping={"status": "complete", "error": "", "error_code": ""})
    push_event(job_id, 8, 8, "Pipeline complete", status="complete")
    _touch_ttl(r, job_id)
    logger.info("job_complete", job_id=job_id, step="complete")


def save_result(job_id: str, result_payload: dict[str, Any]) -> None:
    """Update result JSON in Redis without changing status (HITL edits / re-export)."""
    r = get_redis()
    r.set(_result_key(job_id), json.dumps(result_payload))
    _touch_ttl(r, job_id)
    logger.info("job_result_saved", job_id=job_id, step="hitl")


def classify_error(exc: BaseException) -> ErrorCode:
    msg = str(exc).lower()
    name = type(exc).__name__.lower()
    if "gemini_api_key" in msg or "api key" in msg:
        return ErrorCode.MISSING_API_KEY
    if "429" in msg or "resource_exhausted" in msg or ("rate" in msg and "limit" in msg):
        return ErrorCode.RATE_LIMITED
    if "embedding" in msg or "embeddingerror" in name:
        return ErrorCode.EMBEDDING_ERROR
    if "timeout" in msg:
        return ErrorCode.TIMEOUT
    return ErrorCode.PIPELINE_ERROR


def cleanup_job_dirs(
    job_id: str,
    *,
    raw_dir: Path | None = None,
    output_dir: Path | None = None,
    keep_output: bool = False,
) -> None:
    """
    Remove temp dirs for a job.

    On success: delete raw uploads; keep output for download until Redis TTL.
    On failure: delete both.
    """
    job = get_job(job_id)
    raw = raw_dir or (job.raw_dir if job else None)
    out = output_dir or (job.output_dir if job else None)
    if raw and raw.exists():
        shutil.rmtree(raw, ignore_errors=True)
        logger.info("cleanup_raw", job_id=job_id, path=str(raw))
    if out and out.exists() and not keep_output:
        shutil.rmtree(out, ignore_errors=True)
        logger.info("cleanup_output", job_id=job_id, path=str(out))


def redis_healthy() -> bool:
    try:
        return bool(get_redis().ping())
    except Exception:
        return False


def gemini_key_present() -> bool:
    return bool(os.getenv("GEMINI_API_KEY"))


# ---------------------------------------------------------------------------
# RQ worker entrypoint
# ---------------------------------------------------------------------------


def execute_pipeline(job_id: str) -> dict[str, Any]:
    """
    RQ worker function: run the full pipeline for ``job_id``.

    Importable as ``api.jobs.execute_pipeline`` for ``rq worker``.
    """
    import time

    from dmag.config import TEMPLATE_PATH as DEFAULT_TEMPLATE
    from dmag.pipeline import run_pipeline

    t0 = time.perf_counter()
    job = get_job(job_id)
    if not job:
        logger.error("job_missing_in_worker", job_id=job_id)
        raise RuntimeError(f"Job {job_id} not found in Redis")

    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(job_id=job_id)

    set_status(job_id, "running")
    push_event(job_id, 0, 8, "Pipeline started", status="running")

    def on_progress(step: int, total: int, message: str) -> None:
        push_event(job_id, step, total, message, status="running")

    try:
        if not gemini_key_present():
            raise RuntimeError("GEMINI_API_KEY not set in .env")

        template = (
            job.template_path
            if job.template_path and job.template_path.exists()
            else DEFAULT_TEMPLATE
        )
        result = run_pipeline(
            raw_dir=job.raw_dir,
            template_path=template,
            output_dir=job.output_dir,
            on_progress=on_progress,
            job_id=job_id,
        )
        payload = {
            "memo": result.memo.model_dump(),
            "stats": {
                "doc_count": result.doc_count,
                "chunk_count": result.chunk_count,
                "section_count": result.section_count,
                "flag_count": result.flag_count,
                "supported_claim_rate": result.supported_claim_rate,
            },
            "output_docx": str(result.output_docx),
            "output_json": str(result.output_json),
        }
        set_complete(job_id, payload)
        # Seed HITL review_state.json beside job output
        try:
            from api.review import seed_review_state

            seed_review_state(job_id)
        except Exception as seed_exc:
            logger.warning("review_state_seed_failed", job_id=job_id, error=str(seed_exc))
        # Keep output for download; drop uploaded raw files
        cleanup_job_dirs(job_id, raw_dir=job.raw_dir, output_dir=job.output_dir, keep_output=True)
        latency_ms = int((time.perf_counter() - t0) * 1000)
        logger.info("pipeline_done", job_id=job_id, step="complete", latency_ms=latency_ms)
        return payload
    except Exception as exc:
        code = classify_error(exc)
        set_error(job_id, str(exc), code)
        cleanup_job_dirs(job_id, raw_dir=job.raw_dir, output_dir=job.output_dir, keep_output=False)
        latency_ms = int((time.perf_counter() - t0) * 1000)
        logger.error(
            "pipeline_failed",
            job_id=job_id,
            step="error",
            latency_ms=latency_ms,
            error_code=code.value,
            error=str(exc),
        )
        raise


def get_rq_job(job_id: str) -> RQJob | None:
    """Optional: fetch underlying RQ job (useful for HITL / diagnostics)."""
    try:
        conn = redis.from_url(REDIS_URL)
        return RQJob.fetch(job_id, connection=conn)
    except Exception:
        return None
