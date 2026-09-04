"""独立后台 Worker：轮询解析/索引任务，不阻塞 FastAPI 的 HTTP 请求。"""

import logging
import signal
import time

from app.config import get_settings
from app.db import SessionLocal
from app.services.processing import ProcessingService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)
running = True


def stop_worker(*_) -> None:
    """收到 SIGINT/SIGTERM 时退出轮询，让当前代码路径安全结束。"""
    global running
    running = False


def main() -> None:
    """恢复异常中断的任务，然后持续领取并处理数据库任务队列。"""
    settings = get_settings()
    settings.ensure_directories()
    signal.signal(signal.SIGINT, stop_worker)
    signal.signal(signal.SIGTERM, stop_worker)
    with SessionLocal() as session:
        recovered = ProcessingService(session, settings).recover_stale_jobs()
        logger.info("Worker started; recovered %s stale jobs", recovered)
    while running:
        with SessionLocal() as session:
            service = ProcessingService(session, settings)
            job = service.claim_next_job()
            if job:
                service.process(job)
                continue
        time.sleep(settings.worker_poll_seconds)
    logger.info("Worker stopped")


if __name__ == "__main__":
    main()
