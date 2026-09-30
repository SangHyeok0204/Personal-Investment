import json
import logging
import os
import signal
import sys
import threading
import time

from sqlalchemy import text

from db import get_engine, wait_for_db
from handlers import HANDLERS
from joblog import log_job
from source_health import record_error, record_ok

logger = logging.getLogger("worker")

# ★(0019, 계획 P0) 큐마다 worker 를 따로 띄운다. 기본값 "default" 는 예전과 같은
#   한 줄 — 기존 도커 worker·테스트는 그대로 돈다.
DEFAULT_QUEUES = ("default",)
# 작업 중 심장박동 간격. 이 값의 몇 배 동안 소식이 없으면 죽은 작업으로 본다.
HEARTBEAT_SECONDS = 30
STALE_SECONDS = 5 * 60
# 매번 죽는 작업이 영원히 되살아나지 않게.
MAX_ATTEMPTS = 3

_shutdown = False


def _handle_signal(signum, frame):
    global _shutdown
    _shutdown = True


def _get_required_env(name):
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def claim_job(engine, queues=DEFAULT_QUEUES):
    """Atomically claim one PENDING job from `queues`. Returns its id, or None."""
    with engine.begin() as conn:
        row = conn.execute(
            text(
                "SELECT id FROM jobs WHERE status = 'PENDING' AND queue = ANY(:queues) "
                "ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1"
            ),
            {"queues": list(queues)},
        ).first()
        if row is None:
            return None
        job_id = row.id
        conn.execute(
            text(
                "UPDATE jobs SET status='RUNNING', started_at=now(), heartbeat_at=now(), "
                "attempts=attempts+1, updated_at=now() WHERE id=:id"
            ),
            {"id": job_id},
        )
    return job_id


def reap_stale_jobs(engine, queues=DEFAULT_QUEUES, stale_seconds=STALE_SECONDS,
                    max_attempts=MAX_ATTEMPTS):
    """심장박동이 끊긴 RUNNING 작업을 되살린다. 상한을 넘으면 FAILED.

    ⚠️없으면 도중에 죽은 작업(프로세스 종료·맥 재시동)은 **영원히 RUNNING** 이다 —
      `claim_job` 은 PENDING 만 집는다. 반환: (되살린 수, 포기한 수).
    """
    params = {"queues": list(queues), "stale": stale_seconds, "max": max_attempts}
    stale = (
        "status = 'RUNNING' AND queue = ANY(:queues) "
        "AND COALESCE(heartbeat_at, started_at, updated_at) < now() - make_interval(secs => :stale)"
    )
    with engine.begin() as conn:
        failed = conn.execute(
            text(
                f"UPDATE jobs SET status='FAILED', finished_at=now(), updated_at=now(), "
                f"error_message='심장박동이 끊긴 채 ' || attempts || '회 시도 — 포기' "
                f"WHERE {stale} AND attempts >= :max"
            ),
            params,
        ).rowcount
        revived = conn.execute(
            text(
                f"UPDATE jobs SET status='PENDING', started_at=NULL, heartbeat_at=NULL, "
                f"updated_at=now() WHERE {stale} AND attempts < :max"
            ),
            params,
        ).rowcount
    return revived, failed


def _beat(engine, job_id):
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE jobs SET heartbeat_at=now() WHERE id=:id AND status='RUNNING'"),
            {"id": job_id},
        )


class _Heartbeat:
    """작업이 도는 동안 `heartbeat_at` 을 주기적으로 갱신하는 배경 스레드."""

    def __init__(self, engine, job_id, interval=HEARTBEAT_SECONDS):
        self._engine, self._job_id, self._interval = engine, job_id, interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self._stop.wait(self._interval):
            try:
                _beat(self._engine, self._job_id)
            except Exception:
                logger.exception("heartbeat failed for job %s", self._job_id)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join(timeout=5)


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
        with _Heartbeat(engine, job_id):
            result = handler(engine, job_id, payload, storage_dir, log_job)
    except Exception as exc:
        error_message = str(exc) or exc.__class__.__name__
        finish_job_failure(engine, job_id, error_message)
        log_job(engine, job_id, "ERROR", "failed", error_message)
        return

    finish_job_success(engine, job_id, result)
    log_job(engine, job_id, "INFO", "done", "Job completed successfully")


def run_one_cycle(engine, storage_dir, queues=DEFAULT_QUEUES):
    """Claim and process a single job. Returns True if a job was processed."""
    job_id = claim_job(engine, queues)
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
    queues = tuple(
        q.strip() for q in os.environ.get("WORKER_QUEUES", "default").split(",") if q.strip()
    )
    worker_name = os.environ.get("WORKER_NAME") or "+".join(queues)

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    engine = get_engine(database_url)
    wait_for_db(engine)

    logger.info("Worker %s started on queues %s, polling every %ss",
                worker_name, queues, poll_interval)

    last_housekeeping = 0.0
    while not _shutdown:
        # 생존 신호 + 죽은 작업 되살리기 — 폴링마다 할 일은 아니라 30초에 한 번.
        if time.monotonic() - last_housekeeping >= HEARTBEAT_SECONDS:
            last_housekeeping = time.monotonic()
            try:
                revived, failed = reap_stale_jobs(engine, queues)
                if revived or failed:
                    logger.warning("reaped stale jobs: revived=%s failed=%s", revived, failed)
                record_ok(engine, f"worker:{worker_name}", kind="worker",
                          detail={"queues": list(queues), "pid": os.getpid()})
                # ★(계획 A3a) SEC 를 부르는 큐인데 연락처 UA 가 없으면 화면에 '설정 필요'.
                if "sec_crawl" in queues and not (os.environ.get("SEC_USER_AGENT") or "").strip():
                    record_error(engine, "sec", "config", "SEC_USER_AGENT 미설정 — .env.local 에 연락처 UA 필요")
            except Exception:
                logger.exception("housekeeping failed")
        try:
            processed = run_one_cycle(engine, storage_dir, queues)
        except Exception:
            logger.exception("Unexpected error during poll cycle")
            processed = False
        if not processed and not _shutdown:
            time.sleep(poll_interval)

    logger.info("Worker shutting down gracefully")
    sys.exit(0)


if __name__ == "__main__":
    main()
