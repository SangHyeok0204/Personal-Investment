import json
import logging
import os
import signal
import sys
import time

from sqlalchemy import text

from db import get_engine, wait_for_db
from handlers import HANDLERS
from joblog import log_job

logger = logging.getLogger("worker")

_shutdown = False


def _handle_signal(signum, frame):
    global _shutdown
    _shutdown = True


def _get_required_env(name):
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def claim_job(engine):
    """Atomically claim one PENDING job. Returns its id, or None if none available."""
    with engine.begin() as conn:
        row = conn.execute(
            text(
                "SELECT id FROM jobs WHERE status = 'PENDING' ORDER BY created_at "
                "FOR UPDATE SKIP LOCKED LIMIT 1"
            )
        ).first()
        if row is None:
            return None
        job_id = row.id
        conn.execute(
            text(
                "UPDATE jobs SET status='RUNNING', started_at=now(), updated_at=now() "
                "WHERE id=:id"
            ),
            {"id": job_id},
        )
    return job_id


def fetch_job(engine, job_id):
    with engine.begin() as conn:
        row = (
            conn.execute(
                text("SELECT id, job_type, payload FROM jobs WHERE id=:id"),
                {"id": job_id},
            )
            .mappings()
            .first()
        )
    return dict(row)


def finish_job_success(engine, job_id, result):
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE jobs SET status='SUCCESS', result=CAST(:result AS JSONB), "
                "finished_at=now(), updated_at=now() WHERE id=:id"
            ),
            {"id": job_id, "result": json.dumps(result)},
        )


def finish_job_failure(engine, job_id, error_message):
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE jobs SET status='FAILED', error_message=:error_message, "
                "finished_at=now(), updated_at=now() WHERE id=:id"
            ),
            {"id": job_id, "error_message": error_message},
        )


def process_job(engine, job, storage_dir):
    job_id = job["id"]
    job_type = job["job_type"]
    payload = job["payload"] or {}

    log_job(engine, job_id, "INFO", "claimed", f"Job claimed (type={job_type})")

    handler = HANDLERS.get(job_type)
    if handler is None:
        error_message = f"Unknown job type: {job_type}"
        finish_job_failure(engine, job_id, error_message)
        log_job(engine, job_id, "ERROR", "failed", error_message)
        return

    try:
        result = handler(engine, job_id, payload, storage_dir, log_job)
    except Exception as exc:
        error_message = str(exc) or exc.__class__.__name__
        finish_job_failure(engine, job_id, error_message)
        log_job(engine, job_id, "ERROR", "failed", error_message)
        return

    finish_job_success(engine, job_id, result)
    log_job(engine, job_id, "INFO", "done", "Job completed successfully")


def run_one_cycle(engine, storage_dir):
    """Claim and process a single job. Returns True if a job was processed."""
    job_id = claim_job(engine)
    if job_id is None:
        return False
    job = fetch_job(engine, job_id)
    process_job(engine, job, storage_dir)
    return True


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )

    database_url = _get_required_env("DATABASE_URL")
    storage_dir = _get_required_env("STORAGE_DIR")
    poll_interval = float(os.environ.get("WORKER_POLL_INTERVAL_SECONDS", "2"))

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    engine = get_engine(database_url)
    wait_for_db(engine)

    logger.info("Worker started, polling every %ss", poll_interval)

    while not _shutdown:
        try:
            processed = run_one_cycle(engine, storage_dir)
        except Exception:
            logger.exception("Unexpected error during poll cycle")
            processed = False
        if not processed and not _shutdown:
            time.sleep(poll_interval)

    logger.info("Worker shutting down gracefully")
    sys.exit(0)


if __name__ == "__main__":
    main()
