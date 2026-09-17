"""
Cross-platform RQ worker entrypoint for DMAG.

On Windows, rq.Worker crashes because os.fork() is not supported.
This runner automatically detects Windows and uses rq.SimpleWorker instead.
On Linux/macOS, it uses the standard forking rq.Worker.
"""

from __future__ import annotations

import sys
import redis
import structlog
from rq import Queue, SimpleWorker, Worker

from dmag.config import REDIS_URL, RQ_QUEUE_NAME
from dmag.gemini_client import configure_logging

configure_logging()
logger = structlog.get_logger(__name__)


def main() -> None:
    conn = redis.from_url(REDIS_URL)
    worker_cls = SimpleWorker if sys.platform == "win32" else Worker

    print(
        f"Starting DMAG RQ worker on queue '{RQ_QUEUE_NAME}' "
        f"using {worker_cls.__name__} (platform: {sys.platform})..."
    )
    logger.info(
        "worker_starting",
        queue=RQ_QUEUE_NAME,
        worker_class=worker_cls.__name__,
        platform=sys.platform,
    )

    worker = worker_cls([RQ_QUEUE_NAME], connection=conn)
    worker.work(with_scheduler=False)


if __name__ == "__main__":
    main()
