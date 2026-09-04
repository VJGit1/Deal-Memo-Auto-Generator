"""
Shared Gemini helpers: retries with exponential backoff + structured logging.

All generate_content / embed_content call sites should go through this module
so rate limits and transient errors are handled consistently.
"""

from __future__ import annotations

import os
import random
import time
from collections.abc import Callable
from typing import Any, TypeVar

import structlog
from google import genai

from .config import EMBED_MAX_RETRIES, GEMINI_MAX_RETRIES, GEMINI_MODEL

logger = structlog.get_logger(__name__)

T = TypeVar("T")


def is_retryable(exc: BaseException) -> bool:
    """True for rate limits and transient Gemini/API failures."""
    msg = str(exc).lower()
    if "429" in msg or "resource_exhausted" in msg:
        return True
    if "rate" in msg and "limit" in msg:
        return True
    if "503" in msg or "unavailable" in msg or "timeout" in msg:
        return True
    if "500" in msg or "internal" in msg:
        return True
    if "11001" in msg or "getaddrinfo" in msg or "connection" in msg or "network" in msg:
        return True
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    return code in {408, 429, 500, 502, 503, 504}


def retry_call(
    fn: Callable[[], T],
    *,
    max_retries: int = GEMINI_MAX_RETRIES,
    model: str | None = None,
    job_id: str | None = None,
    step: str | None = None,
    op: str = "gemini_call",
) -> T:
    """
    Run ``fn`` with exponential backoff on retryable errors.

    Delay = min(2**attempt, 30) + jitter. Non-retryable errors raise immediately.
    """
    last_err: BaseException | None = None
    t0 = time.perf_counter()
    for attempt in range(max_retries):
        try:
            result = fn()
            latency_ms = int((time.perf_counter() - t0) * 1000)
            logger.info(
                op,
                job_id=job_id,
                step=step,
                model=model,
                latency_ms=latency_ms,
                attempt=attempt + 1,
            )
            return result
        except Exception as exc:
            last_err = exc
            if not is_retryable(exc) or attempt >= max_retries - 1:
                latency_ms = int((time.perf_counter() - t0) * 1000)
                logger.error(
                    f"{op}_failed",
                    job_id=job_id,
                    step=step,
                    model=model,
                    latency_ms=latency_ms,
                    attempt=attempt + 1,
                    error=str(exc),
                    retryable=is_retryable(exc),
                )
                raise
            delay = min(2**attempt, 30) + random.uniform(0, 0.5)
            logger.warning(
                f"{op}_retry",
                job_id=job_id,
                step=step,
                model=model,
                attempt=attempt + 1,
                delay_sec=round(delay, 2),
                error=str(exc),
            )
            time.sleep(delay)
    assert last_err is not None
    raise last_err


def get_client(api_key: str | None = None) -> genai.Client:
    key = api_key or os.getenv("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set")
    return genai.Client(api_key=key)


def generate_content(
    client: Any,
    *,
    model: str = GEMINI_MODEL,
    contents: Any,
    config: dict[str, Any] | None = None,
    max_retries: int = GEMINI_MAX_RETRIES,
    job_id: str | None = None,
    step: str | None = None,
) -> Any:
    """``client.models.generate_content`` with exponential backoff."""

    def _call():
        kwargs: dict[str, Any] = {"model": model, "contents": contents}
        if config is not None:
            kwargs["config"] = config
        return client.models.generate_content(**kwargs)

    return retry_call(
        _call,
        max_retries=max_retries,
        model=model,
        job_id=job_id,
        step=step,
        op="generate_content",
    )


def embed_content(
    client: Any,
    *,
    model: str,
    contents: Any,
    max_retries: int = EMBED_MAX_RETRIES,
    job_id: str | None = None,
    step: str | None = None,
) -> Any:
    """``client.models.embed_content`` with exponential backoff."""

    def _call():
        return client.models.embed_content(model=model, contents=contents)

    return retry_call(
        _call,
        max_retries=max_retries,
        model=model,
        job_id=job_id,
        step=step,
        op="embed_content",
    )


def configure_logging() -> None:
    """Configure structlog for JSON stdout (idempotent-ish)."""
    import logging
    import sys

    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=logging.INFO)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
