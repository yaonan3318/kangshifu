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
    global running
    running = False


def main() -> None:
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

